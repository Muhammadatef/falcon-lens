"""Ollama chat client (OpenAI-compatible endpoint). The only network peer of the worker."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

SPECIAL = re.compile(r"<\|[^|>]*\|>")
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
QUALITY_MODEL = os.environ.get("FL_LOCAL_QUALITY_MODEL", "inkling-2-mini-chat")
BULK_MODEL = os.environ.get("FL_LOCAL_WORKER_MODEL", "qwen3:4b")


def base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def clean(text: str) -> str:
    return SPECIAL.sub("", THINK.sub("", text)).strip()


def extract_json(text: str) -> Any:
    """No structured output on local models: pull the first JSON value out of prose or code fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


class Ollama:
    def __init__(self, client: httpx.Client, base: str | None = None) -> None:
        self.client = client
        self.base = (base or base_url()).rstrip("/")

    def ping(self) -> bool:
        try:
            return self.client.get(f"{self.base}/api/tags", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, model: str, system: str, user: str, temperature: float = 0.2, seed: int = 7) -> str:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "seed": seed,
        }
        r = self.client.post(f"{self.base}/v1/chat/completions", json=body)
        r.raise_for_status()
        return clean(r.json()["choices"][0]["message"]["content"] or "")
