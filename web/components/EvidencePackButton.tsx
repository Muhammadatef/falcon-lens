"use client";

import { useEffect, useState, type FormEvent } from "react";
import { authHeaders } from "@/lib/api";
import { hT } from "@/lib/i18n-history";
import { usePrefs } from "@/lib/prefs";

const KEY_STORE = "fl_operator_key";

/**
 * Operator-only download of the police evidence pack (GET /v1/verdicts/{id}/evidence-pack).
 * Without a key, public visitors see a note that the pack is available to authorities. The key stays in
 * sessionStorage (shared with /ops), never in a cookie or URL.
 */
export function EvidencePackButton({ verdictId, final }: { verdictId: string; final: boolean }) {
  const { lang } = usePrefs();
  const [key, setKey] = useState("");
  const [draft, setDraft] = useState("");
  const [msg, setMsg] = useState<"" | "denied" | "notfinal" | "failed">("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      setKey(window.sessionStorage.getItem(KEY_STORE) ?? "");
    } catch {
      /* storage blocked */
    }
  }, []);

  const save = (e: FormEvent) => {
    e.preventDefault();
    const next = draft.trim();
    if (!next) return;
    try {
      window.sessionStorage.setItem(KEY_STORE, next);
    } catch {
      /* in memory only */
    }
    setKey(next);
    setDraft("");
  };

  const download = async () => {
    setBusy(true);
    setMsg("");
    try {
      const r = await fetch(`/v1/verdicts/${encodeURIComponent(verdictId)}/evidence-pack`, { headers: { ...authHeaders(key), accept: "application/zip" }, credentials: "same-origin", cache: "no-store" });
      if (r.status === 401 || r.status === 403) return setMsg("denied");
      if (r.status === 409) return setMsg("notfinal");
      if (!r.ok) return setMsg("failed");
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `evidence-${verdictId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setMsg("failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card keybox" aria-labelledby="ep-title" data-testid="evidence-pack">
      <h2 className="h3" id="ep-title">{hT(lang, "ep.title")}</h2>
      {key ? (
        <button className="btn btn--sm btn--primary" type="button" disabled={busy || !final} onClick={() => void download()} data-testid="evidence-pack-download">
          {hT("en", "ep.button")} | <span lang="ar">{hT("ar", "ep.button")}</span>
        </button>
      ) : (
        <>
          <p className="small" data-testid="evidence-pack-public">{hT(lang, "ep.public")}</p>
          <form className="keybox-row" onSubmit={save}>
            <label htmlFor="ep-key" className="small">{hT(lang, "ep.key")}</label>
            <input id="ep-key" className="mono" type="password" autoComplete="off" spellCheck={false} dir="ltr" value={draft} onChange={(e) => setDraft(e.target.value)} data-testid="evidence-pack-key" />
            <button className="btn btn--sm" type="submit">OK</button>
          </form>
        </>
      )}
      {msg ? <p className="small" role="status" data-testid="evidence-pack-msg">{hT(lang, `ep.${msg}` as "ep.denied")}</p> : null}
    </section>
  );
}
