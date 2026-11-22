// Inputs are strings fed to a pure function. Nothing here is fetched. Lookalike cases use only the
// invented brand "Falcon Demo Bank" on reserved test domains (.test, .example) or documentation IPs.
import { describe, expect, it } from "vitest";
import lexiconJson from "../src/generated/lexicon.json";
import { defang, osaDistance, prefilter, punycodeDecode, skeleton, toUnicodeLabel, type Lexicon } from "../src/prefilter";

const lex = lexiconJson as Lexicon;
const run = (url: string, trusted: string[] = []) => prefilter(url, lex, trusted);
const ids = (url: string) => run(url).signals.map((s) => s.id);

describe("official domains never warn", () => {
  it("covers every verified domain in data/brands.yaml, bare and with subdomains", () => {
    const domains = lex.brands.flatMap((b) => b.domains);
    expect(domains.length).toBeGreaterThan(20);
    for (const d of domains) {
      for (const host of [d, `www.${d}`, `login.secure.${d}`]) {
        const r = run(`https://${host}/services/pay?id=1`);
        expect(r.level, host).toBe("official");
        expect(r.signals, host).toEqual([]);
      }
    }
  });

  it("names the brand for the demo bank", () => {
    const r = run("https://online.falcon-demo-bank.test/login");
    expect(r.level).toBe("official");
    expect(r.brand?.id).toBe("falcon_demo_bank");
  });
});

describe("Falcon Demo Bank lookalikes warn", () => {
  const cases: [string, string][] = [
    ["brand in a subdomain of another site", "http://falcon-demo-bank.secure-verify.example/login"],
    ["brand plus a service word", "https://falcon-demo-bank-login.example/"],
    ["brand glued without hyphens", "https://falcondemobank.example/update"],
    ["official domain used as a subdomain", "https://falcon-demo-bank.test.account-check.example/"],
    ["brand on a tunnel", "https://falcon-demo-bank.trycloudflare.com/"],
  ];
  for (const [name, url] of cases) {
    it(name, () => {
      const r = run(url);
      expect(r.level).toBe("warn");
      expect(r.brand?.id).toBe("falcon_demo_bank");
      expect(r.signals[0]).toMatchObject({ id: "brand_in_host", block: true });
    });
  }

  it("digit swapped for a letter", () => {
    const r = run("https://falc0n-dem0-bank.example/");
    expect(r.level).toBe("warn");
    expect(ids("https://falc0n-dem0-bank.example/")).toEqual(["brand_lookalike"]);
    expect(r.brand?.id).toBe("falcon_demo_bank");
  });

  it("one letter off (capital I typed for l lowercases to i)", () => {
    expect(ids("https://faIcon-demo-bank.example/")).toEqual(["brand_lookalike"]);
    expect(ids("https://falcon-demo-bnak.example/")).toEqual(["brand_lookalike"]);
  });

  it("an unrelated name does not match", () => {
    expect(run("https://heron-sample-shop.example/").level).toBe("none");
    expect(run("https://falcon-photography.example/").level).toBe("none");
  });
});

describe("IDN homograph", () => {
  it("Cyrillic letters that spell the demo bank", () => {
    // U+0430 CYRILLIC SMALL LETTER A and U+043E CYRILLIC SMALL LETTER O
    const r = run("https://fаlcоn-demo-bank.example/");
    expect(r.host.startsWith("xn--")).toBe(true);
    expect(r.level).toBe("warn");
    expect(r.signals.map((s) => s.id)).toEqual(["mixed_script", "homograph"]);
    expect(r.brand?.id).toBe("falcon_demo_bank");
  });

  it("the same host given in punycode form", () => {
    const puny = new URL("https://fаlcоn-demo-bank.example/").hostname;
    expect(ids(`https://${puny}/`)).toContain("homograph");
  });

  it("look-alike of the official domain itself", () => {
    const r = run("https://fаlcon-demo-bank.test/");
    expect(r.level).toBe("warn");
    expect(ids("https://fаlcon-demo-bank.test/")).toContain("homograph");
  });

  it("an accent on a brand name", () => {
    expect(ids("https://falcón-demo-bank.example/")).toEqual(["homograph"]);
  });

  it("a plain Arabic domain name is not a warning", () => {
    const r = run("https://موقع.example/");
    expect(r.host.startsWith("xn--")).toBe(true);
    expect(r.level).toBe("none");
  });

  it("mixed alphabets in one label warn even without a brand", () => {
    expect(ids("https://exаmple-shop.example/")).toEqual(["mixed_script"]);
  });
});

