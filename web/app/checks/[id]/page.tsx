import type { Metadata } from "next";
import "../../history/history.css";
import { notFound } from "next/navigation";
import { CheckTrace } from "@/components/CheckTrace";
import { VERDICT_ID_RE } from "@/lib/contracts";

export const metadata: Metadata = { title: "مسار الفحص | عدسة الصقر · Check trace | Falcon Lens", robots: { index: false, follow: false } };

export default async function CheckTracePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  if (!VERDICT_ID_RE.test(id)) notFound();
  const query = await searchParams;
  return <CheckTrace verdictId={id} demo={query.demo === "1"} />;
}
