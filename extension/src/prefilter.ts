/**
 * On-device lexical prefilter. Pure and synchronous: no network, no storage, no DOM.
 *
 * It is a small port of the T1 URL signals in packages/falcon_core/signals/url (homograph,
 * typosquat, brand in host, IP host, userinfo, free host or tunnel). It decides one thing only:
 * is this address odd enough to interrupt the navigation before the person types anything?
 * It never produces a verdict. The server does that (contracts/verdict.schema.json).
 *
 * Deliberate differences from the Python signals:
 *  - No Public Suffix List is bundled, so "official" means the host equals a verified domain or
 *    ends with "." + a verified domain, and a brand token is searched in the whole host.
 *  - A small look-alike table replaces the full Unicode confusables file.
 *  - A free host or tunnel alone is only a note. Interrupting every github.io page would teach
 *    people to click through warnings.
 */

export interface BrandEntry {
  id: string;
  name_ar: string;
  name_en: string;
  demo: boolean;
  domains: string[];
  tokens: string[];
}

export interface Lexicon {
  brands: BrandEntry[];
  free_host_suffixes: string[];
  combo_words: string[];
  weak_tokens: string[];
  region_hints: string[];
}

export type SignalId =
  | "brand_in_host" // a brand name is in the host, and the host is not one of that brand's domains
  | "brand_lookalike" // one or two characters away from a brand name (typo or digit swap)
  | "homograph" // look-alike letters from another alphabet spell a brand name
  | "mixed_script" // one label mixes alphabets
  | "ip_host" // public IP address instead of a name
  | "userinfo" // text before "@" hides the real host
  | "free_host"; // free hosting or temporary tunnel

export interface LocalSignal {
  id: SignalId;
  /** true when this signal alone justifies the full-page warning */
  block: boolean;
  brandId?: string;
  /** free-host suffix, or the name written before "@" */
  detail?: string;
}

export interface BrandRef {
  id: string;
  name_ar: string;
  name_en: string;
  domains: string[];
}

/** warn = interrupt · note = mention only · official = on a verified domain · skip = not checkable */
export type LocalLevel = "warn" | "note" | "none" | "official" | "skip";

export interface PrefilterResult {
  level: LocalLevel;
  /** ASCII (punycode) host, lower case; empty for skip */
  host: string;
  signals: LocalSignal[];
  brand?: BrandRef;
}

const SKIP: PrefilterResult = { level: "skip", host: "", signals: [] };
const STRONG_MIN = 5; // shorter tokens (dewa, rta, adcb ...) are too common inside other words
const TYPO_MIN = 7;
const LEET: Record<string, string> = { "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g" };

// Look-alike letters to Latin. Covers the Cyrillic, Greek and Armenian letters used in practice to
// imitate Latin domain names. Not the full UTS #39 table; the server runs that one.
const CONFUSABLE: Record<string, string> = {
  а: "a", в: "b", с: "c", ԁ: "d", е: "e", ҽ: "e", ё: "e", ф: "f", ɡ: "g", һ: "h", н: "h", і: "i", ї: "i", ı: "i",
  ј: "j", к: "k", ӏ: "l", ɩ: "l", м: "m", п: "n", о: "o", р: "p", ԛ: "q", г: "r", ѕ: "s", т: "t", ц: "u", ѵ: "v",
  ν: "v", ԝ: "w", ш: "w", х: "x", у: "y", ү: "y", ʏ: "y", ᴢ: "z", α: "a", β: "b", ε: "e", η: "n", ι: "i", κ: "k",
  ο: "o", ρ: "p", τ: "t", υ: "u", χ: "x", ω: "w", ϲ: "c", ո: "n", օ: "o", ս: "u", հ: "h", ց: "g", ք: "p", ԍ: "g",
  ℓ: "l", ɑ: "a", ƅ: "b", ɗ: "d", ɛ: "e", ʀ: "r", ꜱ: "s", ß: "b", ł: "l", ø: "o", đ: "d", ħ: "h",
};

const SCRIPTS: [string, RegExp][] = [
  ["Latin", /\p{Script=Latin}/u],
  ["Cyrillic", /\p{Script=Cyrillic}/u],
  ["Greek", /\p{Script=Greek}/u],
  ["Arabic", /\p{Script=Arabic}/u],
  ["Hebrew", /\p{Script=Hebrew}/u],
  ["Armenian", /\p{Script=Armenian}/u],
  ["Han", /\p{Script=Han}/u],
  ["Kana", /[\p{Script=Hiragana}\p{Script=Katakana}]/u],
  ["Hangul", /\p{Script=Hangul}/u],
  ["Thai", /\p{Script=Thai}/u],
  ["Devanagari", /\p{Script=Devanagari}/u],
];

