import { CheckExperience } from "@/components/CheckExperience";
import { VERDICT_ID_RE } from "@/lib/contracts";

type Search = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));

/**
 * `/`            paste box
 * `/?id=vd_…`    attaches to a running or finished check (shareable, reload-proof)
 * `/?text=…`     box pre-filled by the GET share fallback; never auto-submitted
 * `/?demo=1`     adds the labelled demo examples and the DEMO DATA ribbon
 */
export default async function Home({ searchParams }: { searchParams: Search }) {
  const params = await searchParams;
  const id = one(params.id);
  return (
    <CheckExperience
      demo={one(params.demo) === "1"}
      initialId={VERDICT_ID_RE.test(id) ? id : null}
      initialText={one(params.text).slice(0, 8000)}
      shareFailed={one(params.share) === "failed"}
    />
  );
}
