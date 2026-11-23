import { looksLikeSingleUrl } from "./defang";

/** Decides which check a share-target payload starts. Pure, unit-tested. */
export type SharePlan =
  | { kind: "url"; url: string }
  | { kind: "message"; text: string }
  | { kind: "image"; file: File }
  | { kind: "email"; file: File }
  | { kind: "none" };

export interface SharePayload {
  title: string;
  text: string;
  url: string;
  files: File[];
}

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_EMAIL_BYTES = 2 * 1024 * 1024;

export function planShare({ title, text, url, files }: SharePayload): SharePlan {
  const image = files.find((f) => IMAGE_TYPES.has(f.type) && f.size <= MAX_IMAGE_BYTES);
  if (image) return { kind: "image", file: image };
  const email = files.find((f) => (f.type === "message/rfc822" || f.name.toLowerCase().endsWith(".eml")) && f.size <= MAX_EMAIL_BYTES);
  if (email) return { kind: "email", file: email };

  const sharedUrl = url.trim();
  const sharedText = text.trim();
  // Android apps usually put the link in `text`; a lone link is a URL check.
  if (sharedUrl && (!sharedText || sharedText === sharedUrl) && looksLikeSingleUrl(sharedUrl)) return { kind: "url", url: sharedUrl.slice(0, 4096) };
  if (!sharedUrl && looksLikeSingleUrl(sharedText)) return { kind: "url", url: sharedText.slice(0, 4096) };

  // Text with or without a link is a message check; the pipeline extracts and checks the links itself.
  const parts = [sharedText, sharedUrl && !sharedText.includes(sharedUrl) ? sharedUrl : ""].filter(Boolean);
  const message = (parts.length > 0 ? parts.join("\n") : title.trim()).slice(0, 8000);
  return message ? { kind: "message", text: message } : { kind: "none" };
}
