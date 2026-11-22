import { describe, expect, it } from "vitest";
import { buildInput } from "@/components/CheckBox";
import { looksLikeEml, problemFromStatus, safeEventsUrl, utf8Bytes } from "@/lib/api";
import { clip, defang, looksLikeSingleUrl, refang, splitDefanged } from "@/lib/defang";
import { MESSAGES, pick, translate, translateMaybe } from "@/lib/i18n";
import { planShare } from "@/lib/share";
import { createSseParser, type SseMessage } from "@/lib/sse";
import { buildCsp } from "@/proxy";

describe("defang", () => {
  it("defangs scheme and host, and is idempotent", () => {
    const once = defang("https://falcon-demo-bank-secure.test/login?a=b.c");
    expect(once).toBe("hxxps://falcon-demo-bank-secure[.]test/login?a=b.c");
    expect(defang(once)).toBe(once);
    expect(defang("http://a.test")).toBe("hxxp://a[.]test");
    expect(defang("falcon-demo-bank.test/x")).toBe("falcon-demo-bank[.]test/x");
  });
  it("strips bidi controls and control characters", () => {
    expect(defang("https://a.test/‮gnp.exe\u0000")).toBe("hxxps://a[.]test/gnp.exe");
  });
  it("splits for display", () => {
    expect(splitDefanged("hxxps://a[.]test/login")).toEqual({ scheme: "hxxps://", host: "a[.]test", rest: "/login" });
  });
  it("recognises a lone link, not a sentence", () => {
    expect(looksLikeSingleUrl("https://x.test/a")).toBe(true);
    expect(looksLikeSingleUrl("x.com/someone/status/1")).toBe(true);
    expect(looksLikeSingleUrl("hxxps://x[.]test")).toBe(true);
    expect(looksLikeSingleUrl("تم إيقاف بطاقتك https://x.test")).toBe(false);
    expect(looksLikeSingleUrl("hello")).toBe(false);
    expect(looksLikeSingleUrl("")).toBe(false);
  });
  it("clips long echoes", () => {
    expect(clip("a".repeat(300)).length).toBe(180);
    expect(clip("a  b\n c")).toBe("a b c");
  });
});

describe("buildInput", () => {
  const file = (name: string, type: string, size = 10) => new File([new Uint8Array(size)], name, { type });
  it("routes a lone link to the URL check and prose to the message check, whatever the tab", () => {
    expect(buildInput("url", " https://x.test/a ", null)).toMatchObject({ input: { kind: "url", url: "https://x.test/a" } });
    expect(buildInput("url", "your card is blocked https://x.test", null)).toMatchObject({ input: { kind: "message" } });
    expect(buildInput("message", "x.test/pay", null)).toMatchObject({ input: { kind: "url" } });
  });
  it("validates files and empties", () => {
    expect(buildInput("url", "  ", null)).toEqual({ error: "err.empty" });
    expect(buildInput("image", "", null)).toEqual({ error: "err.file" });
    expect(buildInput("image", "", file("a.pdf", "application/pdf"))).toEqual({ error: "err.filetype" });
    expect(buildInput("image", "", file("a.png", "image/png", 6 * 1024 * 1024))).toEqual({ error: "err.toobig" });
    expect(buildInput("image", "", file("qr.png", "image/png"))).toMatchObject({ input: { kind: "image" }, preview: { kind: "image", text: "qr.png" } });
    expect(buildInput("email", "", file("m.eml", "message/rfc822"))).toMatchObject({ input: { kind: "email" } });
    expect(buildInput("email", "", file("m.txt", "text/plain"))).toEqual({ error: "err.emltype" });
    expect(buildInput("image", "", file("a.gif", "image/gif"))).toEqual({ error: "err.filetype" });
  });
  it("sends pasted email as an .eml upload when it has headers, otherwise as a message", () => {
    const built = buildInput("email", "From: a@b.test\nSubject: hi\n\nbody", null);
    expect(built).toMatchObject({ input: { kind: "email" } });
    const sent = "input" in built && built.input.kind === "email" ? built.input.file : null;
    expect(sent?.name).toBe("pasted.eml");
    expect(sent?.type).toBe("message/rfc822");
    expect(buildInput("email", "Dear customer, your card is blocked", null)).toMatchObject({ input: { kind: "message" } });
    expect(looksLikeEml("Subject: x\r\n\r\nbody")).toBe(true);
    expect(looksLikeEml("hello\nFrom: a")).toBe(false);
  });
  it("measures limits in UTF-8 bytes like the API, and refangs a defanged link for submission", () => {
    expect(utf8Bytes("عربي")).toBe(8);
    expect(buildInput("message", "رسالة ".repeat(800), null)).toEqual({ error: "err.toobig" }); // 4800 chars, 8800 bytes
    expect(buildInput("message", "word ".repeat(1500), null)).toMatchObject({ input: { kind: "message" } });
    expect(buildInput("url", "hxxps://falcon-demo-bank-secure[.]test/login", null)).toMatchObject({ input: { kind: "url", url: "https://falcon-demo-bank-secure.test/login" }, preview: { text: "hxxps://falcon-demo-bank-secure[.]test/login" } });
    expect(refang("hxxp://a[.]b(.)test")).toBe("http://a.b.test");
  });
});

