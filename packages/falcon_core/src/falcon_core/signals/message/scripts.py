# ruff: noqa: E501
"""Scam-script retrieval: Ollama /api/embed client, pgvector store, JSONL loader, message.script_match.

Network: the embedder talks to the local Ollama server only through the injected ``http`` client
(``ctx.http``, an httpx-style async client). The store takes an async DB connection (psycopg
``AsyncConnection`` style: ``await conn.execute(sql, params)`` -> cursor with ``fetchall``). Only ids, labels
and similarity leave the store; script texts are never returned by the kNN query.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from falcon_core.signals.base import REGISTRY, Evidence, SignalContext, SignalSpec, _error
from falcon_core.signals.message.normalize import MAX_MESSAGE_CHARS, normalize

DEFAULT_THETA = 0.80  # configurable: FL_SCRIPT_MATCH_THETA or the ``theta`` argument; tune on evals
DEFAULT_MODEL = "qwen3-embedding:4b"
DEFAULT_DIM = 2560


class EmbedError(RuntimeError):
    pass


class EmbedDimMismatch(EmbedError):
    pass


def embed_settings() -> tuple[str, int]:
    return (
        os.environ.get("FL_EMBED_MODEL", DEFAULT_MODEL),
        int(os.environ.get("FL_EMBED_DIM", str(DEFAULT_DIM))),
    )


def prepare_for_embedding(text: str) -> str:
    """Normalised (Arabic-folded) text, capped to the message limit. Same function for scripts and queries."""
    return normalize(text[:MAX_MESSAGE_CHARS], collapse=False).text


class OllamaEmbedder:
    """POST {base}/api/embed {"model", "input": [...]} -> {"embeddings": [[...], ...]}."""

    def __init__(self, http: Any, base_url: str, model: str | None = None, dim: int | None = None) -> None:
        m, d = embed_settings()
        self.http, self.base_url = http, base_url.rstrip("/")
        self.model, self.dim = model or m, dim or d

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self.http.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": [prepare_for_embedding(t) for t in texts]},
        )
        if getattr(resp, "status_code", 200) != 200:
            raise EmbedError(f"embed http {resp.status_code}")
        vecs = resp.json().get("embeddings")
        if not isinstance(vecs, list) or len(vecs) != len(texts):
            raise EmbedError("embed response shape")
        for v in vecs:
            if len(v) != self.dim:
                raise EmbedDimMismatch(f"model returned dim {len(v)}, FL_EMBED_DIM is {self.dim}")
        return [[float(x) for x in v] for v in vecs]

    async def verify_dimension(self) -> int:
        """Runtime check at startup: embeds a probe and requires len == FL_EMBED_DIM."""
        (v,) = await self.embed(["dimension probe"])
        return len(v)


class Cursor(Protocol):
    async def fetchall(self) -> list[Any]: ...


class Conn(Protocol):
    async def execute(self, query: str, params: Sequence[Any] | None = None) -> Cursor: ...


def ddl(dim: int) -> str:
    """pgvector table. No ANN index: pgvector's hnsw/ivfflat cap at 2000 dims for ``vector`` and the table
    is small (hundreds of rows), so kNN is an exact scan."""
    dim = int(dim)
    return (
        "CREATE EXTENSION IF NOT EXISTS vector;\n"
        "CREATE TABLE IF NOT EXISTS scam_scripts (\n"
        "  id text PRIMARY KEY, label text NOT NULL, lang text NOT NULL,\n"
        f"  embedding vector({dim}) NOT NULL, source text NOT NULL, synthetic boolean NOT NULL);"
    )


def to_pgvector(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


@dataclass(frozen=True)
class ScriptMatch:
    id: str
    label: str
    similarity: float


class ScriptStore:
    def __init__(self, conn: Conn, dim: int | None = None) -> None:
        self.conn, self.dim = conn, dim or embed_settings()[1]

    async def create_schema(self) -> None:
        for stmt in ddl(self.dim).split(";\n"):
            if stmt.strip():
                await self.conn.execute(stmt.strip().rstrip(";"))

    async def upsert(self, rows: Sequence[dict[str, Any]], vectors: Sequence[Sequence[float]]) -> int:
        for r, v in zip(rows, vectors, strict=True):
            if len(v) != self.dim:
                raise EmbedDimMismatch(f"vector dim {len(v)} != {self.dim}")
            await self.conn.execute(
                "INSERT INTO scam_scripts (id, label, lang, embedding, source, synthetic) "
                "VALUES (%s, %s, %s, %s::vector, %s, %s) ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, "
                "lang = EXCLUDED.lang, embedding = EXCLUDED.embedding, source = EXCLUDED.source, "
                "synthetic = EXCLUDED.synthetic",
                (r["id"], r["label"], r["lang"], to_pgvector(v), r["source"], bool(r["synthetic"])),
            )
        return len(rows)

    async def knn(self, vec: Sequence[float], k: int = 3) -> list[ScriptMatch]:
        if len(vec) != self.dim:
            raise EmbedDimMismatch(f"query dim {len(vec)} != {self.dim}")
        q = to_pgvector(vec)
        cur = await self.conn.execute(
            "SELECT id, label, 1 - (embedding <=> %s::vector) AS similarity FROM scam_scripts "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (q, q, max(1, min(int(k), 20))),
        )
        return [ScriptMatch(str(i), str(lab), float(s)) for i, lab, s in await cur.fetchall()]


_REQUIRED = ("id", "label", "lang", "text", "source", "synthetic")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Approved JSONL: {id,label,lang,text,source,synthetic}. ``synthetic`` must be explicit; it is kept."""
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        missing = [k for k in _REQUIRED if k not in r]
        if missing:
            raise ValueError(f"{path}:{n} missing {missing}")
        if not isinstance(r["synthetic"], bool):
            raise ValueError(f"{path}:{n} synthetic must be a bool")
        rows.append(r)
    return rows


