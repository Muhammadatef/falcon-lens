// Generates src/generated/lexicon.json for the on-device prefilter:
//   brands  <- ../data/brands.yaml (brand id, names, verified domains, Latin tokens)
//   lists   <- scripts/lexicon.json (free-host suffixes, combo words, weak tokens, region hints)
// Runs before build, typecheck and tests. Nothing here is fetched at runtime: the result is bundled.
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const lex = JSON.parse(readFileSync(join(here, "lexicon.json"), "utf8"));

// Service words that are never a brand token on their own (mirrors GENERIC_EN in registry.py).
const GENERIC = new Set(
  (
    "fine fines traffic violation violations case report parcel package delivery customs fee redelivery tracking " +
    "online banking card blocked account verify verification bill recharge balance points rewards suspended otp " +
    "payment pay refund services service renew renewal visa residency identity digital id login unpaid tag toll " +
    "mobile sim government clearance parking vehicle file disconnection compliance sanctions frozen kyc update " +
    "electricity water gas"
  ).split(" "),
);

const compact = (s) => String(s).toLowerCase().replace(/[\s\-_.]+/g, "");
const clean = (t) => /^[a-z0-9]{3,24}$/.test(t);

function tokensFor(entry) {
  const out = [];
  const add = (t) => {
    if (clean(t) && !out.includes(t)) out.push(t);
  };
  // Every verified domain is a registrable domain, so its first label is the brand label.
  for (const d of entry.verified_domains ?? []) add(compact(String(d).split(".")[0]));
  const name = String(entry.name_en ?? "");
  const base = name.replace(/\(.*?\)/g, " ").split(" - ")[0];
  if (compact(base).length >= 4) add(compact(base));
  for (const m of name.matchAll(/\(([^)]*)\)/g)) for (const part of m[1].split(/[/,]/)) add(compact(part));
  for (const kw of entry.keywords_en ?? []) {
    const words = String(kw).toLowerCase().split(/\s+/);
    if (words.length >= 2 && !words.some((w) => GENERIC.has(w)) && compact(kw).length >= 8) add(compact(kw));
  }
  return out;
}

const doc = parse(readFileSync(join(root, "data", "brands.yaml"), "utf8"));
const brands = (doc.brands ?? []).map((b) => ({
  id: String(b.brand_id),
  name_ar: String(b.name_ar ?? ""),
  name_en: String(b.name_en ?? ""),
  demo: b.category === "demo",
  domains: (b.verified_domains ?? []).map((d) => String(d).toLowerCase()),
  tokens: tokensFor(b),
}));
if (brands.length === 0) throw new Error("gen-data: data/brands.yaml has no brands");
if (!brands.some((b) => b.id === "falcon_demo_bank")) throw new Error("gen-data: falcon_demo_bank is missing");

// Drift check against the Python signals (warning only: the extension keeps its reviewed snapshot).
function pyStrings(file, name) {
  const p = join(root, "packages/falcon_core/src/falcon_core/signals/url", file);
  if (!existsSync(p)) return null;
  const m = readFileSync(p, "utf8").match(new RegExp(`^${name}\\s*=\\s*(?:frozenset\\()?[({]([\\s\\S]*?)^[)}]`, "m"));
  return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : null;
}
const drift = (label, mine, theirs) => {
  if (!theirs) return;
  const a = new Set(mine);
  const missing = theirs.filter((x) => !a.has(x));
  if (missing.length) console.warn(`gen-data: WARNING ${label} is behind falcon_core, missing: ${missing.join(", ")}`);
};
drift("free_host_suffixes", lex.free_host_suffixes, pyStrings("canonical.py", "FREE_HOST_SUFFIXES"));
const combo = [...(pyStrings("squatting.py", "COMBO_EN") ?? []), ...(pyStrings("squatting.py", "COMBO_TRANSLIT") ?? [])];
drift("combo_words", lex.combo_words, combo.length ? combo : null);

const out = {
  generated_from: "data/brands.yaml + extension/scripts/lexicon.json",
  brands,
  free_host_suffixes: lex.free_host_suffixes,
  combo_words: lex.combo_words,
  weak_tokens: lex.weak_tokens,
  region_hints: lex.region_hints,
};
mkdirSync(join(here, "..", "src", "generated"), { recursive: true });
writeFileSync(join(here, "..", "src", "generated", "lexicon.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`gen-data: ${brands.length} brands, ${brands.reduce((n, b) => n + b.domains.length, 0)} official domains`);
