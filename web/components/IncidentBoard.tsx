"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { authHeaders, decideAction, loadBoard } from "@/lib/api";
import { parseIncident, unwrapList, type ActionStatus, type Incident } from "@/lib/contracts";
import { formatTime, pick, translateMaybe } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { readSse } from "@/lib/sse";
import { DemoRibbon, SourceBadge, UntrustedText } from "./Chrome";
import { Icon, SeverityMark } from "./Icon";

type Load = { state: "loading" } | { state: "not_connected" } | { state: "unauthorized" } | { state: "ok"; items: Incident[] };

const KEY_STORE = "fl_operator_key";

export function upsertIncident(current: Incident[], incoming: Incident): Incident[] {
  const without = current.filter((i) => i.incident_id !== incoming.incident_id);
  return [incoming, ...without].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

const setActionStatus = (items: Incident[], incidentId: string, actionId: string, status: ActionStatus): Incident[] =>
  items.map((i) => (i.incident_id !== incidentId ? i : { ...i, actions: i.actions.map((a) => (a.action_id === actionId ? { ...a, status } : a)) }));

export function IncidentBoard({ demo }: { demo: boolean }) {
  const { t } = usePrefs();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [key, setKey] = useState("");
  const [draftKey, setDraftKey] = useState("");
  const [ready, setReady] = useState(false);
  const [live, setLive] = useState(false);
  const [notice, setNotice] = useState<{ actionId: string; text: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  // The operator key lives in sessionStorage only: gone when the tab closes, never in a cookie or URL.
  useEffect(() => {
    try {
      setKey(window.sessionStorage.getItem(KEY_STORE) ?? "");
    } catch {
      /* storage blocked: key stays in memory */
    }
    setReady(true);
  }, []);

  const saveKey = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = draftKey.trim();
    if (!next) return;
    try {
      window.sessionStorage.setItem(KEY_STORE, next);
    } catch {
      /* in-memory only */
    }
    setKey(next);
    setDraftKey("");
    setLoad({ state: "loading" });
  };
  const forgetKey = () => {
    try {
      window.sessionStorage.removeItem(KEY_STORE);
    } catch {
      /* nothing stored */
    }
    setKey("");
    setLoad({ state: "loading" });
  };

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const abort = new AbortController();

    if (demo) {
      void import("@/lib/demo").then(({ DEMO_INCIDENT }) => {
        if (!cancelled) setLoad({ state: "ok", items: [DEMO_INCIDENT] });
      });
      return () => { cancelled = true; };
    }

    const stream = async () => {
      try {
        const response = await fetch("/v1/incidents/stream", { headers: { ...authHeaders(key || undefined), accept: "text/event-stream" }, credentials: "same-origin", cache: "no-store", signal: abort.signal });
        if (!response.ok || !(response.headers.get("content-type") ?? "").includes("text/event-stream")) return;
        setLive(true);
        await readSse(response, (message) => {
          let raw: unknown;
          try {
            raw = JSON.parse(message.data);
          } catch {
            return;
          }
          const incident = parseIncident(raw);
          if (incident) setLoad((prev) => ({ state: "ok", items: upsertIncident(prev.state === "ok" ? prev.items : [], incident) }));
        }, abort.signal);
      } catch {
        /* aborted or dropped: the list stays, the pill shows "paused" */
      } finally {
        if (!cancelled) setLive(false);
      }
    };

    void (async () => {
      const result = await loadBoard("/v1/incidents", parseIncident, unwrapList, key || undefined, abort.signal);
      if (cancelled) return;
      if (result.state === "unauthorized") return setLoad({ state: "unauthorized" });
      if (result.state !== "ok") return setLoad({ state: "not_connected" });
      setLoad({ state: "ok", items: [...result.items].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) });
      void stream();
    })();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [demo, key, ready, attempt]);

  const decide = useCallback(
    async (incidentId: string, actionId: string, decision: "approve" | "reject") => {
      const status: ActionStatus = decision === "approve" ? "approved" : "rejected";
      if (demo) {
        setLoad((prev) => (prev.state === "ok" ? { state: "ok", items: setActionStatus(prev.items, incidentId, actionId, status) } : prev));
        return setNotice({ actionId, text: t("ops.demo.decide") });
      }
      if (!key) return setNotice({ actionId, text: t("ops.needkey") });
      const problem = await decideAction(incidentId, actionId, decision, key);
      if (problem) {
        if (problem.status === 401 || problem.status === 403) setLoad({ state: "unauthorized" });
        return setNotice({ actionId, text: t("ops.decide.failed") });
      }
      setNotice(null);
      setLoad((prev) => (prev.state === "ok" ? { state: "ok", items: setActionStatus(prev.items, incidentId, actionId, status) } : prev));
    },
    [demo, key, t],
  );

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <section aria-labelledby="ops-title">
          <div className="wrap">
            <div className="sec-head">
              <h1 className="page-title" id="ops-title">{t("ops.title")}</h1>
              {demo ? <SourceBadge source="synthetic" /> : null}
              {!demo && load.state === "ok" ? <span className={live ? "pill pill--live pill--brand" : "pill"}>{t(live ? "board.live" : "board.paused")}</span> : null}
            </div>
            <p className="sec-sub">{t("ops.sub")}</p>

            {!demo ? (
              <form className="card keybox" onSubmit={saveKey} data-testid="key-form">
                <label htmlFor="operator-key"><Icon name="key" size={20} />{t("ops.key.label")}</label>
                <div className="keybox-row">
                  <input id="operator-key" className="mono" type="password" autoComplete="off" spellCheck={false} dir="ltr" value={draftKey} placeholder={key ? "••••••••" : ""} onChange={(e) => setDraftKey(e.target.value)} data-testid="key-input" />
                  <button className="btn btn--sm" type="submit">{t("ops.key.save")}</button>
                  {key ? <button className="btn btn--sm" type="button" onClick={forgetKey}>{t("ops.key.clear")}</button> : null}
                </div>
                <p className="small">{t("ops.key.hint")}</p>
              </form>
            ) : null}

            {load.state === "loading" ? (
              <div className="card state" role="status" data-testid="ops-loading">
                <p>{t("ops.loading")}</p>
                <div className="sk" />
                <div className="sk" />
              </div>
            ) : load.state === "unauthorized" ? (
              <div className="card state" role="status" data-testid="ops-unauthorized">
                <Icon name="key" size={40} />
                <h2 className="h3">{t("ops.unauth.title")}</h2>
                <p className="muted">{t("ops.unauth.body")}</p>
              </div>
            ) : load.state === "not_connected" ? (
              <div className="card state" role="status" data-testid="ops-not-connected">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{t("ops.nc.title")}</h2>
                <p className="muted">{t("ops.nc.body")}</p>
                <button className="btn" type="button" onClick={() => { setLoad({ state: "loading" }); setAttempt((n) => n + 1); }}><Icon name="refresh" size={20} />{t("retry")}</button>
              </div>
            ) : load.items.length === 0 ? (
              <div className="card state" role="status" data-testid="ops-empty">
                <Icon name="no_warning_signs" size={40} />
                <h2 className="h3">{t("ops.empty.title")}</h2>
                <p className="muted">{t("ops.empty.body")}</p>
              </div>
            ) : (
              load.items.map((incident) => <IncidentCard key={incident.incident_id} incident={incident} notice={notice} onDecide={decide} />)
            )}
          </div>
        </section>
      </main>
    </>
  );
}

