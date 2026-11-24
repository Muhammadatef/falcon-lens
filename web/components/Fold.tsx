"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * A collapsible results section: closed by default (short phone page), opened on wide screens after mount.
 * Plain <details>, so it works without script and by keyboard; the heading lives inside the summary.
 */
export function Fold({ id, title, badge, testId, openOnDesktop = true, children }: { id: string; title: string; badge?: ReactNode; testId: string; openOnDesktop?: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (openOnDesktop && window.matchMedia("(min-width: 1024px)").matches && ref.current) ref.current.open = true;
  }, [openOnDesktop]);
  return (
    <details className="fold kpi-sec" data-testid={testId} ref={ref}>
      <summary className="fold-sum">
        <h2 id={id}>{title}</h2>
        {badge}
      </summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}
