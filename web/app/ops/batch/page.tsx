import type { Metadata } from "next";
import { BatchTool } from "@/components/BatchTool";
import { bt } from "@/lib/i18n-batch";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return { ...pageMetadata(lang, { title: bt(lang, "title"), description: bt(lang, "sub") }), robots: { index: false, follow: false } };
}

export default function BatchPage() {
  return <BatchTool />;
}