function IncidentCard({ incident, notice, onDecide }: { incident: Incident; notice: { actionId: string; text: string } | null; onDecide: (incidentId: string, actionId: string, decision: "approve" | "reject") => void }) {
  const { t, lang } = usePrefs();
  const open = incident.status === "open" || incident.status === "triaging" || incident.status === "awaiting_approval";
  const title = pick(lang, incident.summary) || translateMaybe(lang, "type", incident.type);
  return (
    <article className="card incident" data-testid="incident-card" data-open={open ? "true" : undefined}>
      <div className="inc-head" data-sev={incident.severity}>
        <span className="sev"><SeverityMark severity={incident.severity} size={20} />{t("sev")}: {t(`sev.${incident.severity}`)}</span>
        <h2 dir="auto">{title}</h2>
        <SourceBadge source={incident.source} />
        <span className="pill">{translateMaybe(lang, "type", incident.type)}</span>
        <span className={incident.status === "awaiting_approval" ? "pill pill--wait pill--live" : "pill"} data-testid="incident-status">{t(`is.${incident.status}`)}</span>
      </div>
      <div className="inc-grid">
        <div>
          {pick(lang, incident.severity_reason) ? <p dir="auto">{pick(lang, incident.severity_reason)}</p> : null}
          <div className="kv">
            <span>{incident.incident_id}</span>
            {incident.rule_ids.map((r) => <span key={r}>rule:{r}</span>)}
            {Object.entries(incident.correlation_keys ?? {}).map(([k, v]) => <span key={k}>{k}={v}</span>)}
          </div>
          <h3>{t("i.ind")}</h3>
          {incident.indicators.length === 0 ? <p className="muted">{t("i.none")}</p> : (
            <ul className="ind">
              {incident.indicators.map((x, i) => (
                <li key={i}>
                  <span className="mono" translate="no">{x.value_defanged}</span>
                  <small>
                    {x.kind} · {t("i.first")} {formatTime(lang, x.first_seen)}
                    {x.blocked_until ? ` · ${t("i.blocked")} ${formatTime(lang, x.blocked_until, true)}` : ""}
                  </small>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>{t("i.tl")}</h3>
          {incident.timeline.length === 0 ? <p className="muted">{t("i.none")}</p> : (
            <ol className="tl">
              {incident.timeline.map((x, i) => (
                <li key={i}>
                  <time dateTime={x.at}>{formatTime(lang, x.at)}</time>
                  <UntrustedText value={x.what} />
                </li>
              ))}
            </ol>
          )}
          <h3>{t("i.act")}</h3>
          {incident.actions.length === 0 ? <p className="muted">{t("i.none")}</p> : incident.actions.map((a) => {
            const waiting = a.status === "awaiting_approval";
            const draft = a.draft ? (lang === "ar" ? a.draft.body_ar || a.draft.body_en : a.draft.body_en || a.draft.body_ar) : "";
            return (
              <div className="op" key={a.action_id} data-status={a.status} data-testid="incident-action">
                <div className="op-top">
                  <b>{translateMaybe(lang, "tool", a.tool)}</b>
                  <span className={waiting ? "pill pill--wait" : "pill"} data-testid="action-status">{t(`as.${a.status}`)}</span>
                </div>
                <span className="op-mode">{t(`mode.${a.mode}`)}</span>
                {draft ? <p className="op-draft" dir="auto">{draft}</p> : null}
                {waiting ? (
                  <div className="op-btns">
                    <button className="btn btn--sm" type="button" data-testid="approve" onClick={() => onDecide(incident.incident_id, a.action_id, "approve")}>{t("approve")}</button>
                    <button className="btn btn--sm" type="button" data-testid="reject" onClick={() => onDecide(incident.incident_id, a.action_id, "reject")}>{t("reject")}</button>
                  </div>
                ) : null}
                {notice?.actionId === a.action_id ? <p className="small" role="status" data-testid="action-notice">{notice.text}</p> : null}
              </div>
            );
          })}
        </div>
      </div>
    </article>
  );
}
