import type { Metadata } from "next";
import "./history.css";
import { HistoryBoard } from "@/components/HistoryBoard";
import { hT } from "@/lib/i18n-history";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return { ...pageMetadata(lang, { title: hT(lang, "hs.title"), description: hT(lang, "hs.sub") }), robots: { index: false, follow: false } };
}

export default async function HistoryPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <HistoryBoard demo={params.demo === "1"} initialTab={params.tab === "incidents" ? "incidents" : "checks"} />;
}
