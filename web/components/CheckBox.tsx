"use client";

import { useEffect, useId, useRef, useState, type ClipboardEvent, type FormEvent } from "react";
import { IMAGE_TYPES, LIMITS, emlFile, looksLikeEml, utf8Bytes, type CheckInput } from "@/lib/api";
import type { InputType } from "@/lib/contracts";
import { looksLikeSingleUrl, refang } from "@/lib/defang";
import type { MessageKey } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import type { CheckInputPreview } from "@/lib/verdict-stream";
import { Icon } from "./Icon";

const KINDS: readonly InputType[] = ["url", "message", "email", "image"];

export interface CheckBoxProps {
  busy: boolean;
  initialText?: string;
  /** Input types whose capability flag is not live yet: a plain note is shown on that tab. */
  pending?: readonly InputType[];
  onSubmit: (input: CheckInput, preview: CheckInputPreview) => void;
}

/**
 * Builds the request from what the person gave us. The "Link" and "Message" tabs are
 * hints, not traps: one link-shaped token goes to the URL check, anything else to the
 * message check, so pasting a whole SMS into the link box still does the right thing.
 */
export function buildInput(kind: InputType, text: string, file: File | null): { input: CheckInput; preview: CheckInputPreview } | { error: MessageKey } {
  const trimmed = text.trim();
  if (kind === "image") {
    if (!file) return { error: "err.file" };
    if (!(IMAGE_TYPES as readonly string[]).includes(file.type)) return { error: "err.filetype" };
    if (file.size > LIMITS.imageBytes) return { error: "err.toobig" };
    return { input: { kind: "image", file }, preview: { kind: "image", text: file.name } };
  }
  if (kind === "email") {
    if (file) {
      if (!file.name.toLowerCase().endsWith(".eml")) return { error: "err.emltype" };
      if (file.size > LIMITS.emailBytes) return { error: "err.toobig" };
      return { input: { kind: "email", file }, preview: { kind: "email", text: file.name } };
    }
    if (!trimmed) return { error: "err.empty" };
    // The API takes email only as an RFC 5322 .eml upload. Pasted text with headers is
    // wrapped as one; pasted body text without headers falls through to the message check.
    const raw = text.trimStart();
    if (looksLikeEml(raw)) {
      if (utf8Bytes(raw) > LIMITS.emailBytes) return { error: "err.toobig" };
      return { input: { kind: "email", file: emlFile(raw) }, preview: { kind: "email", text: trimmed } };
    }
  }
  if (!trimmed) return { error: "err.empty" };
  if (looksLikeSingleUrl(trimmed)) {
    if (utf8Bytes(trimmed) > LIMITS.urlBytes) return { error: "err.toobig" };
    return { input: { kind: "url", url: refang(trimmed) }, preview: { kind: "url", text: trimmed } };
  }
  if (utf8Bytes(trimmed) > LIMITS.messageBytes) return { error: "err.toobig" };
  return { input: { kind: "message", text: trimmed }, preview: { kind: "message", text: trimmed } };
}

export function CheckBox({ busy, initialText = "", pending = [], onSubmit }: CheckBoxProps) {
  const { t } = usePrefs();
  const [kind, setKind] = useState<InputType>(initialText && !looksLikeSingleUrl(initialText) ? "message" : "url");
  const [text, setText] = useState(initialText);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const hintId = useId();
  const errorId = useId();

  useEffect(() => setError(null), [kind, text, file]);

  const choose = (next: InputType) => {
    setKind(next);
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    const built = buildInput(kind, text, file);
    if ("error" in built) return setError(built.error);
    onSubmit(built.input, built.preview);
  };

  // Pasting a screenshot anywhere in the box switches to the image check.
  const onPaste = (event: ClipboardEvent<HTMLFormElement>) => {
    const pasted = Array.from(event.clipboardData.files).find((f) => f.type.startsWith("image/"));
    if (!pasted) return;
    event.preventDefault();
    setKind("image");
    setFile(pasted);
  };

  const wantsFile = kind === "image" || kind === "email";
  const wantsText = kind !== "image";
  return (
    <form className="paste" onSubmit={submit} onPaste={onPaste} noValidate data-testid="check-form">
      <div className="seg" role="group" aria-label={t("kind.label")}>
        {KINDS.map((k) => (
          <button key={k} type="button" aria-pressed={kind === k} data-testid={`kind-${k}`} onClick={() => choose(k)}>
            <Icon name={k} size={18} />
            {t(`kind.${k}`)}
          </button>
        ))}
      </div>

      <label htmlFor={wantsText ? inputId : `${inputId}-file`}>{t(`input.${kind}`)}</label>
      {wantsText ? (
        <textarea
          id={inputId}
          data-testid="check-input"
          rows={kind === "url" ? 2 : 5}
          dir="auto"
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          maxLength={kind === "email" ? LIMITS.emailBytes : LIMITS.messageBytes}
          placeholder={kind === "url" ? "hxxps://…" : undefined}
          aria-describedby={error ? `${hintId} ${errorId}` : hintId}
          aria-invalid={error ? true : undefined}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : null}

      {wantsFile ? (
        <div className="file-row">
          <input
            ref={fileRef}
            id={`${inputId}-file`}
            className="vh"
            type="file"
            data-testid="check-file"
            accept={kind === "image" ? IMAGE_TYPES.join(",") : ".eml,message/rfc822"}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button className="btn btn--sm" type="button" onClick={() => fileRef.current?.click()}>
            <Icon name="paperclip" size={18} />
            {t("file.choose")}
          </button>
          {file ? (
            <span className="file-chip" data-testid="file-chip">
              <span className="vh">{t("file.chosen")}</span>
              <bdi className="mono">{file.name}</bdi>
              <button type="button" className="file-x" aria-label={t("file.remove")} onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}>
                <Icon name="x" size={16} />
              </button>
            </span>
          ) : null}
        </div>
      ) : null}

      <p className="paste-hint" id={hintId}>{t(`input.hint.${kind}`)}</p>
      {pending.includes(kind) ? <p className="paste-hint paste-pending" data-testid="kind-pending">{t("kind.pending")}</p> : null}
      {error ? (
        <p className="paste-error" id={errorId} role="alert" data-testid="input-error">
          <Icon name="suspicious" size={20} />
          <span>{t(error)}</span>
        </p>
      ) : null}
      <button className="btn btn--primary" type="submit" disabled={busy} data-testid="check-submit">
        <Icon name="no_warning_signs" size={24} />
        {t(busy ? "btn.checking" : "btn.check")}
      </button>
    </form>
  );
}
