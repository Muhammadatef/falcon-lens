import type { Lang } from "@/lib/contracts";
import { VOICE_DOC } from "@/lib/voice-doc";

/** The voice path steps for /docs/agents (rendered inside VoiceAgentsSection): sequenced, and static under reduced motion. */
export function VoiceDoc({ lang }: { lang: Lang }) {
  const c = VOICE_DOC[lang];
  return (
    <>
      <p>{c.lead}</p>
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
    </>
  );
}
