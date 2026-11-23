import type { Metadata } from "next";
import type { Lang } from "./contracts";

export const SITE = {
  ar: { name: "عدسة الصقر | Falcon Lens", description: "افحص الروابط والرسائل والبريد المشبوه قبل أن تتفاعل معها، واحصل على حكم واضح مدعوم بالأدلة خلال ثوانٍ. مشروع مستقل." },
  en: { name: "Falcon Lens | عدسة الصقر", description: "Check suspicious links, messages and emails before you act, and get a clear evidence-backed verdict in seconds. An independent project." },
} as const;

export const metadataBase = (): URL => {
  try {
    return new URL(process.env.FL_PUBLIC_BASE_URL ?? "https://localhost:8443");
  } catch {
    return new URL("https://localhost:8443");
  }
};

/** Title, description and Open Graph for a page in the reader's language. No third-party assets. */
export function pageMetadata(lang: Lang, page?: { title: string; description?: string }): Metadata {
  const site = SITE[lang];
  const title = page ? `${page.title} · ${site.name}` : site.name;
  const description = page?.description ?? site.description;
  return {
    title,
    description,
    openGraph: {
      type: "website",
      siteName: site.name,
      title,
      description,
      locale: lang === "ar" ? "ar_AE" : "en_GB",
      alternateLocale: lang === "ar" ? ["en_GB"] : ["ar_AE"],
      images: [{ url: "/og/falcon-lens-og.png", width: 1200, height: 630, alt: site.name }],
    },
    twitter: { card: "summary_large_image", title, description, images: ["/og/falcon-lens-og.png"] },
  };
}
