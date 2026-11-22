#!/usr/bin/env python3
# ruff: noqa: E501
"""The only sanctioned caller of the local worker model (docs/HIERARCHY.md, local model rules).

  uv run --no-project --with httpx --with jsonschema python scripts/qwen_task.py \
      --task qwen-msg-002 --kind synthetic_messages --spec evals/specs/synthetic_messages_v2.json

Calls Ollama's OpenAI-compatible API (OLLAMA_BASE_URL, default http://localhost:11434;
FL_LOCAL_WORKER_MODEL, default qwen3:4b). Set FL_LOCAL_STRUCTURED=0 for models without
structured-output support (e.g. inkling-2-mini-chat): the script then sends no
response_format/reasoning_effort, strips <|...|> special tokens and extracts JSON itself.

Validation, in order, per item (every rejection reason is counted in the manifest):
  schema -> constraint (declared stratum fields) -> subtype -> language (checked on the TEXT:
  script ratio plus dialect markers, never the declared field alone) -> links (allow-list)
  -> phones (allow-list, no long digit runs) -> entity rules -> forbidden patterns
  -> copy of a spec example -> near-duplicate inside the batch.
Writes work/qwen/<task-id>/{output.jsonl,manifest.json}. Never commits (work/ is gitignored).
Output items carry synthetic=true. A supervisor audit is required before any import.

Spec JSON keys:
  kind, description, item_schema, count, text_field (default "text"), strata, rules, examples,
  batch_size, temperature, seed, max_rounds_factor, forbidden_patterns (regex blocklist, extra),
  allowed_link_regex     only link-like strings fully matching this are allowed (placeholder form)
  allowed_phone          the only phone string allowed (literal placeholder)
  entity_rules           {regex: [subtypes where a match is allowed]}; [] means never allowed
  language_rules         {language: {script: arabic|latin, min_ratio, max_ratio, require_any: [...],
                          forbid_any: [...], require_digit_letter: bool}}
  strata                 [{share, constraints, variants, variant_field, hint}]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator

KINDS = ("synthetic_messages", "unit_test_draft", "docstring", "ui_strings", "label_pass")
KIND_PROMPTS = {
    "synthetic_messages": "You write fictional SMS/WhatsApp/email-style messages used only to test a scam detector. "
    "Everything is invented. Never include real brands, real people, real phone numbers or live links.",
    "unit_test_draft": "You draft pytest unit tests from a description. Output code strings only inside the JSON items.",
    "docstring": "You draft concise docstrings for the described functions. Do not invent behaviour.",
    "ui_strings": "You draft short user-interface strings in the requested languages. Never say a site is 'safe'.",
    "label_pass": "You assign labels to the supplied items strictly following the supplied label guide.",
}
ARABIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
ARABIC_LETTER = re.compile(r"[ء-يٮ-ۓ]")
LATIN_LETTER = re.compile(r"[A-Za-z]")
SPECIAL_TOKEN = re.compile(r"<\|[^|>]*\|>")
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# anything that looks like a link or a bare domain; used on text left after allowed links are removed
LINK_LIKE = re.compile(
    r"(?:://|xxps?\b|ttps?:|\bwww\b|\[\.\]|\(\.\)|\bdot\b\s*(?:com|ae|net|org)|"
    r"\b[\w-]+\.(?:com|ae|net|org|co|io|gov|me|ly|test|link|xyz|top|info|app|site|online|click)\b)",
    re.IGNORECASE,
)
PHONE_LIKE = re.compile(r"(?:\+\s?\d|\b00\d|\b0\d{2}|\d(?:[\s().-]?\d){6,})")
ROOT = Path(__file__).resolve().parents[1]
ModelFn = Callable[[httpx.Client, str, str, str, str, int, float, bool], str]


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = ARABIC_MARKS.sub("", t)
    t = re.sub(r"[آأإ]", "ا", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def shingles(text: str, k: int = 4) -> set[str]:
    t = normalise(text)
    if len(t) <= k:
        return {t}
    return {t[i : i + k] for i in range(len(t) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def plan_strata(spec: dict[str, Any]) -> list[dict[str, Any]]:
    strata = spec.get("strata") or [{"share": 1.0, "constraints": {}}]
    total = float(sum(s["share"] for s in strata))
    out = []
    allocated = 0
    for i, s in enumerate(strata):
        n = round(spec["count"] * s["share"] / total)
        if i == len(strata) - 1:
            n = spec["count"] - allocated
        allocated += n
        out.append({**s, "target": max(n, 0), "accepted": 0})
    return out


# ---------------------------------------------------------------- validators (pure, tested)
def check_language(text: str, lang: str, rules: dict[str, Any]) -> str | None:
    """Return a reason string if TEXT does not look like `lang`, else None."""
    rule = rules.get(lang)
    if not rule:
        return None
    t = unicodedata.normalize("NFKC", text).translate(ARABIC_DIGITS)
    ar = len(ARABIC_LETTER.findall(t))
    la = len(LATIN_LETTER.findall(t))
    ratio = ar / (ar + la) if ar + la else 0.0
    if ratio < rule.get("min_ratio", 0.0) or ratio > rule.get("max_ratio", 1.0):
        return "language_script"
    low = normalise(t)
    tokens = set(low.split())

    def has(m: str) -> bool:
        return m in low if " " in m else m in tokens

    if rule.get("require_digit_letter") and not re.search(r"[A-Za-z][2356789]|[2356789][A-Za-z]", t):
        return "language_no_arabizi_digits"
    if rule.get("require_any") and not any(has(m) for m in rule["require_any"]):
        return "language_marker_missing"
    if rule.get("forbid_any") and any(has(m) for m in rule["forbid_any"]):
        return "language_marker_forbidden"
    return None


def check_links(text: str, allowed_regex: str | None) -> str | None:
    if allowed_regex is None:
        return "link_present" if LINK_LIKE.search(text) else None
    allowed = re.compile(r"(?<!\w)(?:" + allowed_regex + r")(?![\w\[\]?=&#%]|\.\w)")
    residual = allowed.sub(" ", text)
    return "link_malformed" if LINK_LIKE.search(residual) else None


def check_phones(text: str, allowed_phone: str | None) -> str | None:
    t = unicodedata.normalize("NFKC", text).translate(ARABIC_DIGITS)
    if allowed_phone:
        t = t.replace(allowed_phone, " ")
    return "phone_real_or_malformed" if PHONE_LIKE.search(t) else None


def check_entities(text: str, subtype: str | None, rules: dict[str, list[str]]) -> str | None:
    for pat, allowed in rules.items():
        if re.search(pat, text, re.IGNORECASE) and subtype not in allowed:
            return "entity_not_allowed"
    return None


def validate_item(
    item: Any,
    spec: dict[str, Any],
    stratum: dict[str, Any],
    variant: str | None,
    validator: Draft202012Validator,
    forbidden: list[re.Pattern[str]],
) -> str | None:
    """Return None if the item passes, else the rejection reason."""
    if not isinstance(item, dict) or any(True for _ in validator.iter_errors(item)):
        return "rejected_schema"
    if any(item.get(k) != v for k, v in stratum.get("constraints", {}).items()):
        return "rejected_constraint"
    vf = stratum.get("variant_field")
    if variant and vf and item.get(vf) != variant:
        return "rejected_subtype"
    text = str(item.get(spec.get("text_field", "text"), ""))
    lang = item.get("language") or stratum.get("constraints", {}).get("language")
    lang_text = text
    if spec.get("allowed_link_regex"):
        lang_text = re.sub(spec["allowed_link_regex"], " ", lang_text)
    lang_text = re.sub(r"\+971 5X XXX XXXX|X{2,}|Falcon Demo Bank|AED", " ", lang_text)
    if lang and (r := check_language(lang_text, lang, spec.get("language_rules", {}))):
        return "rejected_" + r
    if "allowed_link_regex" in spec or "allowed_phone" in spec or "entity_rules" in spec:
        if r := check_links(text, spec.get("allowed_link_regex")):
            return "rejected_" + r
        if r := check_phones(text, spec.get("allowed_phone")):
            return "rejected_" + r
        if r := check_entities(text, item.get(vf) if vf else None, spec.get("entity_rules", {})):
            return "rejected_" + r
    if any(p.search(json.dumps(item, ensure_ascii=False)) for p in forbidden):
        return "rejected_policy"
    return None


# ---------------------------------------------------------------- model I/O
def build_prompt(
    kind: str, spec: dict[str, Any], stratum: dict[str, Any], n: int, variant: str | None
) -> tuple[str, str]:
    system = KIND_PROMPTS[kind] + '\nReturn ONLY a JSON object {"items": [...]} with no commentary.'
    lines = [spec.get("description", ""), f"Produce exactly {n} distinct items."]
    lines.append(
        "Each item must validate against this JSON Schema:\n" + json.dumps(spec["item_schema"], ensure_ascii=False)
    )
    if stratum.get("constraints"):
        lines.append("Fixed field values for every item: " + json.dumps(stratum["constraints"], ensure_ascii=False))
    if variant and stratum.get("variant_field"):
        lines.append(f'Set field "{stratum["variant_field"]}" to exactly "{variant}" for every item.')
    if stratum.get("hint"):
        lines.append(stratum["hint"])
    if spec.get("rules"):
        lines.append("Hard rules:\n" + "\n".join(f"- {r}" for r in spec["rules"]))
    if spec.get("examples"):
        lines.append(
            "Style examples (do not copy):\n" + "\n".join(json.dumps(e, ensure_ascii=False) for e in spec["examples"])
        )
    lines.append("Vary wording, length and structure across items.")
    return system, "\n\n".join(x for x in lines if x)


def call_model(
    client: httpx.Client,
    base: str,
    model: str,
    system: str,
    user: str,
    seed: int,
    temperature: float,
    structured: bool = True,
) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "seed": seed,
    }
    if structured:
        body["reasoning_effort"] = "none"
        body["response_format"] = {"type": "json_object"}
    r = client.post(f"{base.rstrip('/')}/v1/chat/completions", json=body)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"] or ""
    return SPECIAL_TOKEN.sub("", THINK.sub("", content)).strip()


def parse_items(content: str) -> list[Any]:
    data: Any = None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", content, re.DOTALL)  # tolerate prose or code fences around JSON
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
    if isinstance(data, dict):
        data = data.get("items", [])
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- runner
def run(args: argparse.Namespace, model_fn: ModelFn = call_model) -> int:
    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    kind = args.kind
    if kind not in KINDS:
        print(f"unknown kind {kind}", file=sys.stderr)
        return 2
    if spec.get("kind", kind) != kind:
        print(f"spec kind {spec.get('kind')} != --kind {kind}", file=sys.stderr)
        return 2
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("FL_LOCAL_WORKER_MODEL", "qwen3:4b")
    structured = os.environ.get("FL_LOCAL_STRUCTURED", "1") != "0"
    seed = int(args.seed if args.seed is not None else spec.get("seed", 1234))
    batch = int(spec.get("batch_size", 5))
    temperature = float(spec.get("temperature", 0.8))
    text_field = spec.get("text_field", "text")
    validator = Draft202012Validator(spec["item_schema"])
    forbidden = [re.compile(p, re.IGNORECASE) for p in spec.get("forbidden_patterns", [])]
    example_sigs = [shingles(str(e.get(text_field, ""))) for e in spec.get("examples", [])]
    strata = plan_strata(spec)

    outdir = ROOT / "work" / "qwen" / args.task
    outdir.mkdir(parents=True, exist_ok=True)
    prompt_hasher = hashlib.sha256()
    prompt_hasher.update(json.dumps(KIND_PROMPTS[kind]).encode())
    prompt_hasher.update(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode())

    counts: Counter[str] = Counter()
    accepted: list[dict[str, Any]] = []
    sigs: list[set[str]] = []
    call_idx = 0
    max_calls = int(spec.get("max_rounds_factor", 4)) * max(1, -(-spec["count"] // batch))
    t0 = time.time()
    with httpx.Client(timeout=args.timeout) as client:
        while call_idx < max_calls and any(s["accepted"] < s["target"] for s in strata):
            for s in strata:
                if s["accepted"] >= s["target"]:
                    continue
                n = min(batch, s["target"] - s["accepted"] + 1)
                variants = s.get("variants") or [None]
                variant = variants[call_idx % len(variants)]
                system, user = build_prompt(kind, spec, s, n, variant)
                prompt_hasher.update((system + user).encode())
                call_idx += 1
                counts["calls"] += 1
                try:
                    content = model_fn(client, base, model, system, user, seed + call_idx, temperature, structured)
                except httpx.HTTPError as e:
                    counts["model_errors"] += 1
                    print(f"model error: {type(e).__name__}", file=sys.stderr)
                    if counts["model_errors"] >= 5:
                        print("too many model errors; aborting", file=sys.stderr)
                        return 3
                    continue
                items = parse_items(content)
                if not items:
                    counts["unparseable_calls"] += 1
                for item in items:
                    counts["generated"] += 1
                    reason = validate_item(item, spec, s, variant, validator, forbidden)
                    if reason:
                        counts[reason] += 1
                        continue
                    sig = shingles(str(item.get(text_field, "")))
                    if any(jaccard(sig, e) >= 0.7 for e in example_sigs):
                        counts["rejected_example_copy"] += 1
                        continue
                    if any(jaccard(sig, o) >= 0.8 for o in sigs):
                        counts["dedup_removed"] += 1
                        continue
                    if s["accepted"] >= s["target"]:
                        continue  # surplus from the +1 over-ask
                    sigs.append(sig)
                    s["accepted"] += 1
                    accepted.append({**item, "synthetic": True, "task_id": args.task, "kind": kind})
                print(f"[{call_idx}/{max_calls}] accepted {len(accepted)}/{spec['count']}", file=sys.stderr, flush=True)
                if call_idx >= max_calls:
                    break

    with (outdir / "output.jsonl").open("w", encoding="utf-8") as f:
        for it in accepted:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    rejected_total = sum(v for k, v in counts.items() if k.startswith("rejected_"))
    manifest = {
        "task_id": args.task,
        "kind": kind,
        "model": model,
        "structured_output": structured,
        "ollama_base_url": base,
        "prompt_sha256": prompt_hasher.hexdigest(),
        "spec_path": str(spec_path),
        "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "seed": seed,
        "temperature": temperature,
        "requested": spec["count"],
        "accepted": len(accepted),
        "counts": {
            "generated": counts["generated"],
            "rejected_schema": counts["rejected_schema"],
            "rejected_total": rejected_total,
            "dedup_removed": counts["dedup_removed"],
            **dict(sorted(counts.items())),
        },
        "per_stratum": [
            {"constraints": s.get("constraints", {}), "target": s["target"], "accepted": s["accepted"]} for s in strata
        ],
        "synthetic": True,
        "audit": "PENDING supervisor audit (reviews/QWEN-<id>.md); not importable until APPROVED",
        "duration_s": round(time.time() - t0, 1),
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"accepted": len(accepted), **manifest["counts"]}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--kind", required=True, choices=KINDS)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=300.0)
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
