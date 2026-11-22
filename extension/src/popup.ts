/**
 * Popup: what we know about the current tab. The on-device result paints first; the server verdict
 * follows. Opening the popup is the person asking for a check, so the tab's URL is sent then
 * (activeTab), and only then.
 */
import { signalText, t, verdictWord, type Lang, type StringKey, type VerdictWord } from "./i18n";
import { defang, type PrefilterResult } from "./prefilter";
import {
  isWebUrl, loadSettings, saveSettings, send, type CheckError, type CheckReply, type PrefilterReply, type Settings,
} from "./shared";
import { applyLang, createLens, demoBadge, el, header, icon, listBlock, techText } from "./ui";

const app = document.getElementById("app")!;
const lens = createLens();
const WARNING_PAGE = chrome.runtime.getURL("warning.html");

let settings: Settings;
let lang: Lang = "ar";
let url = "";
let local: PrefilterResult | undefined;
let reply: CheckReply | undefined;

const ERROR_KEY: Record<CheckError, StringKey> = {
  offline: "st_offline", disabled: "st_disabled", rate_limited: "st_rate", no_permission: "st_perm",
  bad_response: "st_offline", unsupported: "pop_unsupported",
};

/** The tab's URL; when the tab shows our warning page, the address it is warning about. */
async function currentUrl(): Promise<string> {
  const override = new URLSearchParams(location.search).get("u"); // popup opened as a page (tests, screenshots)
  let u = override ?? "";
  if (!override) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    u = tab?.url ?? "";
  }
  if (u.startsWith(WARNING_PAGE)) u = new URL(u).searchParams.get("u") ?? "";
  return isWebUrl(u) ? u : "";
}

function render(): void {
  applyLang(lang);
  const head = header(lang, (next) => {
    lang = next;
    void saveSettings({ lang });
    render();
  });

  const settingsBtn = el("button", { class: "btn-ghost", type: "button", id: "open-settings" }, icon("gear", 18), el("span", { text: t("pop_settings", lang) }));
  settingsBtn.addEventListener("click", () => void chrome.runtime.openOptionsPage());
  const foot = el(
    "footer",
    { class: "pop-foot" },
    el("a", { class: "btn-secondary", id: "open-app", href: settings.webBase, target: "_blank", rel: "noopener noreferrer" }, icon("open", 18), el("span", { text: t("pop_open_app", lang) })),
    settingsBtn,
  );

  if (!url || !local || local.level === "skip") {
    lens.set("idle");
    app.replaceChildren(head, el("main", { class: "pop" }, el("p", { class: "pop-empty", id: "unsupported", text: t("pop_unsupported", lang) })), foot);
    return;
  }

  const v = reply?.ok ? reply.verdict : null;
  const serverWord: VerdictWord | null = v && (v.final || v.verdict !== "no_warning_signs") ? v.verdict : null;
  // Before (or without) a server verdict: an on-device warning shows as suspicious; anything else
  // stays neutral. "No warning signs" is only ever the server's final word.
  const verdict: VerdictWord | null = serverWord ?? (local.level === "warn" ? "suspicious" : null);
  const pending = reply === undefined;
  lens.set(pending ? "scanning" : verdict ? "locked" : "idle", pending ? undefined : (verdict ?? undefined));

  const localReasons = local.signals.map((s) => signalText(s, local!.brand, lang));
  const serverReasons = v && serverWord ? v.reasons.map((r) => r[lang] || r.ar || r.en).filter(Boolean) : [];

  let headline: string;
  if (verdict) headline = verdictWord(verdict, lang);
  else if (local.level === "note") headline = t("pop_noted", lang);
  else headline = pending ? t("tip_checking", lang) : t("pop_local_only", lang);

  let status: StringKey | null = pending ? "st_checking" : null;
  if (reply && !reply.ok) status = ERROR_KEY[reply.error];
  else if (reply?.ok && !reply.verdict.final) status = "st_partial";

  const official =
    local.level === "official" && local.brand
      ? el(
          "p",
          { class: "official", id: "official" },
          el("span", { text: `${t("pop_official", lang)} «${lang === "ar" ? local.brand.name_ar : local.brand.name_en}». ${t("pop_official_note", lang)}` }),
        )
      : null;

  app.replaceChildren(
    head,
    el(
      "main",
      { class: "pop", "data-verdict": verdict ?? "none" },
      el(
        "section",
        { class: "pop-verdict", "data-verdict": verdict ?? "none", id: "plate", role: "status", "aria-live": "polite" },
        el("div", { class: "lens-stage" }, lens.node),
        el(
          "div",
          { class: "pop-verdict-text" },
          el("span", { class: "eyebrow", text: t("pop_this_page", lang) }),
          el("h1", { class: "pop-word", id: "verdict-word" }, verdict ? icon(verdict, 26) : null, el("span", { text: headline })),
          techText(defang(new URL(url).host), "tech host"),
        ),
      ),
      status
        ? el("p", { class: "status", id: "status", "data-state": pending ? "pending" : "error", role: "status" }, el("span", { class: "status-dot", "aria-hidden": "true" }), el("span", { text: t(status, lang) }))
        : null,
      v && v.source !== "live" ? demoBadge(lang) : null,
      official,
      listBlock("reasons", lang, serverReasons.length ? serverReasons : localReasons, "reasons"),
      !serverReasons.length && !localReasons.length && !pending && local.level === "none" && !serverWord
        ? el("p", { class: "muted", id: "local-none", text: t("pop_local_none", lang) })
        : null,
      serverWord === "no_warning_signs" && v ? listBlock("caution", lang, v.caution[lang].slice(0, 3), "caution", "caution") : null,
      serverWord && serverWord !== "no_warning_signs" && v ? listBlock("do_now", lang, v.now[lang].slice(0, 2), "do-now") : null,
      v && serverWord
        ? el("p", { class: "muted small", id: "risk" }, el("span", { text: `${t("risk_by_arbiter", lang)}: ` }), techText(`${v.risk_score}/100`))
        : null,
      el("p", { class: "legal", text: t("not_legal", lang) }),
    ),
    foot,
  );
}

async function main(): Promise<void> {
  settings = await loadSettings();
  lang = settings.lang;
  url = await currentUrl();
  if (url) local = (await send<PrefilterReply>({ type: "prefilter", url })).local;
  render();
  if (!url || !local || local.level === "skip") return;
  reply = await send<CheckReply>({ type: "check", url }).catch((): CheckReply => ({ ok: false, error: "offline" }));
  render();
}

void main();
