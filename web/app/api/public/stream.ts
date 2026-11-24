import { WindowLimiter, visitorKey } from "@/lib/public-campaigns";
import { filterFrameWith } from "@/lib/public-history";
import { apiBase, notConnected, upstreamHeaders } from "./campaigns/shared";

const MAX_PER_VISITOR = 3;
const MAX_TOTAL = 60;
/** One connection lives at most this long; EventSource reconnects on its own. */
const MAX_LIFETIME_MS = 5 * 60_000;
const KEEPALIVE_MS = 15_000;
const MAX_FRAME_BYTES = 64 * 1024;
const enc = new TextEncoder();

/**
 * Bounded, filtered SSE relay for the public history: per-visitor open-rate limit, per-visitor and global
 * connection caps, a 5 minute lifetime, keep-alives, and every frame re-projected through `project`.
 */
export function publicStream(upstreamPath: string, event: string, project: (raw: unknown) => unknown) {
  const opens = new WindowLimiter(12, 60_000);
  const perVisitor = new Map<string, number>();
  let total = 0;

  return async function GET(request: Request): Promise<Response> {
    const visitor = visitorKey(request);
    const wait = opens.take(visitor);
    if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });
    if ((perVisitor.get(visitor) ?? 0) >= MAX_PER_VISITOR || total >= MAX_TOTAL) return notConnected(429, { "Retry-After": "10" });
    const headers = upstreamHeaders(request, "text/event-stream");
    if (!headers) return notConnected(503);
    const last = request.headers.get("last-event-id");
    if (last && /^[\w.-]{1,64}$/.test(last)) headers.set("last-event-id", last);

    const abort = new AbortController();
    let upstream: Response;
    try {
      upstream = await fetch(`${apiBase()}${upstreamPath}`, { headers, cache: "no-store", signal: abort.signal });
    } catch {
      return notConnected(502);
    }
    if (!upstream.ok || !upstream.body) {
      abort.abort();
      return notConnected(upstream.status === 404 ? 404 : upstream.status === 429 ? 429 : 502);
    }

    perVisitor.set(visitor, (perVisitor.get(visitor) ?? 0) + 1);
    total += 1;
    const reader = upstream.body.getReader();
    let closed = false;
    let keepalive: ReturnType<typeof setInterval> | undefined;
    let lifetime: ReturnType<typeof setTimeout> | undefined;
    const finish = () => {
      if (closed) return;
      closed = true;
      clearInterval(keepalive);
      clearTimeout(lifetime);
      abort.abort();
      reader.cancel().catch(() => undefined);
      const n = (perVisitor.get(visitor) ?? 1) - 1;
      if (n <= 0) perVisitor.delete(visitor);
      else perVisitor.set(visitor, n);
      total -= 1;
    };

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (s: string) => {
          if (!closed) controller.enqueue(enc.encode(s));
        };
        const end = () => {
          finish();
          try {
            controller.close();
          } catch {
            /* already closed */
          }
        };
        request.signal.addEventListener("abort", end);
        send(": stream open\nretry: 3000\n\n");
        keepalive = setInterval(() => send(": keep-alive\n\n"), KEEPALIVE_MS);
        lifetime = setTimeout(end, MAX_LIFETIME_MS);
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done || closed) break;
            buffer += decoder.decode(value, { stream: true });
            if (buffer.length > MAX_FRAME_BYTES * 2) buffer = buffer.slice(-MAX_FRAME_BYTES);
            let at: number;
            while ((at = buffer.search(/\r?\n\r?\n/)) >= 0) {
              const block = buffer.slice(0, at);
              buffer = buffer.slice(at).replace(/^\r?\n\r?\n/, "");
              if (block.length > MAX_FRAME_BYTES) continue;
              const out = filterFrameWith(block, event, project);
              if (out) send(out);
            }
          }
        } catch {
          /* upstream dropped: close, the browser reconnects */
        }
        end();
      },
      cancel() {
        finish();
      },
    });

    return new Response(stream, {
      headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store, no-transform", Connection: "keep-alive", "X-Accel-Buffering": "no" },
    });
  };
}

/** One-shot JSON GET against the API with the server-only key; the body is passed through `project`. */
export async function publicJson(limiter: WindowLimiter, request: Request, upstreamPath: string, project: (raw: unknown) => unknown): Promise<Response> {
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });
  const headers = upstreamHeaders(request, "application/json");
  if (!headers) return notConnected(503);
  try {
    const upstream = await fetch(`${apiBase()}${upstreamPath}`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) });
    if (upstream.status === 404) return notConnected(404);
    if (upstream.status === 429) return notConnected(429, { "Retry-After": "10" });
    if (!upstream.ok) return notConnected(502);
    const out = project(await upstream.json());
    if (!out) return notConnected(502);
    return Response.json(out, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return notConnected(502);
  }
}
