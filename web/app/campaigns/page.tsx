import type { Metadata } from "next";
import { CampaignBoard } from "@/components/CampaignBoard";
import { translate } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: translate(lang, "board.title"), description: translate(lang, "board.sub") });
}

export default async function CampaignsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <CampaignBoard demo={params.demo === "1"} />;
}
