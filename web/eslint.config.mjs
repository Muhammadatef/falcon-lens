import js from "@eslint/js";
import tseslint from "typescript-eslint";

const readonly = (names) => Object.fromEntries(names.map((name) => [name, "readonly"]));
const NODE = readonly(["process", "console", "Buffer", "URL", "setTimeout", "clearTimeout", "fetch"]);
const WORKER = readonly(["self", "caches", "fetch", "URL", "Response", "Request"]);

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "test-results/**", "playwright-report/**", "design/prototype/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      // XSS guard (THREAT_MODEL row E): never inject raw HTML.
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "dangerouslySetInnerHTML is forbidden." },
      ],
    },
  },
  // Node scripts, the test gateway and config files.
  { files: ["**/*.mjs"], languageOptions: { globals: NODE } },
  // Phase A prototype capture script: its page.evaluate callbacks run in the browser.
  { files: ["design/scripts/capture-shots.mjs"], languageOptions: { globals: { ...NODE, ...readonly(["document", "window"]) } } },
  // Service worker.
  { files: ["public/sw.js"], languageOptions: { globals: WORKER } },
  // These three strip or detect control characters on purpose.
  { files: ["lib/defang.ts", "tests/mock/gateway.mjs"], rules: { "no-control-regex": "off" } },
);
