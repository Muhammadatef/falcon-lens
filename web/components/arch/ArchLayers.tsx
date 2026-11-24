import type { Lang } from "@/lib/contracts";
import { Icon, type IconName } from "@/components/Icon";
import { LAYERS, LAYERS_UI, LAYER_LINKS, type Layer, type LayerGroup } from "@/lib/arch-layers";

const LAYER_ICON: Record<Layer["id"], IconName> = { voice: "mic", agents: "spark", platform: "box" };

function Group({ group, lang, ui, solo }: { group: LayerGroup; lang: Lang; ui: (typeof LAYERS_UI)[Lang]; solo: boolean }) {
  const List = group.ordered ? "ol" : "ul";
  return (
    <div className="al-group" data-tone={group.tone} data-testid={`al-group-${group.id}`}>
      {solo ? null : (
        <div className="al-group-head">
          <h3>{group[lang].t}</h3>
          <p>{group[lang].d}</p>
        </div>
      )}
      <List className="al-steps" data-ordered={group.ordered} aria-label={solo ? (group.ordered ? ui.stepsLabel : ui.partsLabel) : group[lang].t}>
        {group.steps.map((step, i) => (
          <li key={step.id} className="al-step" data-testid="al-step">
            {group.ordered ? <span className="al-step-n" aria-hidden="true">{i + 1}</span> : null}
            <span className="al-step-body">
              <b>{step[lang].t}</b>
              <span>{step[lang].d}</span>
            </span>
          </li>
        ))}
      </List>
    </div>
  );
}

/**
 * The architecture as three stacked layers: voice assistant, the two AI agents, platform. Server-rendered, no script:
 * each layer is a native <details> (keyboard and screen-reader friendly), the links between layers carry a label,
 * and the only motion is a small dot travelling down each link (off under prefers-reduced-motion).
 */
export function ArchLayers({ lang, heading = "h2" }: { lang: Lang; heading?: "h2" | "h3" }) {
  const ui = LAYERS_UI[lang];
  const Heading = heading;
  return (
    <section className="al" aria-labelledby="al-h" data-testid="arch-layers">
      <div className="sec-head"><Heading id="al-h">{ui.title}</Heading></div>
      <p className="muted al-lead">{ui.lead}</p>
      <ol className="al-stack" aria-label={ui.flow}>
        {LAYERS.map((layer, index) => {
          const link = LAYER_LINKS.find((l) => l.after === layer.id);
          return (
            <li key={layer.id} className="al-row">
              <details className="al-layer" data-layer={layer.id} data-testid={`al-layer-${layer.id}`} open>
                <summary>
                  <span className="al-num" aria-hidden="true">{index + 1}</span>
                  <Icon name={LAYER_ICON[layer.id]} size={26} />
                  <span className="al-title">
                    <strong>{layer[lang].t}</strong>
                    <small lang={ui.other} dir={ui.other === "ar" ? "rtl" : "ltr"}>{layer[ui.other].t}</small>
                  </span>
                  <span className="al-sum">{layer[lang].d}</span>
                  <span className="al-chev" aria-hidden="true" />
                </summary>
                <div className="al-body" data-groups={layer.groups.length}>
                  {layer.groups.map((group) => <Group key={group.id} group={group} lang={lang} ui={ui} solo={layer.groups.length === 1} />)}
                </div>
              </details>
              {link ? (
                <p className="al-link" data-testid="al-link">
                  <span className="al-link-rail" aria-hidden="true"><span className="al-link-dot" /></span>
                  <span className="al-link-text">{link[lang]}</span>
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
