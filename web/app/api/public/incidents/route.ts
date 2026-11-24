import { WindowLimiter } from "@/lib/public-campaigns";
import { toPublicIncidentPage } from "@/lib/public-history";
import { publicJson } from "../stream";

export const dynamic = "force-dynamic";
const limiter = new WindowLimiter(30, 60_000);

/** Public, read-only incident list: titles, severity, status, counts. No drafts, no approvers. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") ?? "25", 10) || 25));
  const cursor = url.searchParams.get("cursor");
  const q = new URLSearchParams({ limit: String(limit) });
  if (cursor && /^[\w=-]{1,200}$/.test(cursor)) q.set("cursor", cursor);
  return publicJson(limiter, request, `/v1/incidents?${q}`, toPublicIncidentPage);
}
