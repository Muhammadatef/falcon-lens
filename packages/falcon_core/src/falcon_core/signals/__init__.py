"""Signal plugins. ``REGISTRY`` maps signal name -> (SignalSpec, async run)."""

from falcon_core.signals import domain as _domain  # noqa: F401  (import registers the plugins)
from falcon_core.signals import reputation as _reputation  # noqa: F401
from falcon_core.signals import url as _url  # noqa: F401
from falcon_core.signals.base import REGISTRY, Evidence, SignalContext, SignalSpec

__all__ = ["REGISTRY", "Evidence", "SignalContext", "SignalSpec"]
