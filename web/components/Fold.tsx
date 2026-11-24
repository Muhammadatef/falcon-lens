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
  // A link such as #fp-h-sec (the in-page section nav) opens the section it points at.
  useEffect(() => {
    const openIfTargeted = () => {
      if (ref.current && window.location.hash === `#${id}-sec`) ref.current.open = true;
    };
    openIfTargeted();
    window.addEventListener("hashchange", openIfTargeted);
    return () => window.removeEventListener("hashchange", openIfTargeted);
  }, [id]);
  return (
    <details className="fold kpi-sec" id={`${id}-sec`} data-testid={testId} ref={ref}>
      <summary className="fold-sum">
        <h2 id={id}>{title}</h2>
        {badge}
      </summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}
