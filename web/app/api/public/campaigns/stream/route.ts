import { WindowLimiter, filterFrame, visitorKey } from "@/lib/public-campaigns";
import { apiBase, notConnected, upstreamHeaders } from "../shared";

export const dynamic = "force-dynamic";

const opens = new WindowLimiter(12, 60_000);
const perVisitor = new Map<string, number>();
let total = 0;
const MAX_PER_VISITOR = 3;
const MAX_TOTAL = 60;
/** One connection lives at most this long; EventSource reconnects on its own. */
const MAX_LIFETIME_MS = 5 * 60_000;
const KEEPALIVE_MS = 15_000;
const MAX_FRAME_BYTES = 64 * 1024;
const enc = new TextEncoder();

export async function GET(request: Request) {
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
    upstream = await fetch(`${apiBase()}/v1/campaigns/stream`, { headers, cache: "no-store", signal: abort.signal });
  } catch {
    return notConnected(502);
  }
  if (!upstream.ok || !upstream.body) {
    abort.abort();
    return notConnected(upstream.status === 404 ? 404 : 502);
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
            const out = filterFrame(block);
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
}
