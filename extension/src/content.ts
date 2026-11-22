/**
 * Hover check for webmail and chat web apps (hosts listed in the manifest).
 * Resting on a link for 400 ms shows a small badge: the on-device result at once, then the server
 * verdict. The badge lives in a closed shadow root, takes no pointer events and is built from
 * text nodes only. This script reads nothing from the page except the hovered link's address.
 */
import { dirOf, signalText, t, verdictWord, type Lang, type VerdictWord } from "./i18n";
import { defang, type PrefilterResult } from "./prefilter";
import { HOVER_DELAY_MS, type CheckReply, type Message, type PrefilterReply } from "./shared";

const NS = "http://www.w3.org/2000/svg";
const SHAPES: Record<VerdictWord | "none", string[]> = {
  dangerous: ["M8.3 2.6h7.4l5.7 5.7v7.4l-5.7 5.7H8.3l-5.7-5.7V8.3z", "M12 7.4v5.8", "M12 16.6v.1"],
  suspicious: ["M12 3.1 21.8 20.4H2.2z", "M10.1 11.3a2 2 0 1 1 3 1.7c-.7.4-1.1.9-1.1 1.6", "M12 17.4v.1"],
  no_warning_signs: ["M10.5 3.5a7 7 0 1 1 0 14 7 7 0 0 1 0-14z", "M15.6 15.6 21 21", "M7.6 10.5h5.8"],
  none: ["M12 5a7 7 0 1 1 0 14 7 7 0 0 1 0-14z", "M12 10.500a1.500 1.500 0 1 1 0 3 1.500 1.500 0 0 1 0-3z"],
};

// Night theme values from static/tokens.css. A content script cannot rely on the page loading our
// stylesheet, and the system font stack avoids exposing font files to web pages.
const CSS = `
:host { all: initial; }
.tip { position: fixed; z-index: 2147483647; top: 0; left: 0; max-width: min(22rem, calc(100vw - 16px));
  box-sizing: border-box; display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; align-items: center;
  padding: 10px 14px; border-radius: 14px; border: 1px solid #2a3757; border-inline-start: 4px solid var(--c);
  background: #0e1626; color: #f2eee6; box-shadow: 0 2px 4px rgb(0 0 0 / 0.5), 0 12px 32px rgb(0 0 0 / 0.45);
  font: 500 15px/1.6 "Readex Pro", "Noto Sans Arabic", "Segoe UI", Tahoma, system-ui, sans-serif;
  pointer-events: none; opacity: 0; transform: translateY(4px);
  transition: opacity 160ms cubic-bezier(0.16, 1, 0.3, 1), transform 160ms cubic-bezier(0.16, 1, 0.3, 1); --c: #8794ae; }
.tip[data-show] { opacity: 1; transform: none; }
.tip[data-v="dangerous"] { --c: #ff8589; }
.tip[data-v="suspicious"] { --c: #ffc55c; }
.tip[data-v="no_warning_signs"] { --c: #a9c0ff; }
svg { grid-row: span 2; width: 26px; height: 26px; color: var(--c); fill: none; stroke: currentColor; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; }
.tip[data-busy] svg { animation: pulse 1.1s cubic-bezier(0.65, 0, 0.35, 1) infinite alternate; }
.word { font-weight: 650; color: var(--c); }
.why { color: #f2eee6; font-weight: 400; }
.host { grid-column: 2; font: 400 13px/1.5 "JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  color: #aeb8cc; direction: ltr; unicode-bidi: isolate; text-align: start; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.by { grid-column: 2; font-size: 12px; color: #8794ae; }
@keyframes pulse { from { opacity: 1; } to { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .tip { transition: opacity 120ms linear; transform: none; } .tip[data-busy] svg { animation: none; } }
`;

/** Mail services wrap links in their own redirectors; check the address the link really leads to. */
export const WRAPPERS: readonly { suffix: string; path: string; param: string }[] = [
  { suffix: "safelinks.protection.outlook.com", path: "/", param: "url" },
  { suffix: "www.google.com", path: "/url", param: "q" },
];

export function unwrap(href: string, wrappers = WRAPPERS): string {
  try {
    const u = new URL(href);
    const w = wrappers.find((x) => (u.hostname === x.suffix || u.hostname.endsWith("." + x.suffix)) && u.pathname === x.path);
    const inner = w ? u.searchParams.get(w.param) : null;
    if (inner && /^https?:\/\//i.test(inner)) return new URL(inner).href;
    return u.href;
  } catch {
    return "";
  }
}

let host: HTMLElement | undefined;
let tip: HTMLElement | undefined;
let timer = 0;
let current: HTMLAnchorElement | null = null;
let seq = 0;

function ensureTip(): HTMLElement {
  if (tip && host?.isConnected) return tip;
  host = document.createElement("falcon-lens-badge");
  const root = host.attachShadow({ mode: "closed" });
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(CSS);
    root.adoptedStyleSheets = [sheet];
  } catch {
    const style = document.createElement("style");
    style.textContent = CSS;
    root.append(style);
  }
  tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  root.append(tip);
  document.documentElement.append(host);
  return tip;
}