describe("host shape", () => {
  it("public IP address", () => {
    expect(run("http://203.0.113.7/login").level).toBe("warn");
    expect(ids("http://203.0.113.7/login")).toEqual(["ip_host"]);
    expect(ids("http://[2001:db8::1]/")).toEqual(["ip_host"]);
  });

  it("obfuscated IP forms are normalised by the URL parser", () => {
    expect(ids("http://0xcb.0x00.0x71.0x07/")).toEqual(["ip_host"]);
    expect(ids("http://3405803783/")).toEqual(["ip_host"]);
  });

  it("local devices are left alone", () => {
    for (const u of ["http://192.168.1.1/", "http://10.0.0.2/", "http://127.0.0.1:8080/", "http://[::1]/", "http://localhost:3000/"]) {
      expect(run(u).level, u).not.toBe("warn");
    }
  });

  it("userinfo hides the real host", () => {
    const r = run("https://falcon-demo-bank.test@203.0.113.9/login");
    expect(r.level).toBe("warn");
    expect(r.signals[0]).toMatchObject({ id: "userinfo", block: true, detail: "falcon-demo-bank.test" });
  });

  it("userinfo warns even in front of an official domain", () => {
    expect(run("https://notice@falcon-demo-bank.test/").level).toBe("warn");
  });
});

describe("free hosts and tunnels", () => {
  it("alone is only a note", () => {
    const r = run("https://my-notes.github.io/page");
    expect(r.level).toBe("note");
    expect(r.signals).toEqual([{ id: "free_host", block: false, detail: "github.io" }]);
  });

  it("with a service word in the tenant name it warns", () => {
    expect(run("https://account-verification.ngrok-free.app/").level).toBe("warn");
  });

  it("the suffix owner's own site is not a tenant", () => {
    expect(run("https://trycloudflare.com/").level).toBe("none");
  });

  it("the configured API or web app host is trusted", () => {
    const host = "falcon-demo-bank-api.trycloudflare.com";
    expect(run(`https://${host}/`).level).toBe("warn");
    expect(run(`https://${host}/`, [host]).level).toBe("skip");
  });
});

describe("short and ordinary-word tokens need a second hint", () => {
  it("a three or four letter token inside another word is ignored", () => {
    expect(run("https://edewatering.example/").level).toBe("none");
    expect(run("https://start-app.example/").level).toBe("none");
  });

  it("standing alone next to a service word it warns", () => {
    const r = run("https://demobank-login.example/");
    expect(r.level).toBe("warn");
    expect(r.brand?.id).toBe("falcon_demo_bank");
  });

  it("standing alone with no hint it does not", () => {
    expect(run("https://demobank.example/").level).toBe("none");
  });
});

describe("not checkable", () => {
  it("skips non-web schemes and junk", () => {
    for (const u of ["chrome://extensions", "about:blank", "javascript:alert(1)", "data:text/html,hi", "file:///etc/hosts", "not a url", ""]) {
      expect(run(u).level, u).toBe("skip");
    }
  });
});

describe("helpers", () => {
  it("punycode round trip", () => {
    expect(punycodeDecode("mnchen-3ya")).toBe("münchen");
    expect(toUnicodeLabel("xn--mgbh0fb")).toBe("مثال");
    expect(toUnicodeLabel("plain")).toBe("plain");
    expect(punycodeDecode("!!")).toBeNull();
  });

  it("skeleton folds look-alikes and accents", () => {
    expect(skeleton("fаlcоn")).toBe("falcon");
    expect(skeleton("Falcón")).toBe("falcon");
  });

  it("osa distance counts a swap as one edit", () => {
    expect(osaDistance("bnak", "bank", 1)).toBe(1);
    expect(osaDistance("falcon", "falcon", 1)).toBe(0);
    expect(osaDistance("abcdef", "uvwxyz", 1)).toBe(2);
  });

  it("defang makes a URL unclickable", () => {
    expect(defang("https://falcon-demo-bank.example/a.b")).toBe("hxxps://falcon-demo-bank[.]example/a[.]b");
  });
});
