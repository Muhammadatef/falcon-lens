import type { Metadata } from "next";
import { CampaignBoard } from "@/components/CampaignBoard";

export const metadata: Metadata = { title: "الحملات | عدسة الصقر · Campaigns | Falcon Lens" };

export default async function CampaignsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <CampaignBoard demo={params.demo === "1"} />;
}
