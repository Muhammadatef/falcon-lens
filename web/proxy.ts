import { NextResponse, type NextRequest } from "next/server";

/**
 * Per-request CSP nonce (Next.js 16 `proxy.ts`, formerly middleware).
 * https://nextjs.org/docs/app/guides/content-security-policy
 *
 * Production policy has no 'unsafe-inline' and no 'unsafe-eval'. Next.js reads the nonce
 * from the request's CSP header and stamps it on its own scripts. `next dev` needs
 * 'unsafe-eval' (React debugging) and inline styles (HMR), so those are dev-only.
 */
export function buildCsp(nonce: string, isDev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' ${isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`}`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/** The microphone is allowed for our own origin on the voice assistant page only; every other page keeps it off. */
export function permissionsPolicy(pathname: string): string {
  const mic = pathname === "/voice" || pathname.startsWith("/voice/") ? "(self)" : "()";
  return `camera=(), microphone=${mic}, geolocation=(), payment=()`;
}

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "no-referrer");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Permissions-Policy", permissionsPolicy(request.nextUrl.pathname));
  return response;
}

export const config = {
  matcher: [
    {
      // Not matched: API routes and static files (the gateway gives those a deny-all fallback CSP).
      // /sw.js IS matched: a worker runs under the CSP its script was served with, and it needs
      // connect-src 'self' to fetch the offline shell.
      source: "/((?!api/|_next/static/|_next/image|fonts/|icons/|images/|og/|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
