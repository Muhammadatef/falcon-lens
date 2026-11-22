"use client";

import { useEffect, useId, useRef, useState } from "react";
import { TIERS, type Tier, type VerdictLabel } from "@/lib/contracts";
import type { LensState, TierStatus } from "@/lib/verdict-stream";
import { Icon } from "./Icon";

/**
 * The instrument: progress indicator while checking, verdict seal when locked.
 * One SVG plus one rotating layer. The eight blades are redrawn only during a 420 ms
 * state change (one requestAnimationFrame tween); everything else is CSS on
 * data-attributes, so the server-rendered markup needs no inline style (strict CSP).
 */
const APERTURE: Record<LensState, number> = { idle: 78, scanning: 50, locked: 66 };
const TWEEN_MS = 420;

const polar = (r: number, deg: number): [number, number] => [200 + r * Math.sin((deg * Math.PI) / 180), 200 - r * Math.cos((deg * Math.PI) / 180)];
const fx = (n: number) => n.toFixed(1);

function arcPath(r: number, a0: number, a1: number): string {
  const [x0, y0] = polar(r, a0);
  const [x1, y1] = polar(r, a1);
  return `M${fx(x0)} ${fx(y0)}A${r} ${r} 0 0 1 ${fx(x1)} ${fx(y1)}`;
}

function bladePoints(aperture: number, i: number): string {
  const R = 141;
  const n = 8;
  const rv = aperture / Math.cos(Math.PI / n);
  const twist = 34 + (78 - aperture) * 0.9;
  const a0 = i * 45 + 22.5;
  const a1 = a0 + 45;
  return [polar(rv, a0), polar(rv, a1), polar(R, a1 + twist), polar(R, a0 + twist)].map(([x, y]) => `${fx(x)},${fx(y)}`).join(" ");
}

const ARCS = TIERS.map((_, i) => arcPath(170, i * 90 + 7, i * 90 + 83));
const BLADES = [0, 1, 2, 3, 4, 5, 6, 7];

export interface LensProps {
  state: LensState;
  verdict?: VerdictLabel | null;
  tiers?: Record<Tier, TierStatus>;
  mini?: boolean;
}

export function Lens({ state, verdict = null, tiers, mini = false }: LensProps) {
  const gradientId = useId();
  const [aperture, setAperture] = useState<number>(APERTURE[state]);
  const current = useRef(aperture);
  const raf = useRef(0);

  useEffect(() => {
    const to = APERTURE[state];
    const from = current.current;
    if (from === to) return;
    cancelAnimationFrame(raf.current);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      current.current = to;
      setAperture(to);
      return;
    }
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / TWEEN_MS);
      const eased = 1 - Math.pow(1 - k, 4);
      current.current = from + (to - from) * eased;
      setAperture(current.current);
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [state]);

  const locked = state === "locked" && verdict;
  return (
    <div className={mini ? "lens lens--mini" : "lens"} data-state={state} data-verdict={locked ? verdict : undefined} aria-hidden="true">
      <svg className="lens-svg" viewBox="0 0 400 400" focusable="false">
        <defs>
          <radialGradient id={gradientId} cx="42%" cy="38%" r="70%">
            <stop offset="0" stopColor="#1b2a4a" />
            <stop offset="0.6" stopColor="#070b14" />
            <stop offset="1" stopColor="#020409" />
          </radialGradient>
        </defs>
        <circle className="lens-halo" cx={200} cy={200} r={200} />
        <circle className="lens-ticks" cx={200} cy={200} r={190} />
        <circle className="lens-majors" cx={200} cy={200} r={190} />
        {ARCS.map((d, i) => (
          <path key={`b${i}`} className="lens-arc lens-arc--base" d={d} data-status={tiers?.[TIERS[i]!] ?? "pending"} />
        ))}
        {ARCS.map((d, i) => (
          <path key={`f${i}`} className="lens-arc lens-arc--fill" d={d} pathLength={1} data-status={tiers?.[TIERS[i]!] ?? "pending"} />
        ))}
        <circle className="lens-ring" cx={200} cy={200} r={152} />
        <circle cx={200} cy={200} r={141} fill={`url(#${gradientId})`} />
        <circle className="lens-pupil-tint" cx={200} cy={200} r={141} />
        <g>
          {BLADES.map((i) => (
            <polygon key={i} className="lens-blade" points={bladePoints(aperture, i)} />
          ))}
        </g>
        <ellipse className="lens-glint" cx={168} cy={166} rx={9} ry={5} transform="rotate(-35 168 166)" />
        <path className="lens-brow" d="M52 86C120 22 262 6 372 78" />
      </svg>
      <div className="lens-sweep" />
      <div className="lens-core">{locked ? <Icon name={verdict} size={96} /> : null}</div>
    </div>
  );
}
