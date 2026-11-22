# ruff: noqa: E501
"""Scam-script retrieval with a fake Ollama and a fake pgvector connection (no DB, no network)."""

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from falcon_core.signals import REGISTRY
from falcon_core.signals.message.scripts import (
    EmbedDimMismatch,
    EmbedError,
    OllamaEmbedder,
    ScriptStore,
    ddl,
    load_scripts,
    read_jsonl,
    script_match,
)

DIM = 4


class FakeResp:
    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self._d, self.status_code = data, status

    def json(self) -> dict[str, Any]:
        return self._d


class FakeHttp:
    def __init__(self, dim: int = DIM, status: int = 200) -> None:
        self.dim, self.status = dim, status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any]) -> FakeResp:
        self.calls.append((url, json))
        vecs = [
            [1.0 if "fine" in t else 0.0, 1.0 if "otp" in t else 0.0, 0.1, 0.0][: self.dim]
            + [0.0] * max(0, self.dim - 4)
            for t in json["input"]
        ]
        return FakeResp({"embeddings": vecs}, self.status)


class Cur:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[Any]:
        return self.rows


class FakeConn:
    """In-memory stand-in: stores rows, answers the kNN query with cosine similarity."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, Sequence[Any] | None]] = []
        self.rows: dict[str, tuple[str, list[float]]] = {}

    async def execute(self, query: str, params: Sequence[Any] | None = None) -> Cur:
        self.executed.append((query, params))
        if query.startswith("INSERT") and params:
            self.rows[params[0]] = (params[1], json.loads(params[3]))
        if query.startswith("SELECT") and params:
            q = json.loads(params[0])
            out = []
            for i, (lab, v) in self.rows.items():
                dot = sum(a * b for a, b in zip(q, v, strict=True))
                n = math.sqrt(sum(a * a for a in q)) * math.sqrt(sum(a * a for a in v)) or 1.0
                out.append((i, lab, dot / n))
            out.sort(key=lambda r: -r[2])
            return Cur(out[: params[2]])
        return Cur([])


def jsonl(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    p = tmp_path / "scripts.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


ROWS = [
    {
        "id": "s1",
        "label": "fake_fine",
        "lang": "ar",
        "text": "fine مخالفة",
        "source": "synthetic-test",
        "synthetic": True,
    },
    {
        "id": "s2",
        "label": "otp_theft",
        "lang": "en",
        "text": "otp code",
        "source": "synthetic-test",
        "synthetic": True,
    },
]


def test_ddl_has_expected_columns_and_dim() -> None:
    d = ddl(2560)
    assert "vector(2560)" in d and "scam_scripts" in d and "synthetic boolean" in d
    with pytest.raises(ValueError):
        ddl("2560; DROP TABLE x")  # type: ignore[arg-type]


async def test_embedder_calls_api_embed_and_checks_dim() -> None:
    http = FakeHttp()
    emb = OllamaEmbedder(http, "http://ollama.test:11434/", model="m", dim=DIM)
    (v,) = await emb.embed(["هلا otp"])
    assert len(v) == DIM
    assert (
        http.calls[0][0] == "http://ollama.test:11434/api/embed"
        and http.calls[0][1]["model"] == "m"
    )
    assert await emb.verify_dimension() == DIM
    with pytest.raises(EmbedDimMismatch):
        await OllamaEmbedder(http, "http://ollama.test", dim=DIM + 1).embed(["x"])
    with pytest.raises(EmbedError):
        await OllamaEmbedder(FakeHttp(status=500), "http://ollama.test", dim=DIM).embed(["x"])


def test_embedder_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_EMBED_MODEL", "qwen3-embedding:4b")
    monkeypatch.setenv("FL_EMBED_DIM", "2560")
    e = OllamaEmbedder(None, "http://x.test")
    assert (e.model, e.dim) == ("qwen3-embedding:4b", 2560)


async def test_loader_seeds_and_keeps_synthetic(tmp_path: Path) -> None:
    conn = FakeConn()
    store = ScriptStore(conn, DIM)
    n = await load_scripts(
        store, OllamaEmbedder(FakeHttp(), "http://o.test", dim=DIM), jsonl(tmp_path, ROWS)
    )
    assert n == 2 and set(conn.rows) == {"s1", "s2"}
    inserts = [p for q, p in conn.executed if q.startswith("INSERT")]
    assert all(p is not None and p[5] is True for p in inserts)  # synthetic kept


def test_loader_rejects_incomplete_rows(tmp_path: Path) -> None:
    bad = {k: v for k, v in ROWS[0].items() if k != "synthetic"}
    with pytest.raises(ValueError):
        read_jsonl(jsonl(tmp_path, [bad]))
    with pytest.raises(ValueError):
        read_jsonl(jsonl(tmp_path, [{**ROWS[0], "synthetic": "yes"}]))


async def test_script_match_threshold_and_privacy(tmp_path: Path) -> None:
    conn = FakeConn()
    store = ScriptStore(conn, DIM)
    emb = OllamaEmbedder(FakeHttp(), "http://o.test", dim=DIM)
    await load_scripts(store, emb, jsonl(tmp_path, ROWS))
    ev = await script_match("pay this fine now", emb, store, theta=0.9)
    assert len(ev) == 1 and ev[0].signal == "message.script_match"
    m = ev[0].observed["matches"]
    assert (
        m[0]["id"] == "s1"
        and m[0]["label"] == "fake_fine"
        and set(m[0]) == {"id", "label", "similarity"}
    )
    assert "pay this fine" not in json.dumps(ev[0].observed)
    assert await script_match("hello", emb, store, theta=0.99) == []
    assert await script_match("pay this fine now", emb, store, theta=1.01) == []


async def test_theta_configurable_via_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    conn = FakeConn()
    store = ScriptStore(conn, DIM)
    emb = OllamaEmbedder(FakeHttp(), "http://o.test", dim=DIM)
    await load_scripts(store, emb, jsonl(tmp_path, ROWS))
    monkeypatch.setenv("FL_SCRIPT_MATCH_THETA", "1.5")
    assert await script_match("fine", emb, store) == []
    monkeypatch.setenv("FL_SCRIPT_MATCH_THETA", "0.1")
    assert await script_match("fine", emb, store)


def test_knn_sql_returns_only_id_label_similarity() -> None:
    conn = FakeConn()
    asyncio.run(ScriptStore(conn, DIM).knn([0.1] * DIM, 3))
    q = conn.executed[-1][0]
    assert (
        q.startswith("SELECT id, label, 1 - (embedding <=> ") and "text" not in q.split("FROM")[0]
    )


@dataclass
class Ctx:
    text: str | None = "x"
    url: str | None = None
    input_type: str = "message"
    http: Any = None
    cache: Any = None
    mirror: Any = None
    clock: Any = None
    brands: Any = None


async def test_registered_signal_degrades_without_store_and_never_raises() -> None:
    out = await REGISTRY["message.script_match"][1](Ctx())
    assert out[0].error and out[0].confidence == 0.0

    class Boom:
        async def post(self, *a: Any, **k: Any) -> None:
            raise ConnectionError("down")

    c = Ctx(http=Boom())
    c.scripts = ScriptStore(FakeConn(), DIM)  # type: ignore[attr-defined]
    c.ollama_base_url = "http://o.test"  # type: ignore[attr-defined]
    out = await REGISTRY["message.script_match"][1](c)
    assert "ConnectionError" in (out[0].error or "")


async def test_registered_signal_timeout() -> None:
    class Slow:
        async def post(self, *a: Any, **k: Any) -> None:
            await asyncio.sleep(10)

    c = Ctx(http=Slow())
    c.scripts = ScriptStore(FakeConn(), DIM)  # type: ignore[attr-defined]
    c.ollama_base_url = "http://o.test"  # type: ignore[attr-defined]
    spec, fn = REGISTRY["message.script_match"]
    object.__setattr__(spec, "timeout_ms", 50)
    try:
        out = await fn(c)
    finally:
        object.__setattr__(spec, "timeout_ms", 3000)
    assert out[0].error == "timeout"
