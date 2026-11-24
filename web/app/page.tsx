import { CheckExperience } from "@/components/CheckExperience";
import { loadCapabilities } from "@/lib/capabilities";
import { VERDICT_ID_RE } from "@/lib/contracts";
import "./voice/voice.css";
import { translate } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";
import type { Metadata } from "next";

type Search = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));

/** Title and description use the eyebrow: "two AI agents against scams". */
export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: translate(lang, "home.eyebrow"), description: `${translate(lang, "home.eyebrow")}. ${translate(lang, "home.sub.phone")}` });
}

/**
 * `/`            paste box
 * `/?id=vd_…`    attaches to a running or finished check (shareable, reload-proof)
 * `/?text=…`     box pre-filled by the GET share fallback; never auto-submitted
 * `/?demo=1`     adds the labelled demo examples and the DEMO DATA ribbon
 */
export default async function Home({ searchParams }: { searchParams: Search }) {
  const params = await searchParams;
  const id = one(params.id);
  const caps = await loadCapabilities();
  return (
    <CheckExperience
      demo={one(params.demo) === "1"}
      initialId={VERDICT_ID_RE.test(id) ? id : null}
      initialText={one(params.text).slice(0, 8000)}
      pendingKinds={[...(caps.message_check ? [] : ["message" as const]), ...(caps.email_check ? [] : ["email" as const]), ...(caps.image_check ? [] : ["image" as const])]}
      investigatorLive={caps.investigator}
      sentinelLive={caps.sentinel_agent}
      shareFailed={one(params.share) === "failed"}
    />
  );
}
