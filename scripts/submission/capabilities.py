# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Detect which product capabilities are present in this checkout.

Truthfulness rule (CLAUDE.md): the submission may only describe what ships. Every claim in
the descriptions, the deck and the description document is tied to a capability id below,
and a capability counts as shipped only when all of its probes hold in the working tree.

Probes are NECESSARY conditions, not proof that the feature works: a file can exist while
the feature is broken. CHECKLIST.md therefore lists every capability with its probes and
asks the owner to confirm each one on the running stack before submitting.

Probe kinds:
    path:<glob>           at least one file matches (relative to the repo root)
    make:<target>         the Makefile target exists and is not the "not yet implemented" stub
    grep:<glob>::<regex>  at least one matching file contains the regex
    nogrep:<glob>::<regex>  at least one file matches the glob and none contains the regex
                          (used to detect that a "not supported yet" stub is gone)

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = "packages/falcon_core/src/falcon_core"


@dataclass(frozen=True)
class Capability:
    id: str
    label: str  # short English name used in the checklist, deck and document
    probes: tuple[str, ...]
    demo: str = ""  # DEMO.md section that proves it on the running stack


# The end-to-end check: `make smoke` is real, and the cascade and the arbiter are in the tree.
# Every capability that needs a verdict includes these probes.
E2E = (
    "make:smoke",
    f"path:{CORE}/cascade/engine.py",
    f"path:{CORE}/scoring/arbiter.py",
    "path:services/worker/src/falcon_worker/consumer.py",
    "grep:services/sandbox/src/**/*.py::playwright",  # the sandbox is a real browser service, not the health-only stub
)
# The worker answers non-URL inputs with a degraded "not supported yet" verdict until it handles them.
WORKER_KIND_STUB = r"nogrep:services/worker/src/**/*.py::input_type_not_supported_yet"

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "url_check",
        "URL check, end to end (paste a link, get a verdict)",
        E2E,
        "Scenario 1",
    ),
    Capability(
        "brand_check",
        "Brand check H1 (lookalike page caught with no blocklist)",
        (
            *E2E,
            f"path:{CORE}/scoring/hard_rules.py",
            "grep:services/sandbox/src/**/*.py::playwright",
        ),
        "Scenario 2",
    ),
    Capability(
        "message_check",
        "Message check (SMS and chat text, Arabic and English)",
        (*E2E, f"path:{CORE}/signals/message/analyze.py", "grep:services/api/src/**/*.py::check/message", WORKER_KIND_STUB),
        "Scenario 3",
    ),
    Capability(
        "email_check",
        "Email check (.eml)",
        (*E2E, f"path:{CORE}/signals/email/analyze.py", "grep:services/api/src/**/*.py::check/email", WORKER_KIND_STUB),
        "Scenario 4",
    ),
    Capability(
        "image_check",
        "Image and QR check",
        (*E2E, f"path:{CORE}/signals/image/analyze.py", "grep:services/api/src/**/*.py::check/image", WORKER_KIND_STUB),
    ),
    Capability(
        "verified_official",
        "Verified-official rule H3 (lowest verdict is never worded as a guarantee)",
        (*E2E, f"path:{CORE}/scoring/hard_rules.py", "path:data/brands.yaml"),
        "Scenario 5",
    ),
    Capability(
        "injection_defence",
        "Injection defence (spotlighting, quarantined extractor, code-only scoring)",
        (*E2E, f"path:{CORE}/llm/spotlight.py", f"path:{CORE}/agent/extractor.py"),
        "Scenario 6",
    ),
    Capability(
        "investigator",
        "Bounded AI investigator for the uncertain band (T3)",
        (*E2E, f"path:{CORE}/agent/investigator.py"),
    ),
    Capability(
        "sovereign",
        "Sovereign mode (every model call on the local machine)",
        (*E2E, f"path:{CORE}/llm/router.py"),
    ),
    Capability(
        "pipeline",
        "Job and verdict pipeline (Redis streams, verdicts and evidence stored in PostgreSQL)",
        (
            "path:services/worker/src/falcon_worker/consumer.py",
            "path:services/worker/src/falcon_worker/store.py",
            "path:services/worker/src/falcon_worker/migrations/*.sql",
            r"grep:services/api/src/**/*.py::xadd|fl:jobs",
        ),
    ),
    Capability(
        "stack",
        "One-command local stack (`make up`)",
        ("make:up", "path:docker-compose.yml", "path:.env.example"),
    ),
    Capability(
        "audit_log",
        "Incident store and append-only audit log",
        ("path:services/sentinel/src/falcon_sentinel/db.py", r"grep:services/sentinel/src/**/*.py::audit_log"),
    ),
    Capability(
        "sentinel_rules",
        "Sentinel correlation and trigger rules",
        ("path:services/sentinel/sentinel_core/rules.py", "path:services/sentinel/rules.yaml"),
    ),
    Capability(
        "sentinel_agent",
        "Sentinel agent (incidents, internal blocking, takedown drafts held for approval)",
        ("make:replay", "path:services/sentinel/src/falcon_sentinel/graph.py"),
        "Sentinel scene",
    ),
    Capability(
        "pwa",
        "Arabic-first web app (installable PWA)",
        (*E2E, "path:web/app/manifest.ts"),
        "Scenario 1",
    ),
    Capability(
        "share_target",
        "Android share sheet into the installed PWA",
        (*E2E, "path:web/app/manifest.ts", "path:web/app/share/route.ts"),
        "Phone scene",
    ),
    Capability(
        "ops_board",
        "Operator incident board with approve and reject",
        ("make:replay", "path:web/app/ops/page.tsx"),
        "Sentinel scene",
    ),
    Capability(
        "rest_api",
        "REST v1 with OpenAPI",
        (*E2E, "path:contracts/openapi.yaml"),
        "Scenario 1",
    ),
    Capability(
        "mcp",
        "MCP server (streamable HTTP, bearer auth)",
        (*E2E, r"grep:services/mcp/src/**/*.py::(@\w+\.tool|add_tool\()"),
        "CLI scene",
    ),
    Capability(
        "stix",
        "STIX 2.1 incident export",
        (f"path:{CORE}/tools/stix.py", "make:replay"),
    ),
    Capability(
        "observability",
        "Grafana dashboards and alert rules",
        ("path:infra/grafana/dashboards/*.json", "path:infra/prometheus/rules/*.yml"),
    ),
    Capability(
        "extension",
        "Chrome extension (Manifest V3)",
        ("path:extension/manifest.json",),
    ),
    Capability(
        "redteam",
        "Red-team suite (`make redteam`)",
        ("make:redteam",),
    ),
    Capability(
        "evals",
        "Published evaluation artifact",
        ("path:evals/results/published/*.json",),
    ),
)

