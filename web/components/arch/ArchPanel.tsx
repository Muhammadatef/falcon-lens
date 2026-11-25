"use client";

import Link from "next/link";
import type { RefObject } from "react";
import { CapBadge } from "@/components/CapBadge";
import { NODE_BY_ID, relatedOf, type GroupId } from "@/lib/arch-graph";
import type { Lang } from "@/lib/contracts";
import { at, NODE_TEXT, TOOL_IO, type ArchKey } from "@/lib/i18n-arch";

export const REPO_BLOB = "https://github.com/Muhammadatef/falcon-lens/blob/main/";
const isTool = (group: GroupId) => group === "tools_inv" || group === "tools_sen";

/**
 * The detail panel of one architecture node (side panel; a bottom sheet under 720 px). Shared by the lane diagram
 * (ArchDiagram) and the animated diagrams (FlowDiagram). The caller owns the open state, Esc and focus return.
 */
export function ArchPanel({ id, lang, caps, view, visible, onClose, onOpen, closeRef }: {
  id: string;
  lang: Lang;
  caps: Record<string, boolean>;
  view: "full" | "biz";
  /** Related nodes are limited to these ids when given. */
  visible?: ReadonlySet<string>;
  onClose: () => void;
  onOpen: (id: string) => void;
  closeRef: RefObject<HTMLButtonElement | null>;
}) {
  const def = NODE_BY_ID.get(id);
  const text = NODE_TEXT[lang][id];
  if (!def || !text) return null;
  const t = (key: ArchKey, vars?: Record<string, string | number>) => at(lang, key, vars);
  const io = TOOL_IO[id];
  const slug = def.doc;
  return (
    <>
      <div className="ap-scrim" aria-hidden="true" onClick={onClose} />
      <div className="ap" role="dialog" aria-modal="false" aria-labelledby="ap-title" data-testid="arch-panel" data-node={id} data-kind={def.kind}>
        <header className="ap-head">
          <div>
            <span className="ap-kind">{t(`arch.kind.${def.kind}` as ArchKey)}</span>
            <h2 id="ap-title" className={isTool(def.group) ? "mono" : undefined}>{text.name}</h2>
            <CapBadge live={caps[def.cap] === true} lang={lang} />
          </div>
          <button type="button" ref={closeRef} className="ap-close" onClick={onClose} aria-label={t("arch.panel.close")} data-testid="arch-panel-close">
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <div className="ap-body">
          <section>
            <h3>{t("arch.panel.what")}</h3>
            <p>{text.plain}</p>
            {view === "full" ? <p className="ap-tech">{text.tech}</p> : null}
          </section>
          <section>
            <h3>{t("arch.panel.why")}</h3>
            <p>{text.why}</p>
          </section>
          <section className="ap-never">
            <h3>{t("arch.panel.never")}</h3>
            <p>{text.never}</p>
          </section>
          {view === "full" ? (
            <>
              {io?.mode ? (
                <section>
                  <h3>{t("arch.panel.mode")}</h3>
                  <p>{t(`arch.mode.${io.mode}` as ArchKey)}</p>
                </section>
              ) : null}
              <section>
                <h3>{t("arch.panel.inputs")}</h3>
                {io ? <p className="mono ap-io">{io.inputs}</p> : <p>{text.inputs}</p>}
              </section>
              <section>
                <h3>{t("arch.panel.outputs")}</h3>
                {io ? <p className="mono ap-io">{io.outputs}</p> : <p>{text.outputs}</p>}
                {io?.budgetMs ? <p className="faint">{t("arch.panel.budget")}: <span className="mono">{io.budgetMs} {t("arch.panel.ms")}</span></p> : null}
              </section>
              <section>
                <h3>{t("arch.panel.code")}</h3>
                {/* One plain link for engineers; raw repository paths are not shown on the page. */}
                <p>{[def.repo].map((src) => <a key={src} className="ap-link" href={REPO_BLOB + src} rel="noopener noreferrer" target="_blank" data-testid="arch-code-link">{t("arch.code.link")}</a>)}</p>
              </section>
            </>
          ) : null}
          <section>
            <h3>{t("arch.panel.docs")}</h3>
            <p>
              <Link href={`/docs/${slug}`} className="ap-link">{t("arch.docs.link")}</Link>
            </p>
          </section>
          <section>
            <h3>{t("arch.panel.related")}</h3>
            <ul className="ap-rel">
              {relatedOf(def.id, visible).map((rid) => (
                <li key={rid}>
                  <button type="button" className="ap-rel-btn" onClick={() => onOpen(rid)} data-testid={`arch-rel-${rid}`}>
                    {NODE_TEXT[lang][rid]!.name}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </>
  );
}
