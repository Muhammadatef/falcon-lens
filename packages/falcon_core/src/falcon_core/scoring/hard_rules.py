"""Hard rules H1-H6 (docs/SCORING.md §3). Evaluated before the log-odds score.

Each rule is a pure function over *present* evidence (ran, no error, positive observation) and
returns a ``FiredRule`` naming the evidence ids that triggered it, so reasons can cite them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from falcon_core.scoring.evidence import (
    Evidence,
    confidence_of,
    family_matches,
    observed_get,
    observed_number,
    untrusted_origin,
)
from falcon_core.scoring.params import ScoringParams

RuleId = Literal["H1", "H2", "H3", "H4", "H5", "H6"]
Effect = Literal["floor_dangerous", "floor_suspicious", "cap_no_warning_signs"]
InputType = Literal["url", "message", "email", "image"]

FEED_SIGNALS: frozenset[str] = frozenset(["rep.openphish", "rep.gsb", "rep.urlhaus"])
BOT_TARGET_KINDS: frozenset[str] = frozenset(["bot_api", "messaging_bot", "webhook", "webhook_relay", "form_relay"])
LINK_VERDICT_SIGNALS: frozenset[str] = frozenset(["message.link_verdict", "email.link_verdict"])
# "authority/bank impersonation" for H6 (SCORING §3). ``message.brand_mention`` counts: a message that names a
# registered brand (the usual "BankName: ..." sender line) AND asks for a one-time code or a remote-access
# install is posing as that brand; no bank asks for either by message. The ask rules are narrow (a code
# *delivery* or a "never share your code" reminder does not fire them), so a named brand alone never fires H6.
IMPERSONATION_SIGNALS: frozenset[str] = frozenset(
    [
        "message.rule.authority",
        "message.brand_mention",
        "email.display_name_impersonation",
        "brand.claimed_not_owned",
    ]
)


@dataclass(frozen=True, slots=True)
class FiredRule:
    rule_id: RuleId
    effect: Effect
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HardRuleOutcome:
    fired: tuple[FiredRule, ...]
    suppressed: tuple[FiredRule, ...]  # rules that matched but were overridden by H3


def _by_signal(present: Sequence[Evidence], *signals: str) -> list[Evidence]:
    wanted = set(signals)
    return [e for e in present if e.signal in wanted and family_matches(e)]


def h1_brand_mismatch(
    present: Sequence[Evidence],
    params: ScoringParams,
    registrable_domain: str | None,
    verified_domains: Mapping[str, frozenset[str]] | None,
) -> FiredRule | None:
    # H1 never depends on an LLM: only deterministic claims (page title/text brand tokens, favicon, hotlinked
    # assets, form context) count. An extractor claim still adds log-odds weight (risk only) but cannot fire
    # the rule, and a prompt-injected extractor can neither remove nor replace a deterministic claim.
    claims = [
        e
        for e in _by_signal(present, "brand.claimed_not_owned")
        if confidence_of(e) >= params.h1_brand_claim_min_confidence and not untrusted_origin(e)
    ]
    if registrable_domain and verified_domains:
        # Double-check "not owned" against the registry when the caller supplies it.
        dom = registrable_domain.lower()
        claims = [
            e for e in claims if dom not in verified_domains.get(str(observed_get(e, "brand_id") or ""), frozenset())
        ]
    intent = _by_signal(present, "page.cred_form", "message.rule.payment")
    if not claims or not intent:
        return None
    return FiredRule("H1", "floor_dangerous", tuple(e.id for e in [*claims, *intent]))


def _is_fresh_feed_hit(ev: Evidence, params: ScoringParams) -> bool:
    match = observed_get(ev, "match")
    if match is not None and match not in ("url", "host"):
        return False
    if observed_get(ev, "fresh") is False:
        return False
    age = observed_number(ev, "feed_age_s") if isinstance(ev.observed, Mapping) else None
    if age is not None:
        return 0 <= age < params.h2_max_feed_age_s
    return observed_get(ev, "fresh") is True


def h2_known_bad(present: Sequence[Evidence], params: ScoringParams) -> FiredRule | None:
    hits = [e for e in _by_signal(present, *FEED_SIGNALS) if _is_fresh_feed_hit(e, params)]
    if not hits:
        return None
    return FiredRule("H2", "floor_dangerous", tuple(e.id for e in hits))


def h3_verified_official(
    present: Sequence[Evidence],
    input_type: InputType,
    registrable_domain: str | None,
    verified_domains: Mapping[str, frozenset[str]] | None,
) -> FiredRule | None:
    if input_type != "url":
        return None
    official = [e for e in _by_signal(present, "registry.verified_official") if not untrusted_origin(e)]
    if not official:
        return None
    if _by_signal(present, "url.open_redirect_abuse") or _by_signal(present, *FEED_SIGNALS):
        return None
    if registrable_domain and verified_domains:
        all_verified: set[str] = set()
        for doms in verified_domains.values():
            all_verified |= doms
        if registrable_domain.lower() not in all_verified:
            return None
    return FiredRule("H3", "cap_no_warning_signs", tuple(e.id for e in official))


def _posts_to_bot(ev: Evidence) -> bool:
    if observed_get(ev, "bot") is True:
        return True
    kind = observed_get(ev, "target_kind")
    return isinstance(kind, str) and kind in BOT_TARGET_KINDS


def h4_exfil_to_bot(present: Sequence[Evidence]) -> FiredRule | None:
    bot_posts = [e for e in _by_signal(present, "page.cross_origin_post") if _posts_to_bot(e)]
    if not bot_posts:
        return None
    cred_forms = _by_signal(present, "page.cred_form")
    with_creds = [e for e in bot_posts if observed_get(e, "credentials") is True]
    if not with_creds and not cred_forms:
        return None
    ids = [e.id for e in (with_creds or bot_posts)] + [e.id for e in cred_forms]
    return FiredRule("H4", "floor_dangerous", tuple(dict.fromkeys(ids)))


def _link_verdict(e: Evidence) -> str | None:
    v = e.observed if isinstance(e.observed, str) else observed_get(e, "verdict")
    return v if isinstance(v, str) else None


def h5_message_dangerous_link(present: Sequence[Evidence]) -> FiredRule | None:
    """A message/email is at least as severe as its worst child link: dangerous child -> dangerous (floor),
    suspicious child -> at least suspicious. Cites the child verdict evidence."""
    links = _by_signal(present, *LINK_VERDICT_SIGNALS)
    bad = [e for e in links if _link_verdict(e) == "dangerous"]
    if bad:
        return FiredRule("H5", "floor_dangerous", tuple(e.id for e in bad))
    warn = [e for e in links if _link_verdict(e) == "suspicious"]
    if warn:
        return FiredRule("H5", "floor_suspicious", tuple(e.id for e in warn))
    return None


def h6_otp_remote_access(present: Sequence[Evidence]) -> FiredRule | None:
    asks = _by_signal(present, "message.rule.otp_request", "message.rule.remote_access")
    imp = _by_signal(present, *IMPERSONATION_SIGNALS)
    if not asks or not imp:
        return None
    return FiredRule("H6", "floor_suspicious", tuple(e.id for e in [*asks, *imp]))


def evaluate(
    present: Sequence[Evidence],
    params: ScoringParams,
    input_type: InputType = "url",
    registrable_domain: str | None = None,
    verified_domains: Mapping[str, frozenset[str]] | None = None,
) -> HardRuleOutcome:
    """Evaluate all hard rules. H3 (verified official) overrides every risk floor it co-occurs with.

    H3 cannot co-occur with H2 (a feed hit disables H3 by definition).
    """
    candidates = [
        h2_known_bad(present, params),
        h1_brand_mismatch(present, params, registrable_domain, verified_domains),
        h4_exfil_to_bot(present),
        h5_message_dangerous_link(present),
        h6_otp_remote_access(present),
    ]
    risk = tuple(r for r in candidates if r is not None)
    h3 = h3_verified_official(present, input_type, registrable_domain, verified_domains)
    if h3 is None:
        return HardRuleOutcome(fired=risk, suppressed=())
    return HardRuleOutcome(fired=(h3,), suppressed=risk)