BY_ID = {cap.id: cap for cap in CAPABILITIES}


def make_target_implemented(root: Path, target: str) -> bool:
    """True when `target:` exists in the Makefile and its recipe is not the NYI stub."""
    makefile = root / "Makefile"
    if not makefile.is_file():
        return False
    lines = makefile.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^{re.escape(target)}\s*:(?!=)", line):
            continue
        recipe: list[str] = []
        for body in lines[index + 1 :]:
            if body.startswith("\t"):
                recipe.append(body.strip())
            elif body.strip() == "" or body.startswith("#"):
                continue
            else:
                break
        text = "\n".join(recipe)
        return bool(recipe) and "$(NYI)" not in text and "not yet implemented" not in text
    return False


def probe(root: Path, spec: str) -> bool:
    kind, _, arg = spec.partition(":")
    if kind == "path":
        return any(True for _ in root.glob(arg))
    if kind == "make":
        return make_target_implemented(root, arg)
    if kind == "nogrep":
        pattern, _, regex = arg.partition("::")
        compiled = re.compile(regex)
        files = [path for path in root.glob(pattern) if path.is_file()]
        return bool(files) and not any(compiled.search(f.read_text(encoding="utf-8", errors="ignore")) for f in files)
    if kind == "grep":
        pattern, _, regex = arg.partition("::")
        compiled = re.compile(regex)
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                if compiled.search(path.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except OSError:
                continue
        return False
    raise ValueError(f"unknown probe kind in {spec!r}")


def detect(root: Path = ROOT) -> dict[str, bool]:
    """Capability id -> shipped (all probes hold)."""
    return {cap.id: all(probe(root, spec) for spec in cap.probes) for cap in CAPABILITIES}


def probe_report(root: Path = ROOT) -> list[tuple[Capability, bool, list[tuple[str, bool]]]]:
    rows = []
    for cap in CAPABILITIES:
        results = [(spec, probe(root, spec)) for spec in cap.probes]
        rows.append((cap, all(ok for _, ok in results), results))
    return rows
