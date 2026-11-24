import { WindowLimiter } from "@/lib/public-campaigns";
import { toPublicCheck } from "@/lib/public-history";
import { notConnected } from "../../campaigns/shared";
import { publicJson } from "../../stream";

export const dynamic = "force-dynamic";
const limiter = new WindowLimiter(60, 60_000);

/** Public, read-only trace of one check: verdict, score, tiers, evidence codes and texts, reasons, tool names, latency. No raw input. */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^vd_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) return notConnected(404);
  return publicJson(limiter, request, `/v1/verdicts/${id}`, toPublicCheck);
}
