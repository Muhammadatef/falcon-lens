"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOC_SLUGS, isDocSlug } from "@/lib/docs-content";
import { useDt } from "@/lib/use-dt";

/** Side list on desktop; on a phone a breadcrumb ("Docs > page") that links back to the landing page. */
export function DocsNav() {
  const d = useDt();
  const pathname = usePathname();
  const slug = pathname.split("/")[2] ?? "";
  const current = isDocSlug(slug) ? slug : null;
  return (
    <>
      {current ? (
        <nav className="docs-crumb" aria-label={d("docs.nav")}>
          <ol>
            <li><Link href="/docs">{d("docs.crumb")}</Link></li>
            <li aria-current="page">{d(`docs.${current}.title`)}</li>
          </ol>
        </nav>
      ) : null}
      <nav className="docs-side" aria-label={d("docs.nav")} data-testid="docs-side">
        <ul>
          <li><Link href="/docs" aria-current={pathname === "/docs" ? "page" : undefined}>{d("docs.title")}</Link></li>
          {DOC_SLUGS.map((s) => (
            <li key={s}>
              <Link href={`/docs/${s}`} aria-current={current === s ? "page" : undefined}>{d(`docs.${s}.title`)}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
