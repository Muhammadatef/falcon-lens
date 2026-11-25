import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import type { ReactNode } from "react";
import { AppShell, Footer, Header } from "@/components/Chrome";
import type { Lang } from "@/lib/contracts";
import { loadCapabilities } from "@/lib/capabilities";
import { metadataBase, pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";
import { PrefsProvider, type Theme } from "@/lib/prefs";
import "./globals.css";
import "./arch.css";
import "./building-agents.css";
import "./audit-fixes.css";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  const caps = await loadCapabilities();
  return {
    ...pageMetadata(lang, undefined, caps.message_check && caps.email_check && caps.image_check),
    metadataBase: metadataBase(),
    applicationName: "Falcon Lens",
    appleWebApp: { capable: true, title: "عدسة الصقر", statusBarStyle: "black-translucent" },
    icons: {
      icon: [{ url: "/icons/icon.svg", type: "image/svg+xml" }, { url: "/favicon.ico", sizes: "48x48" }, { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
    },
    referrer: "no-referrer",
    robots: { index: false, follow: false },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#070b14" },
    { media: "(prefers-color-scheme: light)", color: "#070b14" },
  ],
};

/**
 * Language and theme come from cookies, so the server renders the right `lang`, `dir`
 * and `data-theme` with no inline theme script. Defaults: Arabic, Night.
 * Reading cookies/headers also makes every page dynamic, which the per-request CSP
 * nonce (proxy.ts) requires.
 */
export default async function RootLayout({ children }: { children: ReactNode }) {
  const jar = await cookies();
  const lang: Lang = jar.get("fl_lang")?.value === "en" ? "en" : "ar";
  const theme: Theme = jar.get("fl_theme")?.value === "light" ? "light" : "dark";
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html lang={lang} dir={lang === "ar" ? "rtl" : "ltr"} data-theme={theme}>
      <body>
        <div className="bg bg-glow" />
        <div className="bg bg-lattice" />
        <PrefsProvider initialLang={lang} initialTheme={theme} nonce={nonce}>
          <Header />
          <AppShell />
          {children}
          <Footer />
        </PrefsProvider>
      </body>
    </html>
  );
}
