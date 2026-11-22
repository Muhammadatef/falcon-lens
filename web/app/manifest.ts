import type { MetadataRoute } from "next";

/**
 * PWA manifest. `share_target` (Android Chrome, installed PWA) posts shared text, links
 * and screenshots to /share, which starts the check. Shape per MDN "share_target".
 * iOS has no share target support (WebKit bug 194593): paste box there.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "عدسة الصقر | Falcon Lens",
    short_name: "عدسة الصقر",
    description: "افحص الروابط والرسائل المشبوهة قبل أن تتفاعل معها.",
    lang: "ar",
    dir: "rtl",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#070b14",
    theme_color: "#070b14",
    categories: ["security", "utilities"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    share_target: {
      action: "/share",
      method: "POST",
      enctype: "multipart/form-data",
      params: {
        title: "title",
        text: "text",
        url: "url",
        files: [{ name: "files", accept: ["image/png", "image/jpeg", "image/webp", "message/rfc822", ".png", ".jpg", ".jpeg", ".webp", ".eml"] }],
      },
    },
  };
}
