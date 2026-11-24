import { toPublicIncident } from "@/lib/public-history";
import { publicStream } from "../../stream";

export const dynamic = "force-dynamic";
export const GET = publicStream("/v1/incidents/stream", "incident", toPublicIncident);
