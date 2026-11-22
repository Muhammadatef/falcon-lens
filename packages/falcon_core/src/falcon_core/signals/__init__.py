"""Signal plugins. ``REGISTRY`` maps signal name -> (SignalSpec, async run)."""

from falcon_core.signals import injection as _injection  # noqa: F401  (registers injection.*)
from falcon_core.signals import url as _url  # noqa: F401  (import registers the url.* plugins)
from falcon_core.signals.base import REGISTRY, Evidence, SignalContext, SignalSpec

__all__ = ["REGISTRY", "Evidence", "SignalContext", "SignalSpec"]
