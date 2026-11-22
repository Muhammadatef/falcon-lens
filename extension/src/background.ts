/**
 * Service worker.
 *  1. Top-frame navigation -> on-device prefilter -> full-page warning before the page is usable.
 *  2. Server confirmation (POST {api}/v1/check/url?wait=6) for the warning page, hover badge and popup.
 *
 * Privacy: the only thing ever sent is the URL being checked, to the configured API origin.
 * Verdicts are cached in chrome.storage.session (memory only) for 10 minutes. Nothing else is kept.
 */
import lexiconJson from "./generated/lexicon.json";
import { prefilter, type Lexicon } from "./prefilter";
import {
  ALLOW_TTL_MS, CACHE_TTL_MS, SERVER_WAIT_S, isWebUrl, loadSettings, normaliseBase, permissionPattern, slimVerdict,
  type CheckReply, type Message, type PrefilterReply, type Settings, type SlimVerdict,
} from "./shared";

const lex = lexiconJson as Lexicon;
const WARNING_PAGE = chrome.runtime.getURL("warning.html");
const MAX_CACHE = 200;
const VERDICT_ID = /^vd_[0-9A-HJKMNP-TV-Z]{26}$/;

interface CacheEntry { v: SlimVerdict; exp: number }

const inflight = new Map<string, Promise<CheckReply>>();

// Settings and the session cache hold an API key and recently checked URLs: keep both away from
// content scripts, which run next to untrusted pages.
void chrome.storage.local.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });
void chrome.storage.session.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });

/* ── state kept in memory so the navigation guard can answer in the same tick ───────────── */

interface State {
  settings: Settings;
  /** hosts the extension itself talks to (API, web app); they may sit on a tunnel */
  trusted: string[];
  /** "continue anyway" choices: host -> expiry. Mirrored to chrome.storage.session. */
  allow: Record<string, number>;
}
let state: State | undefined;

const hostOf = (u: string): string => {
  try {
    return new URL(u).hostname.toLowerCase();
  } catch {
    return "";
  }
};

async function load(): Promise<State> {
  const settings = await loadSettings();
  const allow = ((await chrome.storage.session.get("allow"))["allow"] ?? {}) as Record<string, number>;
  state = { settings, allow, trusted: [hostOf(settings.apiBase), hostOf(settings.webBase)].filter(Boolean) };
  return state;
}
let ready = load();
const getState = (): State | Promise<State> => state ?? ready;

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes["settings"]) ready = load();
});

async function allowHost(host: string): Promise<void> {
  const st = await getState();
  const now = Date.now();
  for (const [h, exp] of Object.entries(st.allow)) if (exp <= now) delete st.allow[h];
  st.allow[host] = now + ALLOW_TTL_MS;
  await chrome.storage.session.set({ allow: st.allow });
}

/* ── navigation guard ───────────────────────────────────────────────────────────────────── */

type NavDetails = { tabId: number; url: string; frameId: number; documentLifecycle?: string };
const warningUrl = (url: string): string => `${WARNING_PAGE}?u=${encodeURIComponent(url)}`;
const landedKey = (tabId: number): string => `landed:${tabId}`;

function guard(st: State, d: NavDetails, committed: boolean): void {
  const local = prefilter(d.url, lex, st.trusted);
  if (local.level !== "warn") {
    if (committed) void chrome.action.setBadgeText({ tabId: d.tabId, text: "" }).catch(() => {});
    return;
  }
  if ((st.allow[local.host] ?? 0) > Date.now()) {
    if (committed) {
      void chrome.action.setBadgeBackgroundColor({ tabId: d.tabId, color: "#F4B23A" }).catch(() => {});
      void chrome.action.setBadgeText({ tabId: d.tabId, text: "!" }).catch(() => {});
    }
    return;
  }
  // Replace the navigation with the warning page. No await before this call: every millisecond
  // here is time the risky page could use to load.
  void chrome.tabs.update(d.tabId, { url: warningUrl(d.url) }).catch(() => {});
  // If the risky document did commit (fast server, or it was reached through a redirect), it sits
  // in the tab's history behind the warning. Remember that so "Go back" steps over it.
  if (committed) void chrome.storage.session.set({ [landedKey(d.tabId)]: d.url });
}

function onNavigation(d: NavDetails, committed: boolean): void {
  if (d.frameId !== 0 || d.tabId < 0 || d.documentLifecycle === "prerender") return;
  const st = getState();
  if (st instanceof Promise) void st.then((s) => guard(s, d, committed)); // cold start only
  else guard(st, d, committed);
}

const WEB_ONLY = { url: [{ schemes: ["http", "https"] }] };
chrome.webNavigation.onBeforeNavigate.addListener((d) => onNavigation(d, false), WEB_ONLY);
// Second look at commit: after server redirects the committed URL can differ from the one first
// requested, and a very fast server can commit before the first replacement takes effect.
chrome.webNavigation.onCommitted.addListener((d) => onNavigation(d, true), WEB_ONLY);
chrome.tabs.onRemoved.addListener((tabId) => void chrome.storage.session.remove(landedKey(tabId)));

/* ── server confirmation ────────────────────────────────────────────────────────────────── */