async def load_scripts(store: ScriptStore, embedder: OllamaEmbedder, path: str | Path, batch: int = 16) -> int:
    rows = read_jsonl(path)
    n = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        vecs = await embedder.embed([r["text"] for r in chunk])
        n += await store.upsert(chunk, vecs)
    return n


SPEC_SCRIPT = SignalSpec(
    name="message.script_match",
    family="message",
    tier="T1",
    input_types=("message", "email", "image"),
    timeout_ms=3000,
    network="local_mirror",
    emits=("message.script_match",),
)


async def script_match(
    text: str, embedder: OllamaEmbedder, store: ScriptStore, theta: float | None = None, k: int = 3
) -> list[Evidence]:
    """message.script_match when the nearest known script has similarity >= theta. Observed: ids, labels and
    similarity only."""
    if theta is None:
        theta = float(os.environ.get("FL_SCRIPT_MATCH_THETA", DEFAULT_THETA))
    (vec,) = await embedder.embed([text])
    matches = [m for m in await store.knn(vec, k) if m.similarity >= theta]
    if not matches:
        return []
    top = matches[0]
    return [
        Evidence(
            signal="message.script_match",
            family="message",
            source="computed",
            confidence=min(1.0, top.similarity),
            observed={
                "theta": theta,
                "matches": [{"id": m.id, "label": m.label, "similarity": round(m.similarity, 4)} for m in matches],
            },
            display={"en": "Matches a known scam script", "ar": "يطابق نصا احتياليا معروفا"},
        )
    ]


async def _run(ctx: SignalContext) -> list[Evidence]:
    """Registered runner. Needs ``ctx.http`` (Ollama) plus ``ctx.scripts`` (ScriptStore) and
    ``ctx.ollama_base_url``; without them it reports a degraded error, never raises."""
    t0 = time.perf_counter()
    try:
        store = getattr(ctx, "scripts", None)
        base = getattr(ctx, "ollama_base_url", None)
        if store is None or ctx.http is None or not base:
            out = [_error(SPEC_SCRIPT, "script store or embedder not configured")]
        else:
            out = await asyncio.wait_for(
                script_match(ctx.text or "", OllamaEmbedder(ctx.http, base), store),
                timeout=SPEC_SCRIPT.timeout_ms / 1000,
            )
    except TimeoutError:
        out = [_error(SPEC_SCRIPT, "timeout")]
    except Exception as exc:  # noqa: BLE001 - signals must never raise
        out = [_error(SPEC_SCRIPT, f"{type(exc).__name__}: {exc}"[:200])]
    ms = int((time.perf_counter() - t0) * 1000)
    for e in out:
        e.latency_ms = ms
    return out


