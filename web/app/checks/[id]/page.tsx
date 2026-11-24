import type { Metadata } from "next";
import "../../history/history.css";
import { notFound } from "next/navigation";
import { CheckTrace } from "@/components/CheckTrace";
import { VERDICT_ID_RE } from "@/lib/contracts";
import { hT } from "@/lib/i18n-history";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

/** Title in the visitor's language, same pattern as every other page. */
export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return { ...pageMetadata(lang, { title: hT(lang, "ck.title"), description: hT(lang, "ck.sub") }), robots: { index: false, follow: false } };
}

export default async function CheckTracePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  if (!VERDICT_ID_RE.test(id)) notFound();
  const query = await searchParams;
  return <CheckTrace verdictId={id} demo={query.demo === "1"} />;
}
