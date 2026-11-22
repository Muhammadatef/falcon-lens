"""Signal plugins. ``REGISTRY`` maps signal name -> (SignalSpec, async run)."""

# isort: off
# url first: brands.registry and url.* import each other; only this order resolves.
from falcon_core.signals import url as _url  # noqa: F401  (import registers the url.* plugins)
from falcon_core.signals import message as _message  # noqa: F401
from falcon_core.signals import image as _image  # noqa: F401
from falcon_core.signals import email as _email  # noqa: F401

# isort: on
from falcon_core.signals.base import REGISTRY, Evidence, SignalContext, SignalSpec

__all__ = ["REGISTRY", "Evidence", "SignalContext", "SignalSpec"]
