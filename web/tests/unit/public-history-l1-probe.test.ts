import { test, expect } from "vitest";
import { scrub, scrubAr } from "../../lib/public-history";

// L1 adversarial probe (PR #114 round 3): nothing beyond a defanged host may survive in public text.
const bad = [
  "https://u:p@evil.test:8443/reset/x?token=SECRETTOKEN#f", "http://203.0.113.7/login?token=SECRETTOKEN",
  "http://intranet/reset?token=SECRETTOKEN", "https:\\\\evil.test\\reset\\SECRETTOKEN", "evil。test/SECRETTOKEN",
  "evil[dot]test/SECRETTOKEN", "evil.test∕reset∕SECRETTOKEN", "data:text/html;base64,PHNjcmlwdD4=",
  "افتح evil.test/SECRETTOKEN الآن", "hxxps://evil[.]test/SECRETTOKEN", "evil.test%2FSECRETTOKEN",
  "رمزك ١٢٣٤٥٦ لا تشاركه", "call +971501234567", "mail me a@b.test", "javascript:alert(1)",
  "evil.test／SECRETTOKEN", "e​vil.test/SECRETTOKEN", "WWW.EVIL.TEST/SECRETTOKEN", "evil.test ⁄ SECRETTOKEN",
];
test.each(bad)("nothing sensitive survives: %s", (s) => {
  for (const f of [scrub, scrubAr]) {
    const out = f(s).replace(/hxxps?:\/\//g, "");
    expect(out).not.toMatch(/SECRETTOKEN|1234567|١٢٣٤٥٦|a@b|alert|PHNjc|\/|\\|@/);
  }
});
test("real reasons survive unchanged", () => {
  for (const s of ["The email failed sender checks (SPF, DKIM and DMARC).", "الصفحة تطلب كلمة المرور ورمز التحقق (OTP)", "العنوان جديد جداً: سُجّل قبل يومين."]) expect(scrub(s)).toBe(s);
});
