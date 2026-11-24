import { lstat, readFile, realpath } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

/**
 * Serves /voice/<lang>/<file> (rewritten here by next.config.ts).
 * Looks first in the private clips dir (FL_VOICE_CLIPS_DIR, default /data/private/voice/clips: macOS and
 * cloned-voice clips that must not be committed), then falls back to the committed public/voice files.
 * Read-only, whitelisted names, path-traversal safe.
 */
const LANGS = new Set(["ar_ae", "en"]);
const NAME = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,120}$/;
const TYPES: Record<string, string> = {
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".json": "application/json; charset=utf-8",
};

export function safeJoin(root: string, lang: string, file: string): string | null {
  if (!LANGS.has(lang) || !NAME.test(file) || file.includes("..")) return null;
  if (!TYPES[path.extname(file)]) return null;
  const base = path.resolve(root, lang);
  const full = path.resolve(base, file);
  return full.startsWith(base + path.sep) ? full : null;
}

/** Reads a regular, non-symlink file whose real path stays inside the real path of its base dir. */
export async function readClip(root: string, lang: string, file: string): Promise<Buffer | null> {
  const p = safeJoin(root, lang, file);
  if (!p) return null;
  try {
    const st = await lstat(/*turbopackIgnore: true*/ p);
    if (st.isSymbolicLink() || !st.isFile()) return null;
    const [realBase, realFile] = await Promise.all([realpath(/*turbopackIgnore: true*/ root).then((r) => path.join(r, lang)), realpath(/*turbopackIgnore: true*/ p)]);
    if (!realFile.startsWith(realBase + path.sep)) return null;
    return await readFile(/*turbopackIgnore: true*/ realFile);
  } catch {
    return null;
  }
}

export async function GET(_req: Request, ctx: { params: Promise<{ lang: string; file: string }> }) {
  const { lang, file } = await ctx.params;
  const privateRoot = process.env.FL_VOICE_CLIPS_DIR ?? "/data/private/voice/clips";
  const publicRoot = path.join(process.cwd(), "public", "voice");
  for (const root of [privateRoot, publicRoot]) {
    const body = await readClip(root, lang, file);
    if (body) {
      const manifest = file === "manifest.json";
      return new Response(new Uint8Array(body), {
        headers: {
          "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream",
          // the manifest is revalidated; audio is cached for a day (regenerated clips keep their id)
          "Cache-Control": manifest ? "no-cache" : "public, max-age=86400",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }
  }
  return new Response("not found", { status: 404 });
}
