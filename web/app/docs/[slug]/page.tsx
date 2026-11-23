import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AgentsDoc } from "@/components/docs/AgentsDoc";
import { DocBody } from "@/components/docs/DocBody";
import { ARCH } from "@/lib/arch-content";
import { loadCapabilities } from "@/lib/capabilities";
import { DOCS, DOC_SLUGS, isDocSlug } from "@/lib/docs-content";
import { dt } from "@/lib/i18n-docs";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export const dynamicParams = false;
export function generateStaticParams() {
  return DOC_SLUGS.map((slug) => ({ slug }));
}

type Props = { params: Promise<{ slug: string }> };

const leadOf = (lang: "ar" | "en", slug: (typeof DOC_SLUGS)[number]): string => (slug === "agents" ? ARCH[lang].lead : DOCS[lang][slug].lead);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  if (!isDocSlug(slug)) return {};
  const lang = await serverLang();
  return pageMetadata(lang, { title: dt(lang, `docs.${slug}.title`), description: leadOf(lang, slug).slice(0, 160) });
}

export default async function DocPageRoute({ params }: Props) {
  const { slug } = await params;
  if (!isDocSlug(slug)) notFound();
  const lang = await serverLang();
  const caps = await loadCapabilities();
  return (
    <main id="main" className="docs-page" data-doc={slug}>
      <span className="eyebrow">{dt(lang, "docs.eyebrow")}</span>
      <h1 className="page-title">{dt(lang, `docs.${slug}.title`)}</h1>
      <p className="page-lead">{leadOf(lang, slug)}</p>
      {slug === "agents" ? <AgentsDoc lang={lang} caps={caps} /> : <DocBody page={DOCS[lang][slug]} lang={lang} caps={caps} />}
    </main>
  );
}
