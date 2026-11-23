/**
 * The Sentinel's glyph: a radar. Static SVG plus one rotating layer (CSS only, same rules as Lens.tsx:
 * stops under prefers-reduced-motion, transform only). Decorative; the agent's name always sits beside it.
 */
const NODES: [number, number, boolean][] = [
  [62, 58, true],
  [74, 70, true],
  [66, 76, true],
  [138, 126, false],
  [120, 150, false],
  [146, 70, false],
];

export function Radar({ mini = false }: { mini?: boolean }) {
  return (
    <span className="radar-wrap">
    <svg className={mini ? "radar-glyph radar-glyph--mini" : "radar-glyph"} viewBox="0 0 200 200" aria-hidden="true" focusable="false">
      <circle className="rg-disc" cx="100" cy="100" r="96" />
      <circle className="rg-ring" cx="100" cy="100" r="96" />
      <circle className="rg-ring" cx="100" cy="100" r="64" />
      <circle className="rg-ring" cx="100" cy="100" r="32" />
      <path className="rg-axis" d="M100 4v192M4 100h192" />
      {!mini ? (
        <>
          <path className="rg-link" d="M62 58 74 70 66 76 62 58" />
          {NODES.map(([x, y, linked]) => (
            <circle key={`${x}-${y}`} className={linked ? "rg-node rg-node--linked" : "rg-node"} cx={x} cy={y} r={linked ? 5 : 3.5} />
          ))}
        </>
      ) : null}
      <circle className="rg-core" cx="100" cy="100" r="5" />
    </svg>
    {/* the sweep is an HTML layer so it rotates on the compositor (an animated SVG child repaints the page every frame) */}
    <i className="rg-sweepdiv" aria-hidden="true" />
    </span>
  );
}
