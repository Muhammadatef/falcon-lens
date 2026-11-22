/**
 * Minimal Server-Sent Events parser for fetch() streams. Used where EventSource cannot
 * be (it has no way to send an Authorization header, which the operator board needs).
 * Follows the WHATWG event-stream parsing rules for `event`, `data`, `id` and comments.
 */

export interface SseMessage {
  event: string;
  data: string;
  id?: string;
}

export function createSseParser(onMessage: (m: SseMessage) => void): { push(chunk: string): void } {
  let buffer = "";
  let event = "";
  let data: string[] = [];
  let id: string | undefined;

  const dispatch = () => {
    if (data.length > 0) onMessage({ event: event || "message", data: data.join("\n"), id });
    event = "";
    data = [];
  };

  const line = (raw: string) => {
    if (raw === "") return dispatch();
    if (raw.startsWith(":")) return;
    const colon = raw.indexOf(":");
    const field = colon === -1 ? raw : raw.slice(0, colon);
    let value = colon === -1 ? "" : raw.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else if (field === "id") id = value;
  };

  return {
    push(chunk: string) {
      buffer += chunk;
      let match: RegExpExecArray | null;
      const eol = /\r\n|\n|\r/g;
      let start = 0;
      while ((match = eol.exec(buffer)) !== null) {
        // A lone "\r" at the very end may be the first half of "\r\n": wait for more.
        if (match[0] === "\r" && match.index === buffer.length - 1) break;
        line(buffer.slice(start, match.index));
        start = match.index + match[0].length;
      }
      buffer = buffer.slice(start);
    },
  };
}

/** Reads an SSE response body until it ends or the signal aborts. */
export async function readSse(response: Response, onMessage: (m: SseMessage) => void, signal?: AbortSignal): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser(onMessage);
  try {
    for (;;) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}
