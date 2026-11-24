"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { cx, type CxKey } from "@/lib/i18n-campaigns";
import { usePrefs } from "@/lib/prefs";
import { Icon, type IconName } from "./Icon";

const WHY: { icon: IconName; h: CxKey; b: CxKey }[] = [
  { icon: "eye", h: "cx.why.res.h", b: "cx.why.res" },
  { icon: "scale", h: "cx.why.auth.h", b: "cx.why.auth" },
  { icon: "keep", h: "cx.why.safe.h", b: "cx.why.safe" },
];
const STEPS: { icon: IconName; k: CxKey }[] = [
  { icon: "url", k: "cx.how.1" },
  { icon: "spark", k: "cx.how.2" },
  { icon: "list", k: "cx.how.3" },
  { icon: "hand", k: "cx.how.4" },
];
const READ: CxKey[] = ["cx.read.title", "cx.read.count", "cx.read.seen", "cx.read.sev", "cx.read.bars", "cx.read.source", "cx.read.advice"];

/** Compact intro plus a collapsed "How this works" panel, so the live board stays above the fold. */
export function CampaignExplainer() {
  const { lang } = usePrefs();
  const [open, setOpen] = useState(false);
  const panel = useId();
  const c = (k: CxKey) => cx(lang, k);
  return (
    <div className="cx" data-testid="campaign-explainer">
      <p className="cx-intro">{c("cx.intro")}</p>
      <button type="button" className="btn cx-toggle" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((v) => !v)} data-testid="cx-toggle">
        <Icon name="list" size={20} />
        <span>{c("cx.toggle")}</span>
        <small>{c("cx.toggle.hint")}</small>
      </button>
      <div id={panel} role="region" aria-label={c("cx.region")} hidden={!open} className="cx-panel card" data-testid="cx-panel">
        <h2 className="h3">{c("cx.why.h")}</h2>
        <ul className="cx-why">
          {WHY.map((w) => (
            <li key={w.h}>
              <Icon name={w.icon} size={24} />
              <h3>{c(w.h)}</h3>
              <p>{c(w.b)}</p>
            </li>
          ))}
        </ul>
        <h2 className="h3">{c("cx.how.h")}</h2>
        <ol className="cx-steps">
          {STEPS.map((s, i) => (
            <li key={s.k}><span className="cx-n" aria-hidden="true">{i + 1}</span><Icon name={s.icon} size={24} /><p>{c(s.k)}</p></li>
          ))}
        </ol>
        <h2 className="h3">{c("cx.read.h")}</h2>
        <ul className="cx-read">
          {READ.map((k) => <li key={k}>{c(k)}</li>)}
        </ul>
        <p className="small muted cx-note">{c("cx.note")}</p>
        {open ? <Link className="cx-more" href="/docs/agents">{c("cx.more")}</Link> : null}
      </div>
    </div>
  );
}
