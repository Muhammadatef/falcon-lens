"use client";

import { translate } from "@/lib/i18n";
import "./globals.css";

/** Last-resort boundary (the root layout itself failed): both languages, no context providers. */
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="ar" dir="rtl" data-theme="dark">
      <body>
        <main id="main" className="wrap err-page" data-testid="global-error">
          <h1 className="page-title" lang="ar" dir="rtl" role="alert">{translate("ar", "err.title")}</h1>
          <p className="page-lead" lang="ar" dir="rtl">{translate("ar", "err.body")}</p>
          <h2 className="page-title" lang="en" dir="ltr">{translate("en", "err.title")}</h2>
          <p className="page-lead" lang="en" dir="ltr">{translate("en", "err.body")}</p>
          <div className="err-actions">
            <button className="btn btn--primary" type="button" onClick={() => reset()}>{translate("ar", "err.retry")} · {translate("en", "err.retry")}</button>
          </div>
        </main>
      </body>
    </html>
  );
}
