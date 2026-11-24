import { requireOperator } from "@/lib/ops-gate";
import { configFromEnv } from "@/lib/observability";

export const dynamic = "force-dynamic";

/**
 * Base URLs of the local observability tools (Phoenix, Grafana, Prometheus), read from the server env at request time.
 * Operator only: the key in `x-ops-key` is verified against the API (401 anonymous, 403 not an operator key).
 * Only origins, no secrets.
 */
export async function GET(request: Request): Promise<Response> {
  const refused = await requireOperator(request);
  if (refused) return refused;
  return Response.json(configFromEnv(process.env), { headers: { "Cache-Control": "no-store" } });
}
