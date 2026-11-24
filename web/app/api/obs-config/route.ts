import { configFromEnv } from "@/lib/observability";

export const dynamic = "force-dynamic";

/**
 * Base URLs of the local observability tools (Phoenix, Grafana, Prometheus), read from the server env at
 * request time. Only origins, no secrets. The browser asks for this only when an operator key is present,
 * and the links are shown to operators only; the tools themselves are bound to 127.0.0.1 and need a login.
 */
export function GET() {
  return Response.json(configFromEnv(process.env), { headers: { "Cache-Control": "no-store" } });
}
