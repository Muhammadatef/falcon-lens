import type { Metadata } from "next";
import { IncidentBoard } from "@/components/IncidentBoard";

export const metadata: Metadata = { title: "لوحة الحوادث | عدسة الصقر · Incident board | Falcon Lens" };

export default async function OpsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <IncidentBoard demo={params.demo === "1"} />;
}
