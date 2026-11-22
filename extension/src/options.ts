/**
 * Options: API base URL, optional API key, web app URL, server checks on/off, language.
 * Saving a new API origin asks Chrome for permission to that one origin (optional host
 * permission); the address is not saved when the person declines.
 */
import { t, type Lang, type StringKey } from "./i18n";
import { loadSettings, normaliseBase, permissionPattern, saveSettings, send, type Settings } from "./shared";
import { applyLang, el, header } from "./ui";

const app = document.getElementById("app")!;
let settings: Settings;
let lang: Lang = "ar";
let notice: { key: StringKey; kind: "ok" | "error" } | null = null;

function field(id: string, labelKey: StringKey, helpKey: StringKey | null, input: HTMLElement): HTMLElement {
  input.id = id;
  if (helpKey) input.setAttribute("aria-describedby", `${id}-help`);
  return el(
    "div",
    { class: "field" },
    el("label", { for: id, text: t(labelKey, lang) }),
    input,
    helpKey ? el("p", { class: "muted small", id: `${id}-help`, text: t(helpKey, lang) }) : null,
  );
}

function render(): void {
  applyLang(lang);
  document.title = t("opt_title", lang);
  const api = el("input", { type: "url", class: "input tech", dir: "ltr", value: settings.apiBase, autocomplete: "off", spellcheck: "false", required: true });
  const key = el("input", { type: "password", class: "input tech", dir: "ltr", value: settings.apiKey, autocomplete: "off", spellcheck: "false" });
  const web = el("input", { type: "url", class: "input tech", dir: "ltr", value: settings.webBase, autocomplete: "off", spellcheck: "false", required: true });
  const server = el("input", { type: "checkbox", id: "opt-server", checked: settings.serverChecks, "aria-describedby": "opt-server-help" });

  const say = (k: StringKey, kind: "ok" | "error"): void => {
    notice = { key: k, kind };
    render();
  };

  const form = el(
    "form",
    { class: "form", id: "options-form", novalidate: true },
    field("opt-api", "opt_api", "opt_api_help", api),
    field("opt-key", "opt_key", "opt_key_help", key),
    field("opt-web", "opt_web", null, web),
    el(
      "div",
      { class: "field check" },
      el("label", { class: "check-label", for: "opt-server" }, server, el("span", { text: t("opt_server", lang) })),
      el("p", { class: "muted small", id: "opt-server-help", text: t("opt_server_help", lang) }),
    ),
    el(
      "div",
      { class: "actions row-actions" },
      el("button", { class: "btn-primary", type: "submit", id: "save", text: t("opt_save", lang) }),
      el("button", { class: "btn-secondary", type: "button", id: "test", text: t("opt_test", lang) }),
    ),
    notice ? el("p", { class: "notice", id: "notice", "data-kind": notice.kind, role: "status", text: t(notice.key, lang) }) : null,
  );

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    void (async () => {
      const apiOrigin = normaliseBase(api.value);
      const webOrigin = normaliseBase(web.value);
      if (!apiOrigin || !webOrigin) return say("opt_bad_url", "error");
      // Must run inside the click: chrome.permissions.request needs a user gesture.
      const origins = [permissionPattern(apiOrigin)];
      const granted = (await chrome.permissions.contains({ origins })) || (await chrome.permissions.request({ origins }).catch(() => false));
      if (!granted) return say("opt_denied", "error");
      settings = await saveSettings({ apiBase: apiOrigin, apiKey: key.value.trim().slice(0, 256), webBase: webOrigin, serverChecks: server.checked });
      say("opt_saved", "ok");
    })();
  });
  form.querySelector("#test")!.addEventListener("click", () => {
    void send<{ ok: boolean }>({ type: "ping" })
      .catch(() => ({ ok: false }))
      .then((r) => say(r.ok ? "opt_test_ok" : "opt_test_fail", r.ok ? "ok" : "error"));
  });

  app.replaceChildren(
    header(lang, (next) => {
      lang = next;
      notice = null;
      void saveSettings({ lang }).then((s) => {
        settings = s;
        render();
      });
    }),
    el("main", { class: "opts" }, el("h1", { class: "page-title", text: t("opt_title", lang) }), form, el("p", { class: "legal", id: "privacy-note", text: t("opt_privacy", lang) })),
  );
}

void loadSettings().then((s) => {
  settings = s;
  lang = s.lang;
  render();
});
