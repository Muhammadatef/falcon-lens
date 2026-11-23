import type { Metadata } from "next";
import { IncidentBoard } from "@/components/IncidentBoard";
import { translate } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return { ...pageMetadata(lang, { title: translate(lang, "ops.title"), description: translate(lang, "ops.sub") }), robots: { index: false, follow: false } };
}

export default async function OpsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <IncidentBoard demo={params.demo === "1"} />;
}
