import { describe, expect, it } from "vitest";
import { hostOf, scrub } from "@/lib/public-history";

const survives = (out: string, secrets: string[]) => {
  for (const x of secrets) expect(out, `survived: ${x}`).not.toContain(x);
  expect(out).not.toMatch(/[?#@]/);
  expect(out).not.toMatch(/:\d{2,5}(?:\/|$|\s)/);
};

describe("scrub: reviewer cases and generated URLs", () => {
  it("userinfo, port, path, token and fragment are all dropped", () => {
    const out = scrub("Open https://admin:S3cretPw@login.example.test:8443/reset/path?token=abcDEF123&sid=99#frag now");
    survives(out, ["admin", "S3cretPw", "8443", "reset", "path", "abcDEF123", "sid", "frag"]);
    expect(out).toContain("hxxps://login[.]example[.]test");
  });

  it("IP and dotless hosts keep the host only", () => {
    const a = scrub("http://203.0.113.7/login?token=SECRETTOK");
    survives(a, ["login", "SECRETTOK"]);
    expect(a).toContain("203[.]0[.]113[.]7");
    const b = scrub("http://intranet/reset?token=SECRETTOK");
    survives(b, ["reset", "SECRETTOK"]);
    expect(b).toContain("hxxp://intranet");
    const c = scrub("http://[2001:db8::1]:8080/x?token=SECRETTOK");
    survives(c, ["2001", "8080", "SECRETTOK"]);
    expect(c).toContain("[link removed]");
  });

  it("phone forms: +971, 00971, 05x, Arabic-Indic", () => {
    const out = scrub("+971501234567 00971501234567 0501234567 ٠٥٠١٢٣٤٥٦٧ 050 123 4567");
    expect(out).not.toMatch(/\d{4}/);
  });

  it("fails closed when residue survives", () => {
    expect(scrub("what is a=b")).toBe("[text removed]");
    expect(scrub("see intranet/reset?x=1")).toBe("[text removed]");
  });

  it("property: 60 generated links never keep ? # @ port path or token", () => {
    let seed = 12345;
    const rnd = (n: number) => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) % n);
    const pick = <T,>(a: T[]) => a[rnd(a.length)]!;
    const hosts = ["login.example.test", "a-b.evil-example.com", "203.0.113.7", "10.0.0.5", "intranet", "[2001:db8::7]", "xn--mgbh0fb.test", "www.example.test"];
    const around = ["", "افتح الرابط ", "اضغط هنا: ", "Click ", "تحقق من "];
    for (let n = 0; n < 60; n++) {
      const user = rnd(2) ? `u${rnd(99)}:Pw${rnd(9999)}Zq@` : "";
      const port = rnd(2) ? `:${1000 + rnd(60000)}` : "";
      const path = rnd(3) ? `/seg${rnd(99)}Path/other` : "";
      const query = rnd(3) ? `?token=tok${rnd(99999)}XyZ&sid=${rnd(99)}` : "";
      const frag = rnd(2) ? `#fr${rnd(99)}ag` : "";
      const url = `${pick(["http://", "https://", "hxxps://", "ftp://"])}${user}${pick(hosts)}${port}${path}${query}${frag}`;
      const out = scrub(`${pick(around)}${url} ${pick(["", "شكراً", "thanks"])}`);
      expect(out, url).not.toMatch(/[?#@]/);
      expect(out, url).not.toMatch(/:\d{2,5}(?:\/|$|\s)/);
      expect(out, url).not.toMatch(/Pw\d|seg\d+Path|tok\d+XyZ|sid|fr\d+ag/);
    }
  });

  it("hostOf drops everything but the host", () => {
    expect(hostOf("https://u:p@a.example.test:99/x?y#z")).toBe("hxxps://a[.]example[.]test");
    expect(hostOf("http://203.0.113.7/login?token=1")).toBe("hxxp://203[.]0[.]113[.]7");
    expect(hostOf("login[.]evil[.]test/verify?token=1")).toBe("login[.]evil[.]test");
  });
});
