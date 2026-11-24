"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  BATCH_MAX_FILE_BYTES,
  BATCH_MAX_URLS,
  couldNotCheck,
  parseBatchInput,
  toCsv,
  type BatchMode,
  type BatchResult,
} from "@/lib/batch";
import { bt, type BatchKey } from "@/lib/i18n-batch";
import { usePrefs } from "@/lib/prefs";

const CONCURRENCY = 3;
const MAX_429_RETRIES = 6;
const KEY_STORE = "fl_operator_key";

type Row = { url: string; result: BatchResult };

/** One URL through the server route, backing off on 429. Never throws. */
async function checkOne(url: string, key: string): Promise<BatchResult | "unauthorized" | "forbidden"> {
  for (let attempt = 0; attempt <= MAX_429_RETRIES; attempt++) {
    let res: Response;
    try {
      res = await fetch("/api/ops/batch", { method: "POST", headers: { "content-type": "application/json", "x-ops-key": key }, body: JSON.stringify({ url }) });
    } catch {
      return couldNotCheck("network error");
    }
    if (res.status === 401) return "unauthorized";
    if (res.status === 403) return "forbidden";
    if (res.status === 429 && attempt < MAX_429_RETRIES) {
      const wait = Number.parseInt(res.headers.get("retry-after") ?? "", 10);
      await new Promise((r) => setTimeout(r, (Number.isFinite(wait) ? Math.min(wait, 60) : 2 ** attempt) * 1000));
      continue;
    }
    if (res.status === 400) return couldNotCheck("not_http_url");
    if (!res.ok) return couldNotCheck(`HTTP ${res.status}`);
    try {
      return (await res.json()) as BatchResult;
    } catch {
      return couldNotCheck("bad response");
    }
  }
  return couldNotCheck("rate limited");
}

export function BatchTool() {
  const { lang } = usePrefs();
  const t = (k: BatchKey, v?: Record<string, string | number>) => bt(lang, k, v);
  const [key, setKey] = useState("");
  useEffect(() => setKey(window.sessionStorage.getItem(KEY_STORE) ?? ""), []);
  const [mode, setMode] = useState<BatchMode>("strict");
  const [urls, setUrls] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<BatchKey | null>(null);
  const stop = useRef(false);

  async function onFile(file: File | undefined) {
    setError(null);
    setFinished(false);
    setRows([]);
    setUrls([]);
    if (!file) return;
    if (file.size > BATCH_MAX_FILE_BYTES) return setError("e_big");
    const list = parseBatchInput(await file.text());
    if (list.length === 0) return setError("e_file");
    if (list.length > BATCH_MAX_URLS) return setError("e_many");
    setUrls(list);
  }

  async function start(e: FormEvent) {
    e.preventDefault();
    if (running || urls.length === 0) return;
    setError(null);
    setRunning(true);
    setFinished(false);
    stop.current = false;
    const results: Row[] = [];
    setRows([]);
    let next = 0;
    const worker = async () => {
      while (!stop.current && next < urls.length) {
        const url = urls[next++] as string;
        const out = await checkOne(url, key);
        if (out === "unauthorized" || out === "forbidden") {
          stop.current = true;
          setError(out === "unauthorized" ? "e_key" : "e_scope");
          return;
        }
        results.push({ url, result: out });
        setRows([...results]);
      }
    };
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    setRunning(false);
    if (!stop.current) {
      const order = new Map(urls.map((u, i) => [u, i]));
      results.sort((a, b) => (order.get(a.url) ?? 0) - (order.get(b.url) ?? 0));
      setRows(results);
      setFinished(true);
    }
  }

  // The CSV is built from the finished rows in the chosen mode; changing the mode after the run re-labels it.
  function download() {
    const blob = new Blob([toCsv(rows, mode)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `falcon-lens-batch-${mode}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const count = (v: string) => rows.filter((r) => r.result.verdict === v).length;

  return (
    <main id="main">
      <section aria-labelledby="batch-title">
        <div className="wrap">
          <h1 className="page-title" id="batch-title">{t("title")}</h1>
          <p className="sec-sub">{t("sub")}</p>
          <form className="card keybox" onSubmit={start} data-testid="batch-form">
            <label htmlFor="batch-key">{t("key")}</label>
            <input
              id="batch-key"
              className="mono"
              type="password"
              autoComplete="off"
              spellCheck={false}
              dir="ltr"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                window.sessionStorage.setItem(KEY_STORE, e.target.value);
              }}
              data-testid="batch-key"
            />
            <label htmlFor="batch-file">{t("file")}</label>
            <input id="batch-file" type="file" accept=".txt,.csv,text/plain,text/csv" onChange={(e) => void onFile(e.target.files?.[0])} data-testid="batch-file" />
            <fieldset>
              <legend>{t("mode")}</legend>
              <label><input type="radio" name="mode" checked={mode === "strict"} onChange={() => setMode("strict")} /> {t("strict")}</label>
              <label><input type="radio" name="mode" checked={mode === "lenient"} onChange={() => setMode("lenient")} /> {t("lenient")}</label>
            </fieldset>
            <button className="btn btn--primary" type="submit" disabled={running || urls.length === 0 || !key} data-testid="batch-start">{t("start")}</button>
            {error ? <p role="alert" data-testid="batch-error">{t(error)}</p> : null}
          </form>
          {urls.length > 0 ? (
            <div className="card keybox" aria-live="polite" data-testid="batch-progress">
              <progress max={urls.length} value={rows.length} aria-label={t("progress", { d: rows.length, n: urls.length })} />
              <p>{t("progress", { d: rows.length, n: urls.length })}</p>
              {rows.length > 0 ? <p className="small" data-testid="batch-summary">{t("summary", { a: count("dangerous"), b: count("suspicious"), c: count("no_warning_signs"), d: count("could_not_check") })}</p> : null}
              {finished ? (
                <>
                  <p>{t("done")}</p>
                  <button type="button" className="btn btn--primary" onClick={download} data-testid="batch-download">{t("download")}</button>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