function draw(a: HTMLAnchorElement, url: string, lang: Lang, v: VerdictWord | "none", word: string, why: string, by: string, busy: boolean): void {
  const box = ensureTip();
  box.dir = dirOf(lang);
  box.lang = lang;
  box.dataset["v"] = v;
  box.toggleAttribute("data-busy", busy);
  const icon = document.createElementNS(NS, "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("aria-hidden", "true");
  for (const d of SHAPES[v]) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    icon.append(p);
  }
  const line = document.createElement("div");
  const w = document.createElement("span");
  w.className = "word";
  w.textContent = word;
  line.append(w);
  if (why) {
    const y = document.createElement("span");
    y.className = "why";
    y.textContent = " · " + why;
    line.append(y);
  }
  const h = document.createElement("div");
  h.className = "host";
  h.textContent = defang(new URL(url).host);
  box.replaceChildren(icon, line, h);
  if (by) {
    const b = document.createElement("div");
    b.className = "by";
    b.textContent = by;
    box.append(b);
  }
  // Place under the link, flipped above when there is no room; clamp to the viewport.
  const r = a.getBoundingClientRect();
  const size = box.getBoundingClientRect();
  const x = Math.max(8, Math.min(lang === "ar" ? r.right - size.width : r.left, innerWidth - size.width - 8));
  const below = r.bottom + 8;
  const y = below + size.height > innerHeight - 8 ? Math.max(8, r.top - size.height - 8) : below;
  box.style.setProperty("left", `${Math.round(x)}px`);
  box.style.setProperty("top", `${Math.round(y)}px`);
  box.toggleAttribute("data-show", true);
  // State mirrored on the host element for assistive tooling and tests. Nothing reads it back.
  if (host) {
    host.dataset["state"] = busy ? "checking" : "done";
    host.dataset["verdict"] = v;
  }
}

function hide(): void {
  clearTimeout(timer);
  seq++;
  current = null;
  tip?.removeAttribute("data-show");
  if (host) host.dataset["state"] = "hidden";
}

const ask = <T>(msg: Message): Promise<T> => chrome.runtime.sendMessage(msg) as Promise<T>;

async function show(a: HTMLAnchorElement): Promise<void> {
  const url = unwrap(a.href);
  if (!/^https?:\/\//i.test(url)) return;
  const mine = ++seq;
  let pre: PrefilterReply;
  try {
    pre = await ask<PrefilterReply>({ type: "prefilter", url });
  } catch {
    return; // extension reloaded or disabled: stay silent
  }
  if (mine !== seq || !pre?.local || pre.local.level === "skip") return;
  const { lang } = pre;
  const local: PrefilterResult = pre.local;
  const first = local.signals[0] ? signalText(local.signals[0], local.brand, lang) : "";
  const localV: VerdictWord | "none" = local.level === "warn" ? "suspicious" : "none";
  const localWord = local.level === "warn" ? verdictWord("suspicious", lang) : local.level === "note" ? t("tip_note", lang) : t("tip_checking", lang);
  draw(a, url, lang, localV, localWord, first, t("brand", lang), true);

  const reply = await ask<CheckReply>({ type: "check", url }).catch((): CheckReply => ({ ok: false, error: "offline" }));
  if (mine !== seq) return;
  if (reply.ok && (reply.verdict.final || reply.verdict.verdict !== "no_warning_signs")) {
    const v = reply.verdict;
    const r = v.reasons[0];
    const why = v.verdict === "no_warning_signs" ? t("tip_caution", lang) : (r ? r[lang] || r.ar || r.en : first);
    draw(a, url, lang, v.verdict, verdictWord(v.verdict, lang), why, t("brand", lang) + (v.source !== "live" ? ` · ${t("demo_data", lang)}` : ""), false);
    return;
  }
  // No usable server verdict: keep the on-device result and say that is all it is.
  const word = local.level === "warn" ? verdictWord("suspicious", lang) : local.level === "note" ? t("tip_note", lang) : t("tip_local_only", lang);
  draw(a, url, lang, localV, word, first, `${t("brand", lang)} · ${t("tip_local_only", lang)}`, false);
}

function arm(target: EventTarget | null): void {
  const a = target instanceof Element ? target.closest<HTMLAnchorElement>("a[href]") : null;
  if (a === current) return;
  hide();
  if (!a) return;
  current = a;
  timer = window.setTimeout(() => void show(a), HOVER_DELAY_MS);
}

if (typeof chrome !== "undefined" && chrome.runtime?.id) {
  document.addEventListener("mouseover", (e) => arm(e.target), { capture: true, passive: true });
  document.addEventListener("focusin", (e) => arm(e.target), { capture: true, passive: true });
  document.addEventListener("mouseout", (e) => {
    const to = e.relatedTarget;
    if (current && !(to instanceof Node && current.contains(to))) hide();
  }, { capture: true, passive: true });
  document.addEventListener("focusout", hide, { capture: true, passive: true });
  document.addEventListener("scroll", hide, { capture: true, passive: true });
  document.addEventListener("keydown", (e) => e.key === "Escape" && hide(), { capture: true, passive: true });
  document.addEventListener("visibilitychange", hide);
}
