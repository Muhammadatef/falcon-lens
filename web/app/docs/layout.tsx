import type { ReactNode } from "react";
import { DocsNav } from "@/components/docs/DocsNav";

export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="wrap docs-shell">
      <DocsNav />
      <div className="docs-main">{children}</div>
    </div>
  );
}
