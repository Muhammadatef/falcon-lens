import type { Metadata } from "next";
import "./trace.css";
import { notFound } from "next/navigation";
import { IncidentTrace } from "@/components/IncidentTrace";
import { INCIDENT_ID_RE } from "@/lib/contracts";

export const metadata: Metadata = { title: "مسار الحارس | عدسة الصقر · Agent trace | Falcon Lens" };

export default async function IncidentTracePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  if (!INCIDENT_ID_RE.test(id)) notFound();
  const query = await searchParams;
  return <IncidentTrace incidentId={id} demo={query.demo === "1"} />;
}