describe("api helpers", () => {
  it("maps HTTP status to problems", () => {
    expect(problemFromStatus(429, "30")).toEqual({ kind: "rate_limited", status: 429, retryAfter: 30 });
    expect(problemFromStatus(429, "soon")).toEqual({ kind: "rate_limited", status: 429, retryAfter: undefined });
    expect(problemFromStatus(413).kind).toBe("too_large");
    expect(problemFromStatus(422).kind).toBe("invalid");
    expect(problemFromStatus(411).kind).toBe("invalid");
    expect(problemFromStatus(415).kind).toBe("unsupported");
    expect(problemFromStatus(503).kind).toBe("unavailable");
    expect(problemFromStatus(404).kind).toBe("not_found");
    expect(problemFromStatus(502).kind).toBe("unavailable");
  });
  it("opens only same-origin verdict event paths", () => {
    const id = "vd_01KB0DEM0DATA0000000000001";
    expect(safeEventsUrl(`/v1/verdicts/${id}/events`, id)).toBe(`/v1/verdicts/${id}/events`);
    expect(safeEventsUrl("https://evil.test/v1/verdicts/x/events", id)).toBe(`/v1/verdicts/${id}/events`);
    expect(safeEventsUrl("//evil.test/x", id)).toBe(`/v1/verdicts/${id}/events`);
    expect(safeEventsUrl(undefined, id)).toBe(`/v1/verdicts/${id}/events`);
  });
});

describe("share target planning", () => {
  const file = (name: string, type: string) => new File([new Uint8Array(4)], name, { type });
  const base = { title: "", text: "", url: "", files: [] as File[] };
  it("prefers files, then a lone link, then the message", () => {
    expect(planShare({ ...base, text: "x", files: [file("s.png", "image/png")] }).kind).toBe("image");
    expect(planShare({ ...base, files: [file("m.eml", "")] }).kind).toBe("email");
    expect(planShare({ ...base, text: "https://x.test/a" })).toEqual({ kind: "url", url: "https://x.test/a" });
    expect(planShare({ ...base, url: "https://x.test/a" })).toEqual({ kind: "url", url: "https://x.test/a" });
    expect(planShare({ ...base, text: "pay now", url: "https://x.test/a" })).toEqual({ kind: "message", text: "pay now\nhttps://x.test/a" });
    expect(planShare({ ...base, title: "only title" })).toEqual({ kind: "message", text: "only title" });
    expect(planShare(base)).toEqual({ kind: "none" });
  });
});

describe("SSE parser", () => {
  const collect = (chunks: string[]): SseMessage[] => {
    const out: SseMessage[] = [];
    const parser = createSseParser((m) => out.push(m));
    chunks.forEach((c) => parser.push(c));
    return out;
  };
  it("parses named events, multi-line data, comments and CRLF", () => {
    expect(collect([": hi\n\nevent: incident\ndata: {\"a\":1}\n\n", "data: x\r\ndata: y\r\n\r\n"])).toEqual([
      { event: "incident", data: '{"a":1}', id: undefined },
      { event: "message", data: "x\ny", id: undefined },
    ]);
  });
  it("handles events split across chunks", () => {
    expect(collect(["event: ver", "dict\nda", "ta: 1\n", "\n"])).toEqual([{ event: "verdict", data: "1", id: undefined }]);
  });
  it("does not dispatch without a blank line", () => {
    expect(collect(["data: 1\n"])).toEqual([]);
  });
});

describe("i18n", () => {
  it("has the same keys in both languages", () => {
    expect(Object.keys(MESSAGES.en).sort()).toEqual(Object.keys(MESSAGES.ar).sort());
  });
  it("never says safe / آمن (product rule)", () => {
    for (const s of Object.values(MESSAGES.en)) expect(s.toLowerCase(), s).not.toMatch(/\bsafe(ly|r|st)?\b/);
    for (const s of Object.values(MESSAGES.ar)) expect(s, s).not.toMatch(/(^|[^؀-ۿ])(ال)?آمن(ة)?($|[^؀-ۿ])/);
    expect(MESSAGES.en["v.no_warning_signs"]).toBe("No warning signs found");
    expect(MESSAGES.ar["v.no_warning_signs"]).toBe("لم نجد علامات تحذير");
  });
  it("translates, interpolates and falls back", () => {
    expect(translate("en", "p.retry_in", { n: 30 })).toBe("Try again in 30 seconds.");
    expect(translateMaybe("en", "tool", "draft_takedown")).toBe("Takedown request draft");
    expect(translateMaybe("en", "tool", "<b>new_tool</b>")).toBe("<b>new_tool</b>");
    expect(pick("ar", { en: "only en" })).toBe("only en");
    expect(pick("en", null)).toBe("");
  });
});

describe("CSP", () => {
  it("production policy is nonce-based with no unsafe sources", () => {
    const csp = buildCsp("abc", false);
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("style-src 'self' 'nonce-abc'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toMatch(/https?:/);
  });
  it("only development relaxes eval and inline styles", () => {
    expect(buildCsp("abc", true)).toContain("'unsafe-eval'");
  });
});
