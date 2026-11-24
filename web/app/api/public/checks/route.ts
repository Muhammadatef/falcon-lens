import { WindowLimiter } from "@/lib/public-campaigns";
import { toPublicCheckPage } from "@/lib/public-history";
import { publicJson } from "../stream";

export const dynamic = "force-dynamic";
const limiter = new WindowLimiter(30, 60_000);

/** Public, read-only list of Investigator checks: redacted summaries only (defanged host for links, nothing for other inputs). */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") ?? "25", 10) || 25));
  const cursor = url.searchParams.get("cursor");
  const q = new URLSearchParams({ limit: String(limit) });
  if (cursor && /^\d{1,20}-\d{1,20}$/.test(cursor)) q.set("cursor", cursor);
  return publicJson(limiter, request, `/v1/verdicts?${q}`, toPublicCheckPage);
}
