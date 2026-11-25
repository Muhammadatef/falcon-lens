import type { Metadata } from "next";
import Link from "next/link";
import { CapBadge } from "@/components/CapBadge";
import { ArchLayers } from "@/components/arch/ArchLayers";
import { Icon, type IconName } from "@/components/Icon";
import { flag } from "@/lib/cap-flag";
import { loadCapabilities } from "@/lib/capabilities";
import { DOC_SLUGS, type DocSlug } from "@/lib/docs-content";
import { dt } from "@/lib/i18n-docs";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

const ICONS: Record<DocSlug, IconName> = { architecture: "box", agents: "spark", "building-agents": "list", cascade: "list", arbiter: "scale", security: "keep", evals: "refresh", integration: "url", privacy: "eye" };

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: dt(lang, "docs.title"), description: dt(lang, "docs.lead") });
}

export default async function DocsLanding() {
  const lang = await serverLang();
  const caps = await loadCapabilities();
  return (
    <main id="main" className="docs-page">
      <span className="eyebrow">{dt(lang, "docs.eyebrow")}</span>
      <h1 className="page-title">{dt(lang, "docs.title")}</h1>
      <p className="page-lead">{dt(lang, "docs.lead")}</p>
      <ol className="docs-grid" data-testid="docs-cards">
        {DOC_SLUGS.map((slug) => (
          <li className="card docs-card" key={slug}>
            <Icon name={ICONS[slug]} size={26} />
            <h2>{dt(lang, `docs.${slug}.title`)}</h2>
            <p>{dt(lang, `docs.${slug}.text`)}</p>
            {slug === "security" ? <p><CapBadge live={flag(caps, "injection_defence")} lang={lang} /></p> : null}
            <Link className="docs-read" href={`/docs/${slug}`} aria-label={`${dt(lang, "docs.read")}: ${dt(lang, `docs.${slug}.title`)}`}>
              {dt(lang, "docs.read")}
            </Link>
          </li>
        ))}
      </ol>
      <ArchLayers lang={lang} caps={caps as unknown as Record<string, boolean>} />
      <p className="card callout docs-back">
        <Icon name="hand" size={24} />
        <Link href="/agents">{dt(lang, "docs.back")}</Link>
      </p>
    </main>
  );
}
