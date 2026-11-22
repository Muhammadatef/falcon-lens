"""AI wiring for the worker: LLM router, quarantined extractor (T2), investigator (T3), responder, T1 model.

Every piece is optional and fails soft: a missing provider, model artifact or detector leaves the deterministic
cascade intact (the router itself falls back cloud -> local -> none, and the responder to template reasons).
``FL_AI_ENABLED=false`` turns the LLM agents off (evals, offline demos); ``FL_T1_MODEL_ENABLED=false`` keeps
the draft p_clf.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from falcon_core.agent import Extractor, Investigator, Responder
from falcon_core.cascade.ai import AgentExtractorAdapter, load_injection_detector, signal_backend
from falcon_core.cascade.engine import SignalCtx
from falcon_core.cascade.ports import SandboxClient
from falcon_core.llm.router import LLMRouter
from falcon_core.signals import REGISTRY
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.tools.registry import ToolBackends, ToolRegistry

log = logging.getLogger("falcon.worker.ai")


def _flag(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def load_t1_model() -> Any:
    """The fitted T1 classifier (sha256-verified artifact), or None -> draft p_clf (logged, flagged in verdicts)."""
    if not _flag("FL_T1_MODEL_ENABLED"):
        return None
    try:
        from falcon_core.scoring.t1_model import load_t1_model as load

        return load()
    except Exception as exc:  # noqa: BLE001 - ImportError (no sklearn) or ModelError
        log.error("T1 model not loaded, using draft p_clf: %s", f"{type(exc).__name__}: {exc}"[:200])
        return None


def tool_backends(http: Any, cache: Any, mirror: Any, registry: BrandRegistry, sandbox: SandboxClient) -> ToolBackends:
    """Investigator tools over the same registered signals the cascade uses (evidence out, never raw text)."""

    def ctx_for_domain(domain: str) -> SignalCtx:
        return SignalCtx(url=f"https://{domain}/", http=http, cache=cache, mirror=mirror, brands=registry)

    def ctx_for_url(url: str) -> SignalCtx:
        return SignalCtx(url=url, http=http, cache=cache, mirror=mirror, brands=registry)

    return ToolBackends(
        rdap_lookup=signal_backend("domain.age_days", ctx_for_domain, REGISTRY),
        cert_lookup=signal_backend("domain.cert_age_days", ctx_for_domain, REGISTRY),
        check_reputation=signal_backend("rep.urlhaus", ctx_for_url, REGISTRY),
    )


def build_ai(
    *, http: Any, cache: Any, mirror: Any, registry: BrandRegistry, sandbox: SandboxClient
) -> Mapping[str, Any]:
    """``CascadeDeps`` keyword arguments for the AI parts."""
    out: dict[str, Any] = {"t1_model": load_t1_model(), "injection": load_injection_detector()}
    if not _flag("FL_AI_ENABLED"):
        log.warning("FL_AI_ENABLED=false: extractor, investigator and responder are off")
        return out
    try:
        router = LLMRouter()
        # Brand ids and owned domains come from the same registry the cascade uses (one source of truth).
        brand_ids = frozenset(b.brand_id for b in registry.brands)
        owned = {b.brand_id: frozenset(b.verified_domains) for b in registry.brands}
        out["extractor"] = AgentExtractorAdapter(
            Extractor(router, brand_ids=brand_ids, verified_domains=owned), out["injection"]
        )
        out["responder"] = Responder(router)
        backends = tool_backends(http, cache, mirror, registry, sandbox)
        out["investigator"] = Investigator(router, ToolRegistry(backends, brand_ids=brand_ids))
    except Exception as exc:  # noqa: BLE001 - never block the worker on the optional AI parts
        log.error("AI agents not started, deterministic cascade only: %s", f"{type(exc).__name__}: {exc}"[:200])
        for k in ("extractor", "responder", "investigator"):
            out.pop(k, None)
    return out
