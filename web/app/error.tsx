"use client";

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { usePrefs } from "@/lib/prefs";

/** Route-level error boundary: a human, actionable message in the reader's language. Never shows the error text. */
export default function RouteError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = usePrefs();
  return (
    <main id="main" className="wrap err-page" data-testid="route-error">
      <Icon name="unplug" size={56} />
      <h1 className="page-title" role="alert">{t("err.title")}</h1>
      <p className="page-lead">{t("err.body")}</p>
      <div className="err-actions">
        <button className="btn btn--primary" type="button" onClick={() => reset()}>{t("err.retry")}</button>
        <Link className="btn" href="/">{t("err.home")}</Link>
      </div>
    </main>
  );
}
