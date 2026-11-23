# ruff: noqa: S603, S607, S310
"""The real collector config strips everything that is not allow-listed (privacy gate).

The collector runs from the repo's image (skipped without Docker or the image). The pipeline
processors are taken from infra/otel/otel-collector.yml unchanged; only the exporter is swapped for
a file exporter so the test can read what would have reached Phoenix.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from falcon_core.telemetry import tracing

ROOT = Path(__file__).resolve().parents[4]
CONFIG = ROOT / "infra" / "otel" / "otel-collector.yml"
IMAGE = "falcon-lens/otel-collector:0.165.0"

LEAK_KEYS = {
    "gen_ai.tool.call.arguments": "SECRET-ARGS",
    "anthropic.tool_result.content": "SECRET-TOOL-RESULT",
    "llm.input_messages.0.message.content": "SECRET-PROMPT",
    "gen_ai.prompt.0.content": "SECRET-PROMPT-2",
    "input.value": "SECRET-IN",
    "output.value": "SECRET-OUT",
    "url.full": "http://user:pw@evil.example/login",
    "url.path": "/v1/messages",
    "http.url": "http://evil.example/x",
}


def _cfg() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_allowlist_is_pinned_to_the_code() -> None:
    cfg = _cfg()
    stmts = {s["context"]: s["statements"] for s in cfg["processors"]["transform/allowlist"]["trace_statements"]}
    span_keys = set(yaml.safe_load("[" + stmts["span"][0].split("[", 1)[1].rsplit("]", 1)[0] + "]"))
    res_keys = set(yaml.safe_load("[" + stmts["resource"][0].split("[", 1)[1].rsplit("]", 1)[0] + "]"))
    assert span_keys == set(tracing.COLLECTOR_ALLOWED_ATTRIBUTES)
    assert res_keys == set(tracing.COLLECTOR_ALLOWED_RESOURCE)
    assert not [k for k in span_keys if k.startswith(("url.", "http.url", "input.", "output."))]
    assert not [k for k in span_keys if "content" in k or "message" in k or "arguments" in k]
    assert cfg["service"]["pipelines"]["traces"]["processors"] == [
        "filter/probes",
        "filter/events",
        "transform/allowlist",
        "batch",
    ]


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return r.returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker or the collector image is not available")
def test_real_collector_drops_leak_keys_and_events(tmp_path: Path) -> None:
    cfg = _cfg()
    cfg["exporters"] = {"file": {"path": "/out/traces.json"}}
    cfg["service"]["pipelines"] = {
        "traces": {
            "receivers": ["otlp"],
            "processors": cfg["service"]["pipelines"]["traces"]["processors"],
            "exporters": ["file"],
        }
    }
    cfg["service"]["telemetry"] = {"metrics": {"level": "none"}}
    (tmp_path / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o777)
    name = f"fl-otel-allowlist-{time.time_ns()}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::4318",
            "-v", f"{tmp_path / 'config.yml'}:/etc/otelcol/config.yml:ro", "-v", f"{out}:/out",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    try:
        port = subprocess.run(
            ["docker", "port", name, "4318/tcp"], check=True, capture_output=True, text=True
        ).stdout.split(":")[-1].strip()  # fmt: skip
        attrs = [{"key": k, "value": {"stringValue": v}} for k, v in LEAK_KEYS.items()]
        attrs += [
            {"key": "fl.tier", "value": {"stringValue": "T2"}},
            {"key": "verdict_id", "value": {"stringValue": "vd_1"}},
            {"key": "llm.token_count.prompt", "value": {"intValue": "7"}},
        ]
        body = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "worker"}},
                            {"key": "host.name", "value": {"stringValue": "SECRET-HOST"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "x",
                                "attributes": [{"key": "k", "value": {"stringValue": "SECRET-SCOPE"}}],
                            },
                            "spans": [
                                {
                                    "traceId": "5b8efff798038103d269b633813fc60c",
                                    "spanId": "eee19b7ec3c1b174",
                                    "name": "cascade.T2",
                                    "kind": 1,
                                    "startTimeUnixNano": "1700000000000000000",
                                    "endTimeUnixNano": "1700000001000000000",
                                    "attributes": attrs,
                                    "status": {"code": 2, "message": "SECRET-STATUS"},
                                    "events": [
                                        {
                                            "name": "exception",
                                            "timeUnixNano": "1700000000500000000",
                                            "attributes": [
                                                {"key": "exception.message", "value": {"stringValue": "SECRET-EXC"}}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/traces",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        for _ in range(60):  # the collector needs a moment to listen
            try:
                urllib.request.urlopen(req, timeout=2).read()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("collector did not accept the span")
        f = out / "traces.json"
        for _ in range(40):
            if f.exists() and f.stat().st_size:
                break
            time.sleep(0.5)
        text = f.read_text(encoding="utf-8")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    assert "SECRET" not in text and "evil.example" not in text and "exception" not in text
    exported = json.loads(text.splitlines()[0])
    span = exported["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    keys = {a["key"] for a in span["attributes"]}
    assert keys == {"fl.tier", "verdict_id", "llm.token_count.prompt"}
    assert not span.get("events")
    res_keys = {a["key"] for a in exported["resourceSpans"][0]["resource"]["attributes"]}
    assert res_keys == {"service.name"}
