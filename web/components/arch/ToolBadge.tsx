import { Icon } from "@/components/Icon";
import type { Badge } from "@/lib/arch-flow";
import { LOGO_PATHS } from "@/lib/tool-logos.gen";

/**
 * The square badge of a diagram node. Three kinds, never mixed up:
 *   logo  an unmodified vendored tool logo (public/logos/tools, see LOGOS_LICENSES.md) in its brand colour on a light tile;
 *   mono  a neutral text badge for a tool whose logo is not vendored (never a drawn imitation);
 *   icon  one of our own icons, for our own code.
 * Decorative: the caller always prints the name as text.
 */
export function ToolBadge({ badge, size = "md" }: { badge: Badge; size?: "sm" | "md" }) {
  if ("logo" in badge) {
    const logo = LOGO_PATHS[badge.logo];
    return (
      <span className="tb" data-kind="logo" data-size={size} data-logo={badge.logo} aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d={logo.d} fill={logo.hex} />
        </svg>
      </span>
    );
  }
  if ("mono" in badge) {
    return <span className="tb" data-kind="mono" data-size={size} data-len={badge.mono.length > 2 ? "long" : "short"} aria-hidden="true">{badge.mono}</span>;
  }
  return (
    <span className="tb" data-kind="icon" data-size={size} aria-hidden="true">
      <Icon name={badge.icon} size={size === "sm" ? 16 : 20} />
    </span>
  );
}
