import { toPublicCheckSummary } from "@/lib/public-history";
import { publicStream } from "../../stream";

export const dynamic = "force-dynamic";
export const GET = publicStream("/v1/verdicts/stream", "verdict", toPublicCheckSummary);