/** RFC 3492 decoder for one label body (the part after "xn--"). Returns null when malformed. */
export function punycodeDecode(input: string): string | null {
  const base = 36, tMin = 1, tMax = 26, skew = 38, damp = 700;
  const out: number[] = [];
  const cut = input.lastIndexOf("-");
  for (let j = 0; j < Math.max(cut, 0); j++) {
    const c = input.charCodeAt(j);
    if (c >= 0x80) return null;
    out.push(c);
  }
  let n = 128, i = 0, bias = 72;
  for (let idx = cut > 0 ? cut + 1 : 0; idx < input.length; ) {
    const oldi = i;
    for (let w = 1, k = base; ; k += base) {
      if (idx >= input.length) return null;
      const c = input.charCodeAt(idx++);
      const digit = c - 48 < 10 ? c - 22 : c - 65 < 26 ? c - 65 : c - 97 < 26 ? c - 97 : base;
      if (digit >= base || digit < 0) return null;
      i += digit * w;
      const t = k <= bias ? tMin : k >= bias + tMax ? tMax : k - bias;
      if (digit < t) break;
      w *= base - t;
      if (w > 0x7fffffff) return null;
    }
    const len = out.length + 1;
    let delta = oldi === 0 ? Math.floor((i - oldi) / damp) : (i - oldi) >> 1;
    delta += Math.floor(delta / len);
    let k = 0;
    for (; delta > ((base - tMin) * tMax) >> 1; k += base) delta = Math.floor(delta / (base - tMin));
    bias = k + Math.floor(((base - tMin + 1) * delta) / (delta + skew));
    n += Math.floor(i / len);
    i %= len;
    if (n > 0x10ffff) return null;
    out.splice(i++, 0, n);
  }
  return String.fromCodePoint(...out);
}

/** "xn--" labels back to Unicode; other labels unchanged. */
export function toUnicodeLabel(label: string): string {
  if (!label.startsWith("xn--")) return label;
  return punycodeDecode(label.slice(4)) ?? label;
}

function scriptsOf(label: string): Set<string> {
  const found = new Set<string>();
  for (const ch of label) for (const [name, re] of SCRIPTS) if (re.test(ch)) found.add(name);
  return found;
}

/** Japanese mixes Han and kana in ordinary words; everything else in one label is a red flag. */
function isMixed(scripts: Set<string>): boolean {
  if (scripts.size < 2) return false;
  return ![...scripts].every((s) => s === "Han" || s === "Kana");
}

/** Fold look-alike letters and accents to plain Latin. */
export function skeleton(s: string): string {
  let out = "";
  for (const ch of s.normalize("NFD").toLowerCase()) {
    if (/\p{M}/u.test(ch)) continue;
    out += CONFUSABLE[ch] ?? ch;
  }
  return out;
}

const compact = (s: string): string => s.replace(/[^\p{L}\p{N}]+/gu, "");
const unleet = (s: string): string => s.replace(/[01345789]/g, (d) => LEET[d] ?? d);

/** Optimal string alignment distance, cut off at `max` + 1. */
export function osaDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev2: number[] = [];
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j]! + 1, cur[j - 1]! + 1, prev[j - 1]! + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2]! + 1);
      cur.push(v);
      if (v < best) best = v;
    }
    if (best > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[b.length]!;
}

function isIpv4(host: string): boolean {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host);
}

/** Loopback, private, link-local, CGNAT and unspecified ranges: local devices, not worth a warning. */
function isLocalIp(host: string): boolean {
  if (host.startsWith("[")) {
    const h = host.slice(1, -1).toLowerCase();
    return h === "::1" || h === "::" || /^f[cd]/.test(h) || /^fe[89ab]/.test(h);
  }
  const [a, b] = host.split(".").map(Number) as [number, number];
  return (
    a === 10 || a === 127 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
    (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127)
  );
}

function officialBrand(host: string, lex: Lexicon): BrandEntry | undefined {
  return lex.brands.find((b) => b.domains.some((d) => host === d || host.endsWith("." + d)));
}

const ref = (b: BrandEntry): BrandRef => ({ id: b.id, name_ar: b.name_ar, name_en: b.name_en, domains: b.domains });

interface BrandHit {
  brand: BrandEntry;
  kind: "brand_in_host" | "brand_lookalike";
}

