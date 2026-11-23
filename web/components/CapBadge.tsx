import { translate } from "@/lib/i18n";
import type { Lang } from "@/lib/contracts";

/**
 * Status chip driven by a capability flag (`loadCapabilities()`), never set by hand.
 * Live = solid outline + filled dot; In progress = dashed outline + hollow dot. A word and a shape, never colour alone.
 */
export function CapBadge({ live, lang }: { live: boolean; lang: Lang }) {
  return (
    <span className="cap" data-live={live ? "true" : "false"} data-testid="cap-badge">
      <i aria-hidden="true" />
      {translate(lang, live ? "cap.live" : "cap.progress")}
    </span>
  );
}
