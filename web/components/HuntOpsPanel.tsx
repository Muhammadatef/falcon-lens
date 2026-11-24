"use client";

import { useEffect, useState } from "react";
import { getHuntAdmin, putHuntPaused, type HuntAdmin } from "@/lib/hunt";
import { formatTime, type MessageKey } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { SourceBadge } from "./Chrome";

/** Operator-only hunting panel on /ops: state, sources, quotas, last cycle, counts, all candidates, pause/resume.
 *  Prescore is shown as a queue priority, never as a risk score. Domains are defanged plain text. */
export function HuntOpsPanel({ operatorKey }: { operatorKey: string }) {
  const { t, lang } = usePrefs();
  const [admin, setAdmin] = useState<HuntAdmin | null>(null);
  const [msg, setMsg] = useState<"" | "saved" | "failed" | "denied">("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    void getHuntAdmin(operatorKey, abort.signal).then(({ status, admin: a }) => {
      if (abort.signal.aborted) return;
      if (a) setAdmin(a);
      else if (status === 401 || status === 403) setMsg("denied");
    });
    return () => abort.abort();
  }, [operatorKey]);

  const toggle = async () => {
    if (!admin) return;
    setBusy(true);
    const { status, admin: a } = await putHuntPaused(operatorKey, !admin.paused);
    setBusy(false);
    if (a) {
      setAdmin(a);
      setMsg("saved");
    } else setMsg(status === 401 || status === 403 ? "denied" : "failed");
  };

  if (!admin && msg !== "denied") return null;
  const state = admin ? (!admin.enabled ? "off" : admin.paused ? "paused" : "on") : null;
  return (
    <section className="card keybox" aria-labelledby="hunt-ops-title" data-testid="hunt-ops-panel">
      <h2 className="h3" id="hunt-ops-title">{t("hunt.ops.title")}</h2>
      {admin && state ? (
        <>
          <p data-testid="hunt-ops-state">
            <strong>{t(`hunt.ops.state.${state}` as MessageKey)}</strong>
            {admin.lastCycleAt ? (
              <>
                {" · "}{t("hunt.ops.last")}: <time dateTime={admin.lastCycleAt}>{formatTime(lang, admin.lastCycleAt, true)}</time>
                {admin.lastOutcome ? <span className="mono"> ({admin.lastOutcome})</span> : null}
              </>
            ) : null}
          </p>
          <p className="small" data-testid="hunt-ops-quota">
            {t("hunt.ops.quota", { h: admin.quota.perHour, d: admin.quota.perDay })} · {t("hunt.ops.min", { n: admin.prescoreMin })}
          </p>
          <div className="camp-stats" data-testid="hunt-ops-sources">
            {admin.sources.map((s) => (
              <span key={s.id} className={s.status === "live" ? "pill pill--live" : "pill"} data-status={s.status}>
                {t(`hunt.src.${s.id}` as MessageKey)} · {t(`hunt.status.${s.status}` as MessageKey)}
              </span>
            ))}
          </div>
          <div className="camp-stats" data-testid="hunt-ops-counts">
            {Object.entries(admin.counts).map(([k, n]) => (
              <span key={k} className="pill">{t(`hunt.st.${k}` as MessageKey)}: <b className="mono">{n}</b></span>
            ))}
          </div>
          <div className="keybox-row">
            <button
              className={admin.paused ? "btn btn--sm btn--primary" : "btn btn--sm"}
              type="button"
              disabled={busy || !admin.enabled}
              onClick={() => void toggle()}
              data-testid="hunt-ops-toggle"
            >
              {t(admin.paused ? "hunt.ops.resume" : "hunt.ops.pause")}
            </button>
          </div>
          {admin.items.length === 0 ? (
            <p className="small muted" data-testid="hunt-ops-none">{t("hunt.ops.none")}</p>
          ) : (
            <div className="table-wrap">
              <table className="small" data-testid="hunt-ops-table">
                <thead>
                  <tr>
                    <th scope="col">{t("hunt.ops.domain")}</th>
                    <th scope="col">{t("hunt.ops.status")}</th>
                    <th scope="col">{t("hunt.ops.prescore")}</th>
                    <th scope="col">{t("hunt.first")}</th>
                  </tr>
                </thead>
                <tbody>
                  {admin.items.slice(0, 100).map((r) => (
                    <tr key={r.id} data-testid="hunt-ops-row">
                      <td><code className="mono" dir="ltr" translate="no">{r.domain}</code> <SourceBadge source={r.source === "fixture" || r.source === "replay" ? r.source : "live"} /></td>
                      <td>{t(`hunt.st.${r.status}` as MessageKey)}</td>
                      <td className="mono">{r.prescore}</td>
                      <td><time dateTime={r.firstSeen}>{formatTime(lang, r.firstSeen, true)}</time></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
      {msg ? <p className="small" role="status" data-testid="hunt-ops-msg">{t(`hunt.ops.msg.${msg}` as MessageKey)}</p> : null}
    </section>
  );
}
