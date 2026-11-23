"use client";

import { TIERS, type Tier } from "@/lib/contracts";
import { usePrefs } from "@/lib/prefs";
import { useDt } from "@/lib/use-dt";
import type { CheckState, TierStatus } from "@/lib/verdict-stream";
import { CapBadge } from "./CapBadge";
import { Icon } from "./Icon";

const STEP_KEY = { T0: "act.step.known", T1: "act.step.address", T2: "act.step.visit", T3: "act.step.ai" } as const satisfies Record<Tier, string>;
const STATE_KEY = { done: "act.st.done", running: "act.st.running", pending: "act.st.pending", skipped: "act.st.skipped" } as const satisfies Record<TierStatus, string>;

/**
 * "The Investigator is checking…" card: the four tiers under plain names, one word of state each.
 * No tier code appears here; those live in Technical details. The AI second look carries its own
 * In-progress badge while the `investigator` flag is false (the badge is driven by the flag only).
 */
export function AgentActivity({ state, investigatorLive, sentinelLive }: { state: CheckState; investigatorLive: boolean; sentinelLive: boolean }) {
  const { lang } = usePrefs();
  const d = useDt();
  const v = state.verdict;
  const final = state.phase === "final" && v?.final === true;
  const title = final && v ? d("act.done", { latency_s: (v.latency_ms / 1000).toFixed(1) }) : d("act.title");
  return (
    <div className="activity" data-testid="activity" data-final={final ? "true" : "false"}>
      <div className="activity-head">
        <Icon name="eye" size={24} />
        <h3 className="h3" data-testid="activity-title">{title}</h3>
      </div>
      <ol className="act-steps" aria-label={d("act.steps")} data-testid="act-steps">
        {TIERS.map((tier) => {
          const status = state.tiers[tier];
          return (
            <li key={tier} className="act-step" data-status={status} data-step={tier === "T3" ? "ai" : tier} data-testid={`act-step-${tier}`}>
              <span className="act-dot" aria-hidden="true" />
              <div className="act-text">
                <span>{d(STEP_KEY[tier])}</span>
                {tier === "T3" && !investigatorLive ? <CapBadge live={false} lang={lang} /> : null}
              </div>
              <span className="act-state">{d(STATE_KEY[status])}</span>
            </li>
          );
        })}
      </ol>
      {!final ? <p className="act-wait" data-testid="act-wait">{d("act.wait")}</p> : null}
      <p className="act-sentinel" data-testid="act-sentinel">
        <Icon name="flag" size={20} />
        <span>{d("act.sentinel")}</span>
        <CapBadge live={sentinelLive} lang={lang} />
      </p>
      {final ? <span className="act-handoff" aria-hidden="true" /> : null}
    </div>
  );
}
