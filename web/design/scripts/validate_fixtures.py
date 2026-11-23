# /// script
# requires-python = ">=3.12"
# dependencies = ["jsonschema>=4.23", "referencing>=0.35"]
# ///
"""Validate the prototype's fixtures against the contracts.

Checks, for web/design/prototype/index.html:
  * every final verdict and every simulated partial verdict validates against
    contracts/verdict.schema.json (evidence against evidence.schema.json);
  * the incident validates against contracts/incident.schema.json;
  * reasons cite only evidence ids present in the same verdict (CONTRACTS invariant);
  * `no_warning_signs` carries `actions.caution`;
  * every URL-like string is defanged and uses a reserved TLD (.test / .invalid),
    except the official reporting channels copied from config/reporting_channels.yaml;
  * no user-facing string contains the word "safe" (Latin) or "آمن" (Arabic).

Usage: uv run web/design/scripts/validate_fixtures.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
PROTOTYPE = ROOT / "web" / "design" / "prototype" / "index.html"
TIERS = ["T0", "T1", "T2", "T3"]
OFFICIAL_CHANNEL_HOSTS = ("adpolice.gov.ae",)


def load_schema(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    return data


def registry() -> Registry[Any]:
    reg: Registry[Any] = Registry()
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        reg = reg.with_resource(schema["$id"], Resource.from_contents(schema))
    return reg


def strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in strings(value)]
    return []


def partials(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Mirror of `partial()` in the prototype: one verdict per completed tier."""
    final: dict[str, Any] = scene["final"]
    out: list[dict[str, Any]] = []
    stream: list[dict[str, Any]] = scene["stream"]
    for index, step in enumerate(stream):
        last = index == len(stream) - 1
        upto = TIERS.index(step["tier"])
        out.append(
            {
                **final,
                "verdict": step["verdict"],
                "risk_score": step["risk_score"],
                "calibrated_probability": step["calibrated_probability"],
                "tier_reached": step["tier"],
                "latency_ms": step["latency_ms"],
                "evidence": [
                    e for e in final["evidence"] if TIERS.index(e["tier"]) <= upto
                ],
                "reasons": final["reasons"] if last else [],
                "final": last,
            }
        )
    return out


def main() -> int:
    html = PROTOTYPE.read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" id="fl-fixtures">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        print("FAIL fixtures block not found")
        return 2
    fixtures: dict[str, Any] = json.loads(match.group(1))
    errors: list[str] = []
    reg = registry()
    verdict_validator = Draft202012Validator(
        load_schema("verdict.schema.json"), registry=reg
    )
    incident_validator = Draft202012Validator(
        load_schema("incident.schema.json"), registry=reg
    )

    checked = 0
    for name, scene in fixtures["scenes"].items():
        scene["final"]["actions"]["report"]["channels"] = fixtures["channels"]["items"]
        stream = partials(scene)
        if stream[-1] != scene["final"]:
            errors.append(
                f"{name}: last stream step does not reproduce the final verdict"
            )
        for index, verdict in enumerate(stream):
            checked += 1
            for err in verdict_validator.iter_errors(verdict):
                errors.append(
                    f"{name}[{index}] schema: {'/'.join(map(str, err.path))}: {err.message}"
                )
            ids = {e["id"] for e in verdict["evidence"]}
            for reason in verdict["reasons"]:
                missing = set(reason["evidence_ids"]) - ids
                if missing:
                    errors.append(
                        f"{name}[{index}] reason cites unknown evidence: {sorted(missing)}"
                    )
            if (
                verdict["final"]
                and verdict["verdict"] == "no_warning_signs"
                and not verdict["actions"].get("caution")
            ):
                errors.append(
                    f"{name}[{index}] no_warning_signs without actions.caution"
                )
            if verdict["degraded"] and verdict["verdict"] == "no_warning_signs":
                errors.append(
                    f"{name}[{index}] degraded verdict shown as no_warning_signs"
                )
            if len(verdict["reasons"]) > 3:
                errors.append(f"{name}[{index}] more than three reasons")

    for err in incident_validator.iter_errors(fixtures["incident"]):
        errors.append(f"incident schema: {'/'.join(map(str, err.path))}: {err.message}")

    for text in strings(fixtures):
        if any(host in text for host in OFFICIAL_CHANNEL_HOSTS):
            continue
        if re.search(r"https?://", text):
            errors.append(f"live-looking URL (not defanged): {text!r}")
        for host in re.findall(
            r"[a-z0-9-]+(?:\[\.\]|\.)(?:test|invalid|com|net|org|ae)\b", text
        ):
            if "[.]" not in host or not host.endswith((".test", "]test", "]invalid")):
                errors.append(f"host is not a defanged reserved-TLD name: {host!r}")

    # User-facing copy: the fixtures plus the STR tables in the prototype script.
    script = html[html.index('"use strict";') :]
    for label, text in (
        ("fixtures", match.group(1)),
        ("strings", script[: script.index("const t = (k)")]),
    ):
        if re.search(r"\b(un)?safe(ly|ty)?\b", text, re.IGNORECASE):
            errors.append(f'{label}: contains the word "safe"')
        if re.search(r"(?<![؀-ۿ])(ال)?آمن(ة)?(?![؀-ۿ])", text):
            errors.append(f'{label}: contains the Arabic word "آمن"')

    for line in errors:
        print("FAIL", line)
    print(f"{checked} verdict events and 1 incident checked; failures: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
