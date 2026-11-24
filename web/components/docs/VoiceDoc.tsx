import Link from "next/link";
import type { Lang } from "@/lib/contracts";
import { VOICE_DOC } from "@/lib/voice-doc";

/** The voice path of /docs/agents: an ordered, sequenced diagram (steps light up one after another; static under reduced motion). */
export function VoiceDoc({ lang }: { lang: Lang }) {
  const c = VOICE_DOC[lang];
  return (
    <section className="voice-doc" aria-labelledby="voice-doc-h" data-testid="voice-doc" id="voice">
      <div className="sec-head"><h2 id="voice-doc-h">{c.title}</h2></div>
      <p className="page-lead">{c.lead}</p>
      <ol className="vflow" aria-label={c.stepsLabel} data-testid="voice-flow">
        {c.steps.map((s) => (
          <li className="vflow-step" key={s.tag}>
            <span className="vflow-tag mono" dir="ltr">{s.tag}</span>
            <div>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="prose">
        <h3>{c.limitsTitle}</h3>
        <ul>{c.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
      <p><Link className="btn" href="/">{c.tryLabel}</Link></p>
    </section>
  );
}
