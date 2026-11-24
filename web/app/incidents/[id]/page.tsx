import type { Metadata } from "next";
import "./trace.css";
import { notFound } from "next/navigation";
import { IncidentTrace } from "@/components/IncidentTrace";
import { INCIDENT_ID_RE } from "@/lib/contracts";
import { trT } from "@/lib/i18n-trace";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

/** Title in the visitor's language, same pattern as every other page. */
export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: trT(lang, "tr.title"), description: trT(lang, "tr.sub") });
}

export default async function IncidentTracePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  if (!INCIDENT_ID_RE.test(id)) notFound();
  const query = await searchParams;
  return <IncidentTrace incidentId={id} demo={query.demo === "1"} />;
}
