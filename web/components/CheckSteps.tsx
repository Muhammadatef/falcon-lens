"use client";

import { useEffect, useState } from "react";
import { TIERS, type Verdict } from "@/lib/contracts";
import { tierFindingLines } from "@/lib/findings";
import { usePrefs } from "@/lib/prefs";

/** The finding lines of one tier (React text nodes only: nothing here is ever parsed as markup). */
export function FoundList({ lines, testid }: { lines: readonly string[]; testid: string }) {
  const { t } = usePrefs();
  return (
    <ul className="ck-found" data-testid={testid}>
      {(lines.length ? lines : [t("steps.none")]).map((l) => (
        <li key={l}>{l}</li>
      ))}
    </ul>
  );
}

/**
 * Progressive steps of THIS check: each layer that has run lists up to three of its strongest findings, with their
 * values (age in days, brand, defanged host), from the evidence of the run. Layers appear as the verdict stream reaches them.
 * A layer that ran with nothing to report says "nothing notable", never "skipped".
 */
export function CheckSteps({ verdict: v }: { verdict: Verdict }) {
  const { t, lang } = usePrefs();
  const reached = TIERS.indexOf(v.tier_reached);
  // Layers appear strictly in order, one every ~320 ms, even when several arrive in one burst (T0, T1, T2, never out of order).
  const [shown, setShown] = useState(0);
  const want = Math.min(reached + 1, 3);
  useEffect(() => {
    if (shown >= want) return;
    const id = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 0 : 320);
    return () => window.clearTimeout(id);
  }, [shown, want]);
  const brand = v.impersonated_brand?.brand_id ?? null;
  return (
    <section className="wrap ck-steps" aria-labelledby="ck-steps-h" data-testid="check-steps">
      <h2 className="h3" id="ck-steps-h">{t("steps.h")}</h2>
      <ol>
        {TIERS.filter((tier, i) => i < shown && tier !== "T3").map((tier) => (
          <li key={tier} data-tier={tier} data-testid="check-step" data-order={TIERS.indexOf(tier) + 1}>
            <strong>{t(`tier.${tier}`)}</strong>
            <FoundList lines={tierFindingLines(v.evidence, tier, lang, brand)} testid="check-step-found" />
          </li>
        ))}
      </ol>
    </section>
  );
}
