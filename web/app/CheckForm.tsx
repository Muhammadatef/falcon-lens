"use client";

import { useState, type FormEvent } from "react";

// Placeholder: no backend call yet (POST /v1/check/url arrives in a later task card).
export default function CheckForm() {
  const [submitted, setSubmitted] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <form onSubmit={onSubmit} className="check-form">
      <label htmlFor="input">الصق الرابط أو نص الرسالة</label>
      <textarea id="input" name="input" rows={4} required maxLength={4000} />
      <button type="submit">افحص</button>
      {submitted && (
        <p role="status" className="notice">
          هذه نسخة أولية، والفحص غير متصل بعد.
        </p>
      )}
    </form>
  );
}
