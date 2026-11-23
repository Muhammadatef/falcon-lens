import type { Polarity, Severity } from "@/lib/contracts";

/**
 * Icons: 24 px grid, 1.9 stroke, round joins, currentColor. Verdicts differ by outline
 * shape: octagon (dangerous), triangle (suspicious), lens with a dash (no warning signs).
 * No tick marks, padlocks-as-good or shields anywhere (DESIGN.md §6).
 */
const ICONS = {
  dangerous: ["M8.3 2.6h7.4l5.7 5.7v7.4l-5.7 5.7H8.3l-5.7-5.7V8.3z", "M12 7.4v5.8", "M12 16.6v.1"],
  suspicious: ["M12 3.1 21.8 20.4H2.2z", "M10.1 11.3a2 2 0 1 1 3 1.7c-.7.4-1.1.9-1.1 1.6", "M12 17.4v.1"],
  no_warning_signs: ["M10.5 3.5a7 7 0 1 1 0 14 7 7 0 0 1 0-14z", "M15.6 15.6 21 21", "M7.6 10.5h5.8"],
  url: ["M10 14a4.2 4.2 0 0 0 6 0l3-3a4.2 4.2 0 0 0-6-6l-1 1", "M14 10a4.2 4.2 0 0 0-6 0l-3 3a4.2 4.2 0 0 0 6 6l1-1"],
  message: ["M4 5h16v11H9l-5 4z"],
  email: ["M3 6h18v12H3z", "m3 7 9 6.5L21 7"],
  image: ["M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z", "M14 14h2.5v2.5M20 14v6h-6v-2"],
  hand: ["M8 12V6.5a1.5 1.5 0 0 1 3 0V11m0-5.5v-1a1.5 1.5 0 0 1 3 0V11m0-5a1.5 1.5 0 0 1 3 0v8.5a6 6 0 0 1-6 6h-.6a6 6 0 0 1-4.6-2.2L4.6 14a1.6 1.6 0 0 1 2.5-2z"],
  undo: ["M9 7 4.5 11.5 9 16", "M4.5 11.5H14a5.5 5.5 0 0 1 0 11h-2"],
  flag: ["M5 21V4", "M5 4.5c4-2 6 2 10 .5 1.6-.6 3-1 4-1v9c-1 0-2.4.4-4 1-4 1.5-6-2.5-10-.5"],
  eye: ["M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z", "M12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"],
  keep: ["M6 11h12v9H6z", "M8.5 11V8a3.5 3.5 0 0 1 7 0v3"],
  scale: ["M12 4v16M7 20h10M5 8h14", "M5 8l-2.5 6a2.8 2.8 0 0 0 5 0zM19 8l-2.5 6a2.8 2.8 0 0 0 5 0z"],
  list: ["M8 6h12M8 12h12M8 18h12", "M4 6v.1M4 12v.1M4 18v.1"],
  globe: ["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M3 12h18", "M12 3c2.5 2.5 3.5 5.5 3.5 9S14.5 18.5 12 21c-2.5-2.5-3.5-5.5-3.5-9S9.500 5.500 12 3z"],
  box: ["M4 8l8-4 8 4v8l-8 4-8-4z", "M4 8l8 4 8-4M12 12v8"],
  spark: ["M12 3v4M12 17v4M3 12h4M17 12h4", "M12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"],
  sun: ["M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z", "M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"],
  moon: ["M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.500 10.500z"],
  unplug: ["M9 3v5M15 3v5", "M6 8h12v3a6 6 0 0 1-12 0z", "M12 17v4", "M3 3l18 18"],
  clock: ["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M12 7.500V12l3 2"],
  paperclip: ["M20 11.500l-7.800 7.800a5 5 0 0 1-7-7L13 4.500a3.300 3.300 0 0 1 4.700 4.700L10 16.900a1.700 1.700 0 0 1-2.400-2.400l7-7"],
  x: ["M6 6l12 12M18 6 6 18"],
  menu: ["M4 7h16M4 12h16M4 17h16"],
  refresh: ["M4 12a8 8 0 0 1 13.700-5.600L20 8.500", "M20 4v4.500h-4.500", "M20 12a8 8 0 0 1-13.700 5.600L4 15.500", "M4 20v-4.500h4.500"],
  key: ["M14.500 9.500a4 4 0 1 0-3.700 5.500L12 16.200V18h2v2h3v-3l-3.800-3.800a4 4 0 0 0 1.300-3.700z", "M9.500 9.500v.1"],
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 24, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={className ? `icon ${className}` : "icon"} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {ICONS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** Evidence polarity: shape carries the meaning (up = raises risk, down = lowers, ring = neutral). */
export function PolarityMark({ polarity }: { polarity: Polarity }) {
  return (
    <svg className="icon ev-mark" width={16} height={16} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {polarity === "risk" ? (
        <path d="M8 2.5 14.5 13.5h-13z" fill="currentColor" />
      ) : polarity === "trust" ? (
        <path d="M8 13.5 1.5 2.5h13z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      ) : (
        <circle cx={8} cy={8} r={4.5} fill="none" stroke="currentColor" strokeWidth="2" />
      )}
    </svg>
  );
}

/** Severity: octagon critical, triangle high, diamond medium, circle low. */
export function severityPath(sev: Severity, cx: number, cy: number, r: number): string {
  const f = (n: number) => n.toFixed(1);
  if (sev === "high") return `M${f(cx)} ${f(cy - r)} ${f(cx + r)} ${f(cy + r * 0.85)}H${f(cx - r)}z`;
  if (sev === "medium") return `M${f(cx)} ${f(cy - r)} ${f(cx + r)} ${f(cy)} ${f(cx)} ${f(cy + r)} ${f(cx - r)} ${f(cy)}z`;
  if (sev === "critical") {
    const k = r * 0.42;
    const d = r - k;
    return `M${f(cx - k)} ${f(cy - r)}h${f(2 * k)}l${f(d)} ${f(d)}v${f(2 * k)}l${f(-d)} ${f(d)}h${f(-2 * k)}l${f(-d)} ${f(-d)}v${f(-2 * k)}z`;
  }
  const c = r * 0.8;
  return `M${f(cx - c)} ${f(cy)}a${f(c)} ${f(c)} 0 1 0 ${f(2 * c)} 0a${f(c)} ${f(c)} 0 1 0 ${f(-2 * c)} 0z`;
}

export function SeverityMark({ severity, size = 16 }: { severity: Severity; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false">
      <path d={severityPath(severity, 8, 8, 6.5)} />
    </svg>
  );
}

/** The mark: ring, pupil, brow stroke and the falcon's malar stripe. Original; no crest, no shield. */
export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <svg className="icon brand-mark" width={size} height={size} viewBox="0 0 36 36" fill="none" aria-hidden="true" focusable="false">
      <path className="brand-mark-sand" d="M5 10.5c5-5.5 16-7 26-2.5" strokeWidth="3" strokeLinecap="round" />
      <circle className="brand-mark-ring" cx="18" cy="18" r="9" strokeWidth="3" />
      <circle className="brand-mark-pupil" cx="18" cy="18" r="3.6" />
      <path className="brand-mark-sand" d="M14.5 28.5c-.6 2.6-2 4.6-4 6" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