run_script_match = _run
if SPEC_SCRIPT.name not in REGISTRY:
    REGISTRY[SPEC_SCRIPT.name] = (SPEC_SCRIPT, _run)


# ---------------------------------------------------------------------------------------------------------------
# Offline script index. WHY message.script_match never appeared: the registered runner above needs ctx.scripts (a
# pgvector ScriptStore), ctx.ollama_base_url and an embedder, but (1) the cascade's message path calls
# ``analyze_message`` only and never runs registry signals for messages, (2) ``SignalCtx`` has no ``scripts`` or
# ``ollama_base_url``, (3) nothing seeds the ``scam_scripts`` table and no script corpus existed. The runner therefore
# only ever returned its "not configured" error. The offline index below needs no DB and no network: character
# 3-gram cosine over a small corpus of SYNTHETIC scam scripts (``scam_scripts.jsonl``: TRAIN split items only),
# called from ``analyze_message``. The pgvector/Ollama path stays available for a wired deployment.
# ---------------------------------------------------------------------------------------------------------------
OFFLINE_THETA_FILE = Path(__file__).with_name("script_theta.json")
CORPUS_FILE = Path(__file__).with_name("scam_scripts.jsonl")


def _grams(text: str) -> dict[str, float]:
    t = " " + normalize(text[:MAX_MESSAGE_CHARS], collapse=False).text + " "
    g: dict[str, float] = {}
    for i in range(len(t) - 2):
        g[t[i : i + 3]] = g.get(t[i : i + 3], 0.0) + 1.0
    n = sum(v * v for v in g.values()) ** 0.5 or 1.0
    return {k: v / n for k, v in g.items()}


class LocalScriptIndex:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self.rows = [(str(r["id"]), str(r["label"]), _grams(str(r["text"]))) for r in rows]

    def nearest(self, text: str, k: int = 3) -> list[ScriptMatch]:
        q = _grams(text)
        sims = [ScriptMatch(i, lab, sum(v * g.get(t, 0.0) for t, v in q.items())) for i, lab, g in self.rows]
        return sorted(sims, key=lambda m: -m.similarity)[:k]


_INDEX: list[LocalScriptIndex | None] = []


def default_index() -> LocalScriptIndex | None:
    if not _INDEX:
        try:
            _INDEX.append(LocalScriptIndex(read_jsonl(CORPUS_FILE)))
        except (OSError, ValueError):
            _INDEX.append(None)
    return _INDEX[0]


def offline_theta() -> float:
    try:
        return float(json.loads(OFFLINE_THETA_FILE.read_text())["theta"])
    except (OSError, ValueError, KeyError):
        return 2.0  # unreachable: no fitted threshold, no evidence


def script_match_offline(
    text: str, index: LocalScriptIndex | None = None, theta: float | None = None
) -> list[Evidence]:
    index = index or default_index()
    theta = offline_theta() if theta is None else theta
    if index is None or not text.strip():
        return []
    matches = [m for m in index.nearest(text) if m.similarity >= theta]
    if not matches:
        return []
    top = matches[0]
    return [
        Evidence(
            signal="message.script_match",
            family="message",
            confidence=min(1.0, top.similarity),
            observed={
                "theta": theta,
                "index": "offline_char3gram",
                "matches": [{"id": m.id, "label": m.label, "similarity": round(m.similarity, 4)} for m in matches],
            },
            display={"en": "Matches a known scam script", "ar": "يطابق نصا احتياليا معروفا"},
        )
    ]