/** Find a brand name in an (already Latin, lower-case) host. */
function findBrand(host: string, lex: Lexicon): BrandHit | undefined {
  const labels = host.split(".");
  const parts = labels.flatMap((l) => l.split("-")).filter(Boolean);
  const whole = compact(host);
  const labelForms = labels.map(compact).filter(Boolean);
  const weak = new Set(lex.weak_tokens);
  // A region word counts only before the last label: ".ae" itself says nothing about intent.
  const inner = labels.slice(0, -1).flatMap((l) => l.split("-"));
  const hasHint =
    inner.some((p) => lex.region_hints.includes(p)) || lex.combo_words.some((w) => w.length >= 3 && parts.includes(w));

  let lookalike: BrandEntry | undefined;
  for (const brand of lex.brands) {
    for (const tok of brand.tokens) {
      const strong = tok.length >= STRONG_MIN && !weak.has(tok);
      if (strong) {
        if (whole.includes(tok)) return { brand, kind: "brand_in_host" };
      } else if (hasHint && (parts.includes(tok) || labelForms.includes(tok))) {
        // short or ordinary-word token: needs to stand alone AND sit next to a service or region word
        return { brand, kind: "brand_in_host" };
      }
      if (lookalike || !strong || tok.length < TYPO_MIN) continue;
      if (unleet(whole).includes(tok)) {
        lookalike = brand; // digit-for-letter swap, e.g. 0 for o
        continue;
      }
      const max = tok.length >= 12 ? 2 : 1;
      if (labelForms.some((l) => l !== tok && osaDistance(l, tok, max) <= max)) lookalike = brand;
    }
  }
  return lookalike ? { brand: lookalike, kind: "brand_lookalike" } : undefined;
}

function freeHostSuffix(host: string, lex: Lexicon): string | undefined {
  return lex.free_host_suffixes.find((s) => host.endsWith("." + s));
}

/**
 * Judge one URL. `trustedHosts` are hosts the extension itself talks to (the configured API and
 * web app), which may legitimately sit on a tunnel.
 */
export function prefilter(rawUrl: string, lex: Lexicon, trustedHosts: readonly string[] = []): PrefilterResult {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return SKIP;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return SKIP;
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (!host || host === "localhost" || host.endsWith(".localhost") || trustedHosts.includes(host)) {
    return { ...SKIP, host };
  }

  const signals: LocalSignal[] = [];
  let brand: BrandEntry | undefined;

  // Text before "@" is never the destination. Checked first: it applies to official hosts too,
  // because the visible name is the bait and the real host is what follows.
  if (url.username) signals.push({ id: "userinfo", block: true, detail: decodeSafe(url.username).slice(0, 64) });

  const ip = isIpv4(host) || host.startsWith("[");
  if (ip) {
    if (!isLocalIp(host)) signals.push({ id: "ip_host", block: true });
    return finish(host, signals, undefined);
  }

  const official = officialBrand(host, lex);
  if (official) {
    if (signals.length) return finish(host, signals, undefined);
    return { level: "official", host, signals: [], brand: ref(official) };
  }

  const uniLabels = host.split(".").map(toUnicodeLabel);
  const nonAscii = uniLabels.some((l) => /[^\x00-\x7f]/.test(l));
  if (nonAscii) {
    if (uniLabels.some((l) => isMixed(scriptsOf(l)))) signals.push({ id: "mixed_script", block: true });
    const folded = uniLabels.map(skeleton).join(".");
    // Only a host that folds entirely to ASCII can be read as a Latin brand name.
    if (/^[\x00-\x7f]+$/.test(folded)) {
      brand = findBrand(folded, lex)?.brand ?? officialBrand(folded, lex);
      if (brand) signals.push({ id: "homograph", block: true, brandId: brand.id });
    }
  } else {
    const hit = findBrand(host, lex);
    if (hit) {
      brand = hit.brand;
      signals.push({ id: hit.kind, block: true, brandId: brand.id });
    }
  }

  const free = freeHostSuffix(host, lex);
  if (free) {
    // The tenant name is the part before the suffix. A service word there ("login", "verify")
    // on throwaway hosting is the classic kit; the suffix alone is only worth a note.
    const tenantParts = host.slice(0, -free.length - 1).split(/[.-]/);
    const bait = lex.combo_words.some((w) => w.length >= 5 && tenantParts.includes(w));
    signals.push({ id: "free_host", block: bait || signals.some((s) => s.block), detail: free });
  }

  return finish(host, signals, brand);
}

function finish(host: string, signals: LocalSignal[], brand: BrandEntry | undefined): PrefilterResult {
  const level: LocalLevel = signals.some((s) => s.block) ? "warn" : signals.length ? "note" : "none";
  return brand ? { level, host, signals, brand: ref(brand) } : { level, host, signals };
}

function decodeSafe(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/** Display form required everywhere a URL is shown: never clickable, never auto-linked. */
export function defang(value: string): string {
  return value.replace(/^http(s?):\/\//i, "hxxp$1://").replace(/\./g, "[.]").slice(0, 512);
}
