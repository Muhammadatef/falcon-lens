/**
 * Full-page warning shown instead of a risky page. Order of events:
 *   1. paint the on-device result at once ("Suspicious", reasons, Go back);
 *   2. ask the service worker for the server verdict and upgrade or downgrade in place.
 * A provisional "no warning signs" is never shown: only a final verdict may say it.
 */
import lexiconJson from "./generated/lexicon.json";
import { signalText, t, verdictWord, type Lang, type StringKey, type VerdictWord } from "./i18n";
import { defang, prefilter, type Lexicon, type PrefilterResult } from "./prefilter";
import { isWebUrl, loadSettings, saveSettings, send, type CheckError, type CheckReply, type SlimVerdict } from "./shared";
import { applyLang, createLens, demoBadge, el, header, icon, listBlock, plate, techText } from "./ui";

const params = new URLSearchParams(location.search);
const rawTarget = params.get("u") ?? "";
const target = isWebUrl(rawTarget) ? rawTarget : "";
const app = document.getElementById("app")!;
const lens = createLens();

let lang: Lang = "ar";
let local: PrefilterResult = { level: "skip", host: "", signals: [] };
let reply: CheckReply | undefined;

const ERROR_KEY: Record<CheckError, StringKey> = {
  offline: "st_offline", disabled: "st_disabled", rate_limited: "st_rate", no_permission: "st_perm",
  bad_response: "st_offline", unsupported: "st_offline",
};

async function goBack(): Promise<void> {
  // When the risky document committed before it was replaced, it is one step behind this page.
  const { steps } = await send<{ steps: number }>({ type: "back_steps", url: target }).catch(() => ({ steps: 1 }));
  if (history.length > steps) {
    history.go(-steps);
    return;
  }
  chrome.tabs.getCurrent((tab) => {
    if (tab?.id !== undefined) void chrome.tabs.remove(tab.id);
    else window.close();
  });
}

async function continueAnyway(): Promise<void> {
  if (!target) return;
  await send({ type: "allow", url: target });
  location.replace(target);
}

/** Server verdict to show, or null while the on-device result must stay in front. */
function shown(): SlimVerdict | null {
  if (!reply?.ok) return null;
  if (reply.verdict.verdict === "no_warning_signs" && !reply.verdict.final) return null;
  return reply.verdict;
}

function render(): void {
  applyLang(lang);
  document.title = `${t("warn_title", lang)} · ${t("brand", lang)}`;
  const v = shown();
  const verdict: VerdictWord = v?.verdict ?? "suspicious";
  const pending = reply === undefined;
  lens.set(pending ? "scanning" : "locked", pending ? undefined : verdict);

  const lead = v?.verdict === "dangerous" ? "warn_danger_lead" : v?.verdict === "no_warning_signs" ? "warn_nws_lead" : "warn_lead";
  const title = verdict === "no_warning_signs" ? verdictWord(verdict, lang) : t("warn_title", lang);

  let status: StringKey = "st_checking";
  if (reply && !reply.ok) status = ERROR_KEY[reply.error];
  else if (reply?.ok) status = reply.verdict.final ? "st_confirmed" : "st_partial";

  const localReasons = local.signals.map((s) => signalText(s, local.brand, lang));
  const serverReasons = v ? v.reasons.map((r) => r[lang] || r.ar || r.en).filter(Boolean) : [];
  const brandDomains = v?.brand?.domains.length ? v.brand.domains : (local.brand?.domains ?? []);

  const back = el("button", { class: "btn-primary", type: "button", id: "go-back" }, icon("undo", 22), el("span", { text: t("go_back", lang) }));
  back.addEventListener("click", () => void goBack());
  const cont = el("button", {
    class: verdict === "no_warning_signs" ? "btn-secondary" : "btn-quiet", type: "button", id: "continue", text: t("continue_anyway", lang),
  });
  cont.addEventListener("click", () => void continueAnyway());

  const chip = verdict === "no_warning_signs" ? null : el("span", { class: "chip", "data-verdict": verdict, id: "verdict-chip" }, icon(verdict, 18), el("span", { text: verdictWord(verdict, lang) }));

  app.replaceChildren(
    header(lang, (next) => {
      lang = next;
      void saveSettings({ lang });
      render();
    }),
    el(
      "main",
      { class: "warn", "data-verdict": verdict },
      el("div", { class: "lens-stage" }, lens.node),
      plate(verdict, title, t(lead, lang), chip ?? undefined),
      // The way out sits directly under the verdict, above the fold on a phone.
      el("div", { class: "actions" }, back, cont, el("p", { class: "muted small", text: t("continue_note", lang) })),
      el(
        "p",
        { class: "status", id: "status", "data-state": pending ? "pending" : reply?.ok ? "done" : "error", role: "status" },
        el("span", { class: "status-dot", "aria-hidden": "true" }),
        el("span", { text: t(status, lang) }),
        v?.degraded ? el("span", { class: "muted", text: " " + t("degraded", lang) }) : null,
        v && v.source !== "live" ? demoBadge(lang) : null,
      ),
      el(
        "section",
        { class: "block address" },
        el("h2", { class: "block-title", text: t("address", lang) }),
        techText(target ? defang(target) : "—", "tech url"),
        brandDomains.length
          ? el("p", { class: "official", id: "official" }, el("span", { text: t("official_is", lang) + " " }), techText(brandDomains.slice(0, 3).join(" · ")))
          : null,
      ),
      listBlock(v ? "reasons" : "why", lang, serverReasons.length ? serverReasons : localReasons, "reasons"),
      serverReasons.length && localReasons.length ? listBlock("why_local", lang, localReasons, "local-reasons", "quiet") : null,
      v?.verdict === "no_warning_signs" ? listBlock("caution", lang, v.caution[lang], "caution", "caution") : null,
      v && v.verdict !== "no_warning_signs" ? listBlock("do_now", lang, v.now[lang].slice(0, 3), "do-now") : null,
      el("p", { class: "legal", text: t("not_legal", lang) }),
    ),
  );
  back.focus({ preventScroll: true });
}

async function main(): Promise<void> {
  const settings = await loadSettings();
  lang = settings.lang;
  if (target) local = prefilter(target, lexiconJson as Lexicon);
  render();
  if (!target) {
    reply = { ok: false, error: "unsupported" };
    render();
    return;
  }
  reply = await send<CheckReply>({ type: "check", url: target }).catch((): CheckReply => ({ ok: false, error: "offline" }));
  render();
  if (reply.ok && reply.verdict.verdict === "dangerous" && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    navigator.vibrate?.([60, 60, 120]);
  }
}

void main();
