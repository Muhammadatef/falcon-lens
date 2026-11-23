import Link from "next/link";

/** Plain 404 page with no inline styles (the framework default uses a style attribute, which the strict CSP blocks). */
export default function NotFound() {
  const l = { href: "/" };
  return (
    <main id="main">
      <div className="wrap">
        <div className="card state" role="status" data-testid="not-found">
          <h1 className="page-title">404</h1>
          <p className="muted">الصفحة غير موجودة · Page not found</p>
          <Link className="btn" href={l.href}>عدسة الصقر · Falcon Lens</Link>
        </div>
      </div>
    </main>
  );
}
