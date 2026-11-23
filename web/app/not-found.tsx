import type { Metadata } from "next";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { translate } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return { ...pageMetadata(lang, { title: translate(lang, "nf.title") }), robots: { index: false, follow: false } };
}

export default async function NotFound() {
  const lang = await serverLang();
  const t = (k: Parameters<typeof translate>[1]) => translate(lang, k);
  return (
    <main id="main" className="wrap err-page" data-testid="not-found">
      <Icon name="no_warning_signs" size={56} />
      <span className="err-code">404</span>
      <h1 className="page-title">{t("nf.title")}</h1>
      <p className="page-lead">{t("nf.body")}</p>
      <div className="err-actions">
        <Link className="btn btn--primary" href="/">{t("err.home")}</Link>
        <Link className="btn" href="/how-it-works">{t("nav.how")}</Link>
      </div>
    </main>
  );
}