async function cacheGet(key: string): Promise<SlimVerdict | null> {
  const e = (await chrome.storage.session.get(key))[key] as CacheEntry | undefined;
  if (!e) return null;
  if (e.exp <= Date.now()) {
    await chrome.storage.session.remove(key);
    return null;
  }
  return e.v;
}

async function cachePut(key: string, v: SlimVerdict): Promise<void> {
  const now = Date.now();
  const all = (await chrome.storage.session.get(null)) as Record<string, CacheEntry>;
  const mine = Object.entries(all).filter(([k]) => k.startsWith("c:"));
  const dead = mine.filter(([, e]) => e.exp <= now).map(([k]) => k);
  const live = mine.filter(([, e]) => e.exp > now).sort((a, b) => a[1].exp - b[1].exp);
  for (let i = 0; live.length - i >= MAX_CACHE; i++) dead.push(live[i]![0]);
  if (dead.length) await chrome.storage.session.remove(dead);
  await chrome.storage.session.set({ [key]: { v, exp: now + CACHE_TTL_MS } satisfies CacheEntry });
}

async function api(s: Settings, path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (s.apiKey) headers["X-API-Key"] = s.apiKey;
  return fetch(s.apiBase + path, {
    ...init,
    headers,
    credentials: "omit",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    redirect: "error",
    signal: AbortSignal.timeout(timeoutMs),
  });
}

async function serverCheck(rawUrl: string): Promise<CheckReply> {
  if (!isWebUrl(rawUrl)) return { ok: false, error: "unsupported" };
  const s = (await getState()).settings;
  if (!s.serverChecks) return { ok: false, error: "disabled" };
  const origin = normaliseBase(s.apiBase);
  if (!origin) return { ok: false, error: "offline" };
  if (!(await chrome.permissions.contains({ origins: [permissionPattern(origin)] }))) return { ok: false, error: "no_permission" };

  // The fragment never reaches a web server, so it is not part of what is checked.
  const u = new URL(rawUrl);
  u.hash = "";
  const url = u.href;
  const key = "c:" + url;
  const hit = await cacheGet(key);
  if (hit) return { ok: true, verdict: hit };

  try {
    const res = await api(
      s,
      `/v1/check/url?wait=${SERVER_WAIT_S}`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) },
      (SERVER_WAIT_S + 4) * 1000,
    );
    if (res.status === 429) return { ok: false, error: "rate_limited" };
    if (res.status !== 200 && res.status !== 202) return { ok: false, error: "bad_response" };
    const body = (await res.json()) as Record<string, unknown>;
    let verdict = slimVerdict(body);
    // 202 with no verdict yet is the Accepted shape: ask once more for the latest partial verdict.
    if (!verdict && typeof body["verdict_id"] === "string" && VERDICT_ID.test(body["verdict_id"])) {
      const again = await api(s, `/v1/verdicts/${body["verdict_id"]}`, { method: "GET" }, 4000);
      if (again.status === 200 || again.status === 202) verdict = slimVerdict(await again.json());
    }
    if (!verdict) return { ok: false, error: "bad_response" };
    if (verdict.final) await cachePut(key, verdict);
    return { ok: true, verdict };
  } catch {
    return { ok: false, error: "offline" };
  }
}

function checkOnce(url: string): Promise<CheckReply> {
  let p = inflight.get(url);
  if (!p) {
    p = serverCheck(url).finally(() => inflight.delete(url));
    inflight.set(url, p);
  }
  return p;
}

async function ping(): Promise<{ ok: boolean }> {
  try {
    const res = await api((await getState()).settings, "/v1/version", { method: "GET" }, 5000);
    return { ok: res.ok };
  } catch {
    return { ok: false };
  }
}

/* ── messages ───────────────────────────────────────────────────────────────────────────── */

chrome.runtime.onMessage.addListener((msg: Message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !msg || typeof msg !== "object") return false;
  const fromPage = (sender.url ?? "").startsWith(chrome.runtime.getURL(""));
  const fromWarning = (sender.url ?? "").startsWith(WARNING_PAGE);
  const url = "url" in msg && typeof msg.url === "string" ? msg.url.slice(0, 4096) : "";
  switch (msg.type) {
    case "prefilter":
      void (async () => {
        const st = await getState();
        const out: PrefilterReply = { local: prefilter(url, lex, st.trusted), lang: st.settings.lang };
        reply(out);
      })();
      return true;
    case "check":
      void checkOnce(url).then(reply);
      return true;
    case "allow":
      // Only the warning page may record "continue anyway"; a content script must not be able to.
      if (!fromWarning || !isWebUrl(url)) return false;
      void allowHost(hostOf(url)).then(() => reply({ ok: true }));
      return true;
    case "back_steps": {
      // How far "Go back" must travel from the warning page in this tab: 2 when the risky
      // document committed before it was replaced, else 1.
      const tabId = sender.tab?.id;
      if (!fromWarning || tabId === undefined) return false;
      const key = landedKey(tabId);
      void chrome.storage.session.get(key).then((r) => reply({ steps: r[key] === url ? 2 : 1 }));
      return true;
    }
    case "ping":
      if (!fromPage) return false;
      void ping().then(reply);
      return true;
    default:
      return false;
  }
});
