# ruff: noqa: E501  (copy and tables read better unwrapped)
"""The copy shared by the deck and the description document.

Rules this module enforces by construction (CLAUDE.md):
- A line tied to a capability is marked PLANNED unless that capability is shipped in this
  checkout (scripts/submission/capabilities.py). Unshipped capabilities also appear on the
  roadmap automatically.
- No number is typed here. The results section copies values verbatim from the newest
  published eval artifact, or says "Evaluation in progress".
- No statistic about the problem is quoted, because none has a public source link attached.
- The product is never described as "safe", and no relationship with a police body is implied.

Standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from submission import artifact as artifact_mod
from submission import capabilities as caps_mod

TITLE = "Falcon Lens | عدسة الصقر"
TAGLINE_EN = "Check before you tap."
TAGLINE_AR = "افحص قبل أن تضغط"
PROMISE_EN = "Paste anything suspicious and get a clear answer in Arabic: what we found, why, and what to do now."
PROMISE_AR = "الصق ما تشكّ فيه، فنقول لك بوضوح: ماذا وجدنا، ولماذا، وماذا تفعل الآن."
DISCLAIMER_EN = (
    "Falcon Lens is an independent hackathon project. It is not affiliated with or endorsed by Abu Dhabi Police, "
    "uses no police branding, and is not connected to any police system."
)
DISCLAIMER_AR = "عدسة الصقر مشروع مستقل لمسابقة، غير تابع لشرطة أبوظبي ولا يمثّلها، وغير مربوط بأي نظام شرطي."
PRE_MVP_BANNER = (
    "Build status: the end-to-end check is not finished in this build. Lines marked PLANNED describe the design, "
    "not a working feature."
)
PLANNED = "PLANNED"
NO_RESULTS = (
    f"{artifact_mod.NO_ARTIFACT}. No number is shown until `make eval` has written an artifact and a copy is in "
    "evals/results/published/."
)
MAX_RESULT_ROWS = 10


@dataclass(frozen=True)
class Line:
    text: str
    cap: str | None = None  # capability id the line depends on; None = always true
    planned: bool = False  # filled in by build()


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    lead: str = ""
    lines: tuple[Line, ...] = ()
    note: str = ""
    table: tuple[tuple[str, str], ...] = ()  # (label, value) rows, results only
    extra: dict[str, str] = field(default_factory=dict)


def _mark(lines: tuple[Line, ...], caps: Mapping[str, bool]) -> tuple[Line, ...]:
    return tuple(
        Line(line.text, line.cap, planned=bool(line.cap) and not caps.get(line.cap or "", False)) for line in lines
    )


def _problem() -> Section:
    return Section(
        "problem",
        "The problem",
        lead="A blocklist can only list a scam page after someone has reported it.",
        lines=(
            Line(
                "The challenge targets fake fine, delivery-fee, bank one-time-code and UAE Pass links sent by SMS, WhatsApp and email."
            ),
            Line("A page that copies an official site and has not been reported yet is on no blocklist."),
            Line("A warning written in English and in security jargon is hard to act on for a reader of neither."),
            Line("People need one clear answer in Arabic: is this a scam, why, and what do I do now?"),
        ),
        note="No statistic and no measured claim about scams is made here: a figure appears in this project only with a public source link.",
    )


def _solution() -> Section:
    return Section(
        "solution",
        "The solution",
        lead=PROMISE_EN,
        lines=(
            Line("Checks a link and streams an evidence-backed verdict as each check tier finishes.", "url_check"),
            Line(
                "Checks SMS and chat text in Arabic, Arabizi and English; every link inside is checked too.",
                "message_check",
            ),
            Line("Checks an email file without fetching anything remote.", "email_check"),
            Line("Checks a screenshot or QR code.", "image_check"),
            Line(
                "Three verdicts: Dangerous, Suspicious, No warning signs found. The lowest one always carries a caution reminder.",
                "url_check",
            ),
            Line(
                "Every reason cites the evidence behind it, with what to do now and what to do if you already clicked.",
                "url_check",
            ),
            Line("Installable Arabic-first web app; Android can share a message straight into it.", "share_target"),
            Line("A second agent, the Sentinel, links single checks into campaigns and incidents.", "sentinel_agent"),
        ),
        extra={"promise_ar": PROMISE_AR, "verdicts_ar": "خطِر · مريب · لم نجد علامات تحذير"},
    )


def _demo() -> Section:
    return Section(
        "demo",
        "Demo flow",
        lead="Recording rule: real screen, real voice. Phishing scenarios use only snapshots and the invented brand Falcon Demo Bank.",
        lines=(
            Line("A phishing URL from a feed, replayed from a stored snapshot: Dangerous.", "url_check"),
            Line("A Falcon Demo Bank lookalike that no blocklist knows: caught by the brand check.", "brand_check"),
            Line("An Arabic scam SMS: verdict, reasons and next steps in Arabic.", "message_check"),
            Line("A fictional phishing email file.", "email_check"),
            Line("A verified official site: No warning signs found, with a caution reminder.", "verified_official"),
            Line("A page with injected instructions: the verdict does not change.", "injection_defence"),
            Line(
                "Sentinel: a planted campaign in a replay opens an incident; a takedown draft waits for approval.",
                "sentinel_agent",
            ),
            Line("A command-line client calls the MCP server.", "mcp"),
            Line("A phone shares a message into the installed app.", "share_target"),
        ),
        note="The demo is a script, not a recording yet. A scene is recorded only when its line here is not marked PLANNED. Full script: docs/DEMO.md.",
    )


def _architecture() -> Section:
    return Section(
        "architecture",
        "Architecture",
        lead="Design: one gateway, a tiered worker, an isolated browser sandbox, and an event stream that feeds the Sentinel.",
        lines=(
            Line("Gateway to API; jobs and verdict events travel on Redis streams.", "pipeline"),
            Line("Worker cascade T0 to T3 exits as early as the evidence allows.", "url_check"),
            Line(
                "The sandbox reaches the internet only through the egress proxy and returns features only.",
                "brand_check",
            ),
            Line("PostgreSQL stores verdicts and their evidence.", "pipeline"),
            Line("Incidents and every Sentinel action go to an append-only audit log.", "audit_log"),
            Line("Metrics, logs and traces flow to dashboards and alerts.", "observability"),
        ),
    )


def _agent() -> Section:
    return Section(
        "agent",
        "Inside the agent",
        lead="Models read and explain. Code decides.",
        lines=(
            Line(
                "Tiered cascade: known lists, then URL and domain signals, then an isolated page visit, then the AI investigator only for the uncertain band.",
                "url_check",
            ),
            Line("A deterministic arbiter is the only component that sets the score and the verdict.", "url_check"),
            Line(
                "Brand-mismatch rule H1: a page that claims a brand, asks for credentials and sits on a domain the brand does not own is Dangerous.",
                "brand_check",
            ),
            Line(
                "Untrusted text is delimited and datamarked, and read only by a quarantined extractor that has no tools.",
                "injection_defence",
            ),
            Line(
                "The investigator is a bounded state machine with typed tools and a provenance check on every URL argument.",
                "investigator",
            ),
            Line(
                "Sentinel: deterministic rules open incidents; a LangGraph agent enriches them and stops for a human before any external action.",
                "sentinel_agent",
            ),
        ),
    )


def _results(artifact: artifact_mod.Artifact | None) -> Section:
    if artifact is None:
        return Section(
            "results",
            "Results",
            lead=NO_RESULTS,
            note="Method: docs/EVALS.md (temporal split, frozen test split, bootstrap confidence intervals).",
        )
    metrics = artifact.metrics
    if any(key.startswith("test.") for key, _ in metrics):  # the frozen test split is the headline
        metrics = [(key, value) for key, value in metrics if key.startswith("test.")]
    intervals = {key: value for key, value in metrics if key.endswith("_ci95")}
    rows_list = []
    for key, value in metrics:
        if key in intervals:
            continue
        shown = artifact_mod.show(value)
        if f"{key}_ci95" in intervals:
            shown += f"   ci95 {artifact_mod.show(intervals[f'{key}_ci95'])}"
        rows_list.append((key, shown))
    rows = tuple(rows_list[:MAX_RESULT_ROWS])
    provenance = " · ".join(f"{key}: {artifact_mod.show(value)}" for key, value in artifact.provenance)
    note = (
        f"Source: evals/results/published/{artifact.path.name}. Values are copied verbatim; "
        "ci95 is the bootstrap interval from the same file."
    )
    if len(artifact.metrics) > len(metrics) or len(rows_list) > len(rows):
        note += " More metrics are in the artifact."
    if not rows:
        return Section(
            "results",
            "Results",
            lead=f"{artifact_mod.NO_ARTIFACT}. The published artifact has no `metrics` object yet.",
            note=note,
        )
    if artifact.scope:
        scope = (
            f"Scope of this run, in the artifact's words: {artifact.scope}. It is not a measurement of the full system."
        )
    else:
        scope = "Measured by `make eval`."
    extra = {"provenance": provenance}
    if artifact.not_evaluated:
        extra["not_evaluated"] = "Not evaluated yet: " + ", ".join(artifact.not_evaluated) + "."
    return Section("results", "Results", lead=scope, table=rows, note=note, extra=extra)


def _security() -> Section:
    return Section(
        "security",
        "Security and sovereignty",
        lead="The checker fetches content that attackers control, so it is designed as a target.",
        lines=(
            Line(
                "A page cannot talk the model into lowering a score: model output never reaches the score.",
                "injection_defence",
            ),
            Line(
                "SSRF guard: own DNS resolution, blocked private ranges, pinned address, every redirect re-checked.",
                "url_check",
            ),
            Line(
                "Suspicious pages load once, passively, in an isolated browser. No form is ever submitted.",
                "brand_check",
            ),
            Line("Personal data is redacted before logging and before any cloud call.", "sovereign"),
            Line("Sovereign mode: every model call stays on the local machine.", "sovereign"),
            Line(
                "The product never asks for personal, banking or ID details, and its lowest verdict is never worded as a guarantee.",
                "url_check",
            ),
        ),
    )


def _integration() -> Section:
    return Section(
        "integration",
        "Integration with police systems",
        lead="Ready to connect, not connected.",
        lines=(
            Line("REST interface with an OpenAPI description.", "rest_api"),
            Line("MCP server so another agent can call the checks as tools.", "mcp"),
            Line("STIX export of incident indicators.", "stix"),
            Line("Operator board: the Sentinel proposes, a human approves or rejects.", "ops_board"),
            Line("External actions are drafts only. Nothing is sent to a third party by the system.", "sentinel_agent"),
        ),
        note="No integration with Abu Dhabi Police exists and none is implied. A real connection needs an agreement with the receiving organisation.",
    )


def _deployment(artifact: artifact_mod.Artifact | None) -> Section:
    cost = [(k, v) for k, v in (artifact.metrics if artifact else []) if "cost" in k.lower()]
    cost_line = (
        "Measured cost per check: "
        + "; ".join(f"{k} = {artifact_mod.show(v)}" for k, v in cost[:3])
        + " (from the published artifact)."
        if cost
        else "Cost per check: evaluation in progress. No cost figure is shown until an eval artifact reports one."
    )
    return Section(
        "deployment",
        "Deployment and cost",
        lead="Designed to start with one command on a laptop.",
        lines=(
            Line(
                "Docker Compose starts the gateway, API, worker, sandbox, Sentinel, data store and observability containers.",
                "stack",
            ),
            Line(
                "Most checks are meant to finish in the deterministic tiers; a model is called only for the uncertain band.",
                "url_check",
            ),
            Line("With no cloud key, or in sovereign mode, every model call goes to a local model.", "sovereign"),
            Line("Every external key is optional: a missing key switches that feature off.", "stack"),
            Line(cost_line),
        ),
    )


STATIC_ROADMAP = (
    "A production deployment needs an OpenPhish licence: the community feed allows research use only.",
    "More reputation feeds when keys are available.",
    "Sandbox hardening on a Linux host, and mobile or residential egress to reduce cloaking.",
    "iPhone share flow through an iOS Shortcut (iOS has no share target for web apps).",
    "Any real connection to a police system, under an agreement with that organisation.",
)


def _roadmap(caps: Mapping[str, bool]) -> Section:
    labels = [cap.label.split(" (")[0] for cap in caps_mod.CAPABILITIES if not caps.get(cap.id) and cap.id != "evals"]
    step = 1 if len(labels) <= 4 else 4
    unbuilt = tuple(
        Line("Not built yet: " + "; ".join(labels[i : i + step]) + ".") for i in range(0, len(labels), step)
    )
    return Section(
        "roadmap",
        "Roadmap",
        lead="What is not in this build, stated plainly.",
        lines=unbuilt + tuple(Line(text) for text in STATIC_ROADMAP),
    )


def _team(repo_url: str) -> Section:
    return Section(
        "team",
        "Team",
        lead="Placeholder names: the owner fills these in before submitting.",
        lines=(
            Line("[Team member name], [role]"),
            Line("[Team member name], [role]"),
            Line("[Team member name], [role]"),
        ),
        note=DISCLAIMER_EN,
        extra={"repo_url": repo_url, "disclaimer_ar": DISCLAIMER_AR},
    )


def build(caps: Mapping[str, bool], artifact: artifact_mod.Artifact | None, repo_url: str) -> list[Section]:
    """The eleven sections, in deck order, with PLANNED marks resolved."""
    sections = [
        _problem(),
        _solution(),
        _demo(),
        _architecture(),
        _agent(),
        _results(artifact),
        _security(),
        _integration(),
        _deployment(artifact),
        _roadmap(caps),
        _team(repo_url),
    ]
    return [Section(s.key, s.title, s.lead, _mark(s.lines, caps), s.note, s.table, s.extra) for s in sections]


def mvp_shipped(caps: Mapping[str, bool]) -> bool:
    return bool(caps.get("url_check"))


def all_text(sections: list[Section]) -> str:
    parts: list[str] = []
    for s in sections:
        parts += [
            s.title,
            s.lead,
            s.note,
            *(line.text for line in s.lines),
            *(f"{k} {v}" for k, v in s.table),
            *s.extra.values(),
        ]
    return "\n".join(p for p in parts if p)
