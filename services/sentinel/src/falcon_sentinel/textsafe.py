"""Vetting of LLM free text before it is stored (CONTRACTS invariant 5: URLs in any output are defanged).

`vet(text, view)` returns the text with every allowed domain defanged, or None when the text mentions a URL,
domain, IP, e-mail, phone number or other number that is not derivable from the structured evidence view.
Callers fall back to the deterministic template (summary/reason) or drop the claim.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from sentinel_core.events import EVENT_SCHEMA_PATH

URL_RE = re.compile(r"(?i)\b(?:https?|hxxps?|ftp)\s*:\s*//|\bwww\s*\.")
DOMAIN_RE = re.compile(
    r"(?i)(?<![\w@-])((?:[a-z0-9؀-ۿ](?:[a-z0-9؀-ۿ-]*[a-z0-9؀-ۿ])?(?:\[\.\]|\.))+[a-z]{2,24})(?![\w-])"
)
IP_RE = re.compile(
    r"\b\d{1,3}(?:\[?\.\]?\d{1,3}){3}\b|\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b|(?:[0-9a-f]{0,4}:){1,7}:[0-9a-f]{0,4}",
    re.I,
)
EMAIL_RE = re.compile(r"[\w.+-]+(?:@|\[at\])[\w-]+(?:\.|\[\.\])[\w.-]+", re.I)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def allowed_numbers(view: dict[str, Any]) -> set[str]:
    nums = set(NUM_RE.findall(json.dumps(view, ensure_ascii=False)))
    doms = [i for i in view["indicators"] if i["kind"] == "domain"]
    nums |= {
        str(len(doms)),
        str(len(view["indicators"])),
        str(len(view["timeline"])),
        str(len(view["rule_ids"])),
        str(len(view["linked_verdicts"])),
    }
    nums |= {str(len(v)) for v in view["correlation_keys"].values() if isinstance(v, list)}
    cmp = view.get("comparison") or {}
    nums |= {str(v) for v in cmp.values() if isinstance(v, int) and not isinstance(v, bool)}
    return nums


ARABIC_LETTERS = "".join(chr(c) for c in range(0x0600, 0x06FF + 1))


@lru_cache(maxsize=1)
def contract_event_types() -> frozenset[str]:
    """Event type names from contracts/event.schema.json (the contract, not a hand list)."""
    schema = json.loads(EVENT_SCHEMA_PATH.read_text())
    return frozenset(str(t).lower() for t in schema["properties"]["type"]["enum"])


def allowed_event_types(view: dict[str, Any]) -> set[str]:
    """Event type names ("domain.observed") look like hosts but are contract vocabulary. Only names that are in
    the event contract AND appear in this incident's timeline pass."""
    seen = {str(t["what"]).split(" ", 1)[0].lower() for t in view["timeline"] if t.get("what")}
    return seen & contract_event_types()


def allowed_hosts(view: dict[str, Any]) -> set[str]:
    return {
        i["value_defanged"].replace("[.]", ".").lower() for i in view["indicators"] if i["kind"] in ("domain", "url")
    }


def defang_hosts(text: str, hosts: set[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        return m.group(1).replace("[.]", ".").replace(".", "[.]")

    return DOMAIN_RE.sub(sub, text)


def vet(text: str, view: dict[str, Any]) -> str | None:
    if URL_RE.search(text) or EMAIL_RE.search(text) or IP_RE.search(text):
        return None
    hosts = allowed_hosts(view)
    kinds = allowed_event_types(view)
    for m in DOMAIN_RE.finditer(text):
        cand = m.group(1).replace("[.]", ".").lower()
        # Arabic clitics (و "and", ب, ل ...) glue onto a Latin host with no space: judge the host itself.
        if cand not in hosts and cand.lstrip(ARABIC_LETTERS) not in hosts and cand not in kinds:
            return None
    ok_nums = allowed_numbers(view)
    for n in NUM_RE.findall(text):
        if n not in ok_nums:
            return None
    return defang_hosts(text, hosts)
