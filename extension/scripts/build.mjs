// Builds the extension into dist/ (or dist-e2e/ with --e2e). Everything is bundled: no remote code,
// no remote fonts. `--zip` also writes build/falcon-lens-extension-<version>.zip.
//
// Environment:
//   FL_API_BASE   default API origin, also the only host permission (default https://localhost:8443)
//   FL_WEB_BASE   web app origin for the popup link (default: FL_API_BASE)
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const args = new Set(process.argv.slice(2));
const e2e = args.has("--e2e");
const out = e2e && process.env.FL_E2E_OUT ? process.env.FL_E2E_OUT : join(root, e2e ? "dist-e2e" : "dist");
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

// The e2e build differs in exactly two ways: the API origin is the local mock, and the hover
// script also matches a reserved .test host that stands in for a webmail app.
const E2E_API = `http://127.0.0.1:${process.env.FL_E2E_API_PORT ?? "8765"}`; // tests pick a free port per run
const E2E_HOVER_MATCH = "http://webmail.test/*";

function origin(value, name) {
  let u;
  try {
    u = new URL(value);
  } catch {
    throw new Error(`build: ${name} is not a URL: ${value}`);
  }
  const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
  if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) throw new Error(`build: ${name} must be https (http only for localhost)`);
  return u.origin;
}
const apiBase = origin(e2e ? E2E_API : (process.env.FL_API_BASE ?? "https://localhost:8443"), "FL_API_BASE");
const webBase = origin(e2e ? E2E_API : (process.env.FL_WEB_BASE ?? apiBase), "FL_WEB_BASE");
// A match pattern has no port: the permission covers the host on any port.
const hostPattern = (o) => `${new URL(o).protocol}//${new URL(o).hostname}/*`;

execFileSync(process.execPath, [join(here, "gen-data.mjs")], { stdio: "inherit" });
rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "fonts"), { recursive: true });

const common = {
  bundle: true,
  minify: !e2e,
  sourcemap: false,
  target: "chrome116",
  legalComments: "none",
  define: { __FL_API_BASE__: JSON.stringify(apiBase), __FL_WEB_BASE__: JSON.stringify(webBase) },
  logLevel: "warning",
};
await build({
  ...common,
  format: "esm",
  entryPoints: ["background", "warning", "popup", "options"].map((n) => join(root, "src", `${n}.ts`)),
  outdir: out,
});
// Content scripts are classic scripts: one self-contained IIFE.
await build({ ...common, format: "iife", entryPoints: [join(root, "src", "content.ts")], outdir: out });

for (const f of ["warning.html", "popup.html", "options.html", "ui.css", "tokens.css"]) cpSync(join(root, "static", f), join(out, f));
cpSync(join(root, "static", "icons"), join(out, "icons"), { recursive: true });
const fonts = [
  ["@fontsource-variable/readex-pro", "readex-pro-arabic-wght-normal.woff2"],
  ["@fontsource-variable/readex-pro", "readex-pro-latin-wght-normal.woff2"],
  ["@fontsource-variable/jetbrains-mono", "jetbrains-mono-latin-wght-normal.woff2"],
];
for (const [p, f] of fonts) cpSync(join(root, "node_modules", p, "files", f), join(out, "fonts", f));
for (const p of new Set(fonts.map((x) => x[0]))) cpSync(join(root, "node_modules", p, "LICENSE"), join(out, "fonts", `${p.split("/")[1]}-LICENSE.txt`));

const design = join(root, "..", "web", "design", "tokens.css");
if (existsSync(design) && readFileSync(design, "utf8") !== readFileSync(join(root, "static", "tokens.css"), "utf8")) {
  console.warn("build: WARNING static/tokens.css differs from web/design/tokens.css (the source of truth); copy it over.");
}

const hoverHosts = [
  "https://mail.google.com/*",
  "https://outlook.live.com/*",
  "https://outlook.office.com/*",
  "https://web.whatsapp.com/*",
  "https://web.telegram.org/*",
];
const manifest = {
  manifest_version: 3,
  name: "Falcon Lens | عدسة الصقر",
  short_name: "Falcon Lens",
  version: pkg.version,
  description: "يحذّرك قبل أن تكتب في صفحة مريبة، ويفحص الروابط في بريدك. Warns before you type on a suspicious page and checks links in webmail.",
  minimum_chrome_version: "116",
  icons: { 16: "icons/icon-16.png", 32: "icons/icon-32.png", 48: "icons/icon-48.png", 128: "icons/icon-128.png" },
  action: {
    default_popup: "popup.html",
    default_title: "عدسة الصقر | Falcon Lens",
    default_icon: { 16: "icons/icon-16.png", 32: "icons/icon-32.png" },
  },
  options_ui: { page: "options.html", open_in_tab: true },
  background: { service_worker: "background.js", type: "module" },
  // Each permission is explained in PRIVACY.md. No "tabs", no "scripting", no "<all_urls>".
  permissions: ["webNavigation", "storage", "activeTab"],
  host_permissions: [hostPattern(apiBase)],
  // Used only when the person saves a different API address in the options page.
  optional_host_permissions: ["https://*/*", "http://localhost/*", "http://127.0.0.1/*"],
  content_scripts: [
    { matches: e2e ? [...hoverHosts, E2E_HOVER_MATCH] : hoverHosts, js: ["content.js"], run_at: "document_idle", all_frames: false },
  ],
  content_security_policy: {
    extension_pages:
      "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; " +
      "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; object-src 'none'; base-uri 'none'; " +
      "form-action 'none'; frame-ancestors 'none'",
  },
};
writeFileSync(join(out, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`build: ${e2e ? "dist-e2e" : "dist"} ready (API ${apiBase})`);

if (args.has("--zip")) {
  mkdirSync(join(root, "build"), { recursive: true });
  const zip = join(root, "build", `falcon-lens-extension-${pkg.version}.zip`);
  rmSync(zip, { force: true });
  execFileSync("zip", ["-q", "-r", "-X", zip, "."], { cwd: out, stdio: "inherit" });
  console.log(`build: ${zip}`);
}
