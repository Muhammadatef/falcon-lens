"use client";

import { useEffect, useState } from "react";
import { authHeaders } from "@/lib/api";
import { hT } from "@/lib/i18n-history";
import { usePrefs } from "@/lib/prefs";

const KEY_STORE = "fl_operator_key";

/**
 * Operator-only download of the police evidence pack (GET /v1/verdicts/{id}/evidence-pack).
 * Public visitors only see a note that the pack is available to authorities: there is no key form here.
 * The key is entered on /ops and read from sessionStorage (never a cookie or URL).
 */
export function EvidencePackButton({ verdictId, final, compact = false }: { verdictId: string; final: boolean; compact?: boolean }) {
  const { lang } = usePrefs();
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<"" | "denied" | "notfinal" | "failed">("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      setKey(window.sessionStorage.getItem(KEY_STORE) ?? "");
    } catch {
      /* storage blocked */
    }
  }, []);

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
      window.setTimeout(() => URL.revokeObjectURL(url), 1000); // after the browser has taken the download
    } catch {
      setMsg("failed");
    } finally {
      setBusy(false);
    }
  };

  if (compact) {
    // /ops incident view: one inline button per linked check; the operator key comes from the /ops session.
    if (!key) return null;
    return (
      <span className="ep-inline" data-testid="evidence-pack-inline">
        <button className="btn btn--sm" type="button" disabled={busy || !final} onClick={() => void download()} data-testid="evidence-pack-download" aria-label={`${hT(lang, "ep.button")} ${verdictId}`}>
          {hT(lang, "ep.button")}
        </button>
        {msg ? <small role="status" data-testid="evidence-pack-msg"> {hT(lang, `ep.${msg}` as "ep.denied")}</small> : null}
      </span>
    );
  }

  return (
    <section className="card keybox" aria-labelledby="ep-title" data-testid="evidence-pack">
      <h2 className="h3" id="ep-title">{hT(lang, "ep.title")}</h2>
      {key ? (
        <button className="btn btn--sm btn--primary" type="button" disabled={busy || !final} onClick={() => void download()} data-testid="evidence-pack-download">
          {hT("en", "ep.button")} | <span lang="ar">{hT("ar", "ep.button")}</span>
        </button>
      ) : (
        <p className="small" data-testid="evidence-pack-public">{hT(lang, "ep.public")}</p>
      )}
      {msg ? <p className="small" role="status" data-testid="evidence-pack-msg">{hT(lang, `ep.${msg}` as "ep.denied")}</p> : null}
    </section>
  );
}
