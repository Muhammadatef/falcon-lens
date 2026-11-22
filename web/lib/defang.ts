/**
 * Display-side defanging. The API already sends `canonical_url` defanged; this runs
 * again on anything URL-like we print (idempotent), so a live link can never reach the
 * screen even if an upstream field forgets. Output is rendered as text, never as href.
 */

const SCHEME_RE = /\b(h)(tt)(ps?)(:\/\/)/gi;

/** hxxp(s) scheme + [.] for every dot in the authority part. Idempotent. */
export function defang(input: string): string {
  let s = input.replace(/[\u0000-\u001f\u007f‎‏‪-‮⁦-⁩]/g, "");
  s = s.replace(SCHEME_RE, (_m, h: string, _tt: string, ps: string, sep: string) => `${h}xx${ps}${sep}`);
  const m = /^([a-z][a-z0-9+.-]*:\/\/)?([^/?#\s]*)(.*)$/is.exec(s);
  if (!m) return s;
  const [, scheme = "", authority = "", rest = ""] = m;
  if (!looksLikeHost(authority)) return s;
  return scheme + authority.replace(/\[\.\]/g, ".").replace(/\./g, "[.]") + rest;
}

function looksLikeHost(authority: string): boolean {
  return /^[^\s@]*@?[^\s]+(\.|\[\.\])[^\s]+$/.test(authority);
}

/**
 * Undoes defanging for SUBMISSION only (the API accepts http(s) URLs, and people often paste
 * a link that a colleague already defanged). The result is sent as JSON data, never rendered.
 */
export function refang(input: string): string {
  return input.trim().replace(/^hxxp(s?):\/\//i, "http$1://").replace(/\[\.\]|\(\.\)/g, ".");
}

export interface UrlParts {
  scheme: string;
  host: string;
  rest: string;
}

/** Splits a defanged URL so the host can be emphasised. */
export function splitDefanged(defanged: string): UrlParts {
  const m = /^([a-z][a-z0-9+.-]*:\/\/)?([^/?#\s]*)(.*)$/is.exec(defanged);
  if (!m) return { scheme: "", host: defanged, rest: "" };
  return { scheme: m[1] ?? "", host: m[2] ?? "", rest: m[3] ?? "" };
}

/** True when the text is one token that looks like a link or a bare domain. */
export function looksLikeSingleUrl(text: string): boolean {
  const t = text.trim();
  if (!t || /\s/.test(t) || t.length > 4096) return false;
  if (/^(https?|hxxps?):\/\//i.test(t)) return true;
  return /^[\p{L}\p{N}-]+(\.[\p{L}\p{N}-]+)+(:\d+)?([/?#].*)?$/u.test(t);
}

/** Middle-truncates long strings for the case header (full text is never needed there). */
export function clip(text: string, max = 180): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}
