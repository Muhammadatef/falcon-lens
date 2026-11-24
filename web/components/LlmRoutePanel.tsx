"use client";

import { useEffect, useState } from "react";
import { getLlmRoute, putLlmRoute, type LlmRoute, type RouteMode } from "@/lib/llm-route";
import { usePrefs } from "@/lib/prefs";

/** Operator-only "AI model route" panel: shows the active route and local model, and switches them. */
export function LlmRoutePanel({ operatorKey }: { operatorKey: string }) {
  const { t } = usePrefs();
  const [route, setRoute] = useState<LlmRoute | null>(null);
  const [mode, setMode] = useState<RouteMode>("auto");
  const [model, setModel] = useState("");
  const [msg, setMsg] = useState<"" | "saved" | "failed" | "denied">("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    void getLlmRoute(operatorKey, abort.signal).then(({ status, route: r }) => {
      if (abort.signal.aborted) return;
      if (r) {
        setRoute(r);
        setMode(r.mode);
        setModel(r.local_model);
      } else if (status === 401 || status === 403) setMsg("denied");
    });
    return () => abort.abort();
  }, [operatorKey]);

  const save = async () => {
    setBusy(true);
    const { status, route: r } = await putLlmRoute(operatorKey, mode, model || null);
    setBusy(false);
    if (r) {
      setRoute(r);
      setMsg("saved");
    } else setMsg(status === 401 || status === 403 ? "denied" : "failed");
  };

  if (!route && msg !== "denied") return null;
  return (
    <section className="card keybox" aria-labelledby="route-title" data-testid="llm-route-panel">
      <h2 className="h3" id="route-title">{t("ops.route.title")}</h2>
      {route ? (
        <>
          <p data-testid="route-current">
            {t("ops.route.current")}: <strong data-testid="route-effective">{t(`ops.route.mode.${route.effective_mode}`)}</strong>
            {" · "}
            {t("ops.route.model")}: <strong className="mono" dir="ltr" data-testid="route-model">{route.local_model}</strong>
          </p>
          <div className="keybox-row">
            <label htmlFor="route-mode" className="small">{t("ops.route.select")}</label>
            <select id="route-mode" value={mode} disabled={route.sovereign_locked} onChange={(e) => setMode(e.target.value as RouteMode)} data-testid="route-select">
              {route.modes.map((m) => <option key={m} value={m}>{t(`ops.route.mode.${m}`)}</option>)}
            </select>
            <label htmlFor="route-model" className="small">{t("ops.route.model")}</label>
            <select id="route-model" dir="ltr" value={model} onChange={(e) => setModel(e.target.value)} data-testid="route-model-select">
              {route.local_models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <button className="btn btn--sm btn--primary" type="button" disabled={busy || route.sovereign_locked} onClick={() => void save()} data-testid="route-save">{t("ops.route.save")}</button>
          </div>
          {route.sovereign_locked ? <p className="small" data-testid="route-locked">{t("ops.route.locked")}</p> : null}
          {!route.cloud_available ? <p className="small">{t("ops.route.nokey")}</p> : null}
          <p className="small" data-testid="route-note">{t("ops.route.note")}</p>
        </>
      ) : null}
      {msg ? <p className="small" role="status" data-testid="route-msg">{t(`ops.route.msg.${msg}`)}</p> : null}
    </section>
  );
}
