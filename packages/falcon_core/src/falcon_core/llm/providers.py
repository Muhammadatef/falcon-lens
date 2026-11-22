"""LLM providers behind the router: Anthropic Messages API (cloud) and Ollama ``/v1`` (local).

Both take the same ``ProviderRequest`` (system text + user/assistant turns) and return plain text.
No native tool calling and no provider structured-output mode is used, so the cloud and local
routes behave the same (ADR-001); JSON is requested in the prompt and validated by the router.

Anthropic notes (anthropic 2.12.0, VERIFIED_VERSIONS §2): the stable system prompt is sent as a
text block with ``cache_control: {"type": "ephemeral"}``; ``output_config={"effort": "low"}``;
``thinking`` "disabled" for Haiku 5.5, "between_tools" for Sonnet 5.5 (rejects "disabled");
no temperature
(Haiku 5.5 says omit it); only ``text`` blocks are read from the response (thinking is ignored).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
import httpx

from falcon_core.llm.accounting import Usage
from falcon_core.llm.config import Route

_SPECIAL_TOKEN_RE = re.compile(r"<\|[a-z_]{2,40}\|>")


class ProviderError(Exception):
    def __init__(self, kind: Literal["timeout", "error", "unavailable"], detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    system: str
    turns: Sequence[ChatTurn]
    max_tokens: int
    timeout_s: float
    cache_system: bool = True


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    usage: Usage
    model: str


class Provider(Protocol):
    route: Route

    async def complete(self, req: ProviderRequest) -> ProviderResponse: ...


def strip_special_tokens(text: str) -> str:
    """Remove chat-template tokens such as ``<|end_message|>`` that leak from local models."""
    return _SPECIAL_TOKEN_RE.sub("", text).strip()


class AnthropicProvider:
    route: Route = "cloud"

    def __init__(self, api_key: str, client: Any | None = None) -> None:
        # max_retries=0: the router owns fallback; a retry storm would blow the latency budget.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        system_block: dict[str, Any] = {"type": "text", "text": req.system}
        if req.cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": [system_block],
            "messages": [{"role": t.role, "content": t.content} for t in req.turns],
            "output_config": {"effort": "low"},
            "timeout": req.timeout_s,
        }
        # No up-front thinking for short JSON replies (effort docs, checked 2026-11-22):
        # Haiku 5.5 accepts "disabled" at <= high; Sonnet 5.5 rejects it and takes "between_tools".
        if req.model.startswith("claude-haiku"):
            kwargs["thinking"] = {"type": "disabled"}
        elif req.model.startswith("claude-sonnet-5"):
            kwargs["thinking"] = {"type": "between_tools"}
        try:
            msg = await self._client.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise ProviderError("timeout", type(exc).__name__) from exc
        except anthropic.APIError as exc:
            raise ProviderError("error", type(exc).__name__) from exc
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        usage = Usage(
            input_tokens=int(getattr(u, "input_tokens", 0) or 0),
            output_tokens=int(getattr(u, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        )
        return ProviderResponse(text=text, usage=usage, model=str(getattr(msg, "model", req.model)))


class OllamaProvider:
    """Ollama OpenAI-compatible ``/v1/chat/completions`` (no ``response_format``)."""

    route: Route = "local"

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._client = client

    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        body = {
            "model": req.model,
            "stream": False,
            "temperature": 0,
            "seed": 7,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "system", "content": req.system}]
            + [{"role": t.role, "content": t.content} for t in req.turns],
        }
        try:
            if self._client is not None:
                resp = await self._client.post(self._url, json=body, timeout=req.timeout_s)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=body, timeout=req.timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", type(exc).__name__) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("error", type(exc).__name__) from exc
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("error", "malformed response") from exc
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("prompt_tokens", 0) or 0),
            output_tokens=int(u.get("completion_tokens", 0) or 0),
        )
        return ProviderResponse(text=strip_special_tokens(str(content)), usage=usage, model=req.model)
