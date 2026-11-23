import type { Lang } from "@/lib/contracts";
import { translate } from "@/lib/i18n";
import { CapBadge } from "./CapBadge";
import { Radar } from "./Radar";

/** The Investigator's glyph: a small lens (aperture ring + pupil). Decorative. */
export function LensGlyph() {
  return (
    <svg className="lens-glyph" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <circle className="lg-ring" cx="24" cy="24" r="20" />
      <path className="lg-arc" d="M24 4a20 20 0 0 1 20 20" />
      <path className="lg-blade" d="M24 12l9 5v10l-9 5-9-5V17z" />
      <circle className="lg-pupil" cx="24" cy="24" r="4" />
    </svg>
  );
}

export type AgentId = "inv" | "sen";

/**
 * One of the two AI agents, named. `variant="chip"` is the phone card under the promise line;
 * `variant="tag"` is the desktop name tag on the lens + radar composition.
 * Every badge comes from a capability flag: the Investigator's "AI second look" from `investigator`,
 * the Sentinel from `sentinel_agent`. The Investigator itself (link checking) carries no hand-set badge.
 */
export function AgentChip({ agent, lang, aiLive, sentinelLive, variant }: { agent: AgentId; lang: Lang; aiLive: boolean; sentinelLive: boolean; variant: "chip" | "tag" }) {
  const t = (key: Parameters<typeof translate>[1]) => translate(lang, key);
  return (
    <div className="agent-chip" data-agent={agent} data-variant={variant} data-testid={`agent-${variant}-${agent}`}>
      <span className="agent-chip-glyph">{agent === "inv" ? <LensGlyph /> : <Radar mini />}</span>
      <div className="agent-chip-body">
        <b className="agent-chip-name">{t(agent === "inv" ? "agent.inv.name" : "agent.sen.name")}</b>
        <span className="agent-chip-kind">{t("agent.kind")}</span>
        <span className="agent-chip-role">{t(agent === "inv" ? "agent.inv.role" : "agent.sen.role")}</span>
        {agent === "inv" ? (
          <span className="agent-chip-ai">
            <span>{t("agent.inv.aistep")}</span>
            <CapBadge live={aiLive} lang={lang} />
          </span>
        ) : (
          <span className="agent-chip-ai">
            <CapBadge live={sentinelLive} lang={lang} />
          </span>
        )}
      </div>
    </div>
  );
}
