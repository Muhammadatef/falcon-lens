import { planShare, type SharePlan } from "@/lib/share";

export const dynamic = "force-dynamic";

/**
 * Web Share Target (app/manifest.ts): the installed PWA receives what a person shares
 * from another app as a multipart POST here. Sharing to Falcon Lens is the request to
 * check, so this route starts the check on the API and answers 303 to `/?id=vd_…`,
 * where the page attaches to the live SSE stream.
 *
 * The only outbound call is to the fixed internal API base (never a URL taken from the
 * shared content), and the redirect target is always a relative path built from a
 * validated verdict id.
 */
const API_BASE = (process.env.FL_API_INTERNAL_URL ?? "http://api:8000").replace(/\/+$/, "");
const MAX_BODY_BYTES = 6 * 1024 * 1024;
const VERDICT_ID_RE = /^vd_[0-9A-HJKMNP-TV-Z]{26}$/;

const seeOther = (location: string) => new Response(null, { status: 303, headers: { Location: location, "Cache-Control": "no-store" } });

async function startCheck(plan: Exclude<SharePlan, { kind: "none" }>, forwardedFor: string | null): Promise<string | null> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (forwardedFor) headers["x-forwarded-for"] = forwardedFor;
  let body: BodyInit;
  if (plan.kind === "url") {
    headers["content-type"] = "application/json";
    body = JSON.stringify({ url: plan.url });
  } else if (plan.kind === "message") {
    headers["content-type"] = "application/json";
    body = JSON.stringify({ text: plan.text });
  } else {
    // The API answers 411 without Content-Length, so the multipart body is serialised first.
    const form = new FormData();
    form.append("file", plan.file, plan.file.name || (plan.kind === "email" ? "shared.eml" : "shared"));
    const encoded = new Response(form);
    headers["content-type"] = encoded.headers.get("content-type") ?? "multipart/form-data";
    body = await encoded.arrayBuffer();
  }
  try {
    const response = await fetch(`${API_BASE}/v1/check/${plan.kind}`, { method: "POST", headers, body, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!response.ok) return null;
    const data = (await response.json()) as { verdict_id?: unknown };
    return typeof data.verdict_id === "string" && VERDICT_ID_RE.test(data.verdict_id) ? data.verdict_id : null;
  } catch {
    return null;
  }
}

export async function POST(request: Request) {
  const length = Number.parseInt(request.headers.get("content-length") ?? "0", 10);
  if (Number.isFinite(length) && length > MAX_BODY_BYTES) return seeOther("/?share=failed");

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return seeOther("/?share=failed");
  }
  const text = (name: string) => {
    const v = form.get(name);
    return typeof v === "string" ? v : "";
  };
  const files = form.getAll("files").filter((f): f is File => typeof f !== "string" && f.size > 0);
  const plan = planShare({ title: text("title"), text: text("text"), url: text("url"), files });
  if (plan.kind === "none") return seeOther("/");

  const id = await startCheck(plan, request.headers.get("x-forwarded-for"));
  return seeOther(id ? `/?id=${id}` : "/?share=failed");
}

/** GET fallback (older launchers, manual links): pre-fills the box and lets the person confirm. */
export function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const shared = [params.get("url"), params.get("text")].filter((v): v is string => !!v && v.trim() !== "").join(" ").trim().slice(0, 2000);
  return seeOther(shared ? `/?text=${encodeURIComponent(shared)}` : "/");
}
