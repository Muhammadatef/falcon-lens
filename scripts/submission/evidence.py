# ruff: noqa: E501
"""The other published evaluation families, read for the submission documents and for number tracing.

Truthfulness rule (CLAUDE.md): every number shown anywhere comes from a generated artifact. The headline
artifact (`evals/results/published/*.json`) and the live false-alarm runs (`fp_regress/`) are read by
`artifact.py`. This module adds the red-team, message-text, brand-new-pages, cost, stability, route-compare,
faithfulness, T3 and DSPy artifacts. It returns formatted text built only from values in those files, and the
list of artifact dicts that `check_numbers.py` accepts as sources.

Standard library only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "evals" / "results" / "published"
_STAMP = re.compile(r"\d{8}T\d{6}Z")


def pct(value: float, places: int = 1) -> str:
    q = Decimal(1).scaleb(-places)
    return f"{(Decimal(str(value)) * 100).quantize(q, rounding=ROUND_HALF_UP)}%"


def _stamp(path: Path) -> str:
    match = _STAMP.search(path.name)
    return match.group() if match else ""


def _read(path: Path) -> dict[str, Any] | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    data["_file"] = path.name
    return data


def newest(published: Path, family: str, glob: str = "*.json") -> dict[str, Any] | None:
    """Newest artifact of a family directory (by the timestamp in the file name), or None."""
    paths = sorted((p for p in (published / family).glob(glob) if p.is_file()), key=lambda p: (_stamp(p), p.name))
    return _read(paths[-1]) if paths else None


def redteam_runs(published: Path) -> dict[str, dict[str, Any]]:
    """Newest red-team run per LLM budget ('production', 'extended')."""
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted((published / "redteam").glob("*.json")):
        data = _read(path)
        if data is None or "summary" not in data:
            continue
        budget = str(data.get("llm_budget", "production"))
        key = (str(data.get("generated_at", "")), path.name)
        if budget not in best or key >= (best[budget][0], best[budget][1]["_file"]):
            best[budget] = (key[0], data)
    return {b: d for b, (_, d) in best.items()}


def fp_history(published: Path) -> list[dict[str, Any]]:
    """Every live held-out false-alarm run, oldest first (by `created_at`)."""
    runs = []
    for path in sorted((published / "fp_regress").glob("*.json")):
        data = _read(path)
        rate = data.get("false_positive_rate") if data else None
        if data and isinstance(rate, dict) and "value" in rate and "ci95" in rate and "n" in data and "target" in data:
            runs.append(data)
    return sorted(runs, key=lambda d: (str(d.get("created_at", "")), d["_file"]))


@dataclass
class Evidence:
    redteam: dict[str, dict[str, Any]] = field(default_factory=dict)
    fp: list[dict[str, Any]] = field(default_factory=list)
    message: dict[str, Any] | None = None
    brand_new: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    stability: dict[str, Any] | None = None
    route: dict[str, Any] | None = None
    faith: dict[str, Any] | None = None
    t3: dict[str, Any] | None = None
    sandbox: dict[str, Any] | None = None
    dspy: list[dict[str, Any]] = field(default_factory=list)
    fresh: dict[str, Any] | None = None
    voice: dict[str, Any] | None = None
    sovereign: list[dict[str, Any]] = field(default_factory=list)

    def claimed_values(self) -> list[float]:
        """The exact numbers the lines and slide rows above read, and nothing else (the tracer accepts only these)."""
        out: list[float] = []

        def take(node: Any, *path: str) -> None:
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    return
                node = node[key]
            for leaf in node if isinstance(node, list) else [node]:
                if isinstance(leaf, int | float) and not isinstance(leaf, bool):
                    out.append(leaf)

        for run in self.redteam.values():
            for key in ("cases", "harmful", "ci95", "llm_ran"):
                take(run, "summary", "overall", key)
        if self.message:
            for part in ("shipped", "rules_only_before"):
                for key in ("n_scam", "n_legit"):
                    take(self.message, "results", "test", part, key)
                for metric in ("recall", "fpr"):
                    for key in ("value", "ci_low", "ci_high", "k", "n"):
                        take(self.message, "results", "test", part, metric, key)
        if self.brand_new:
            for grp, keys in (
                ("new_lookalike_brand_pages", ("dangerous_final",)),
                ("benign_controls_novel_hosts", ("warning_final",)),
            ):
                take(self.brand_new, "groups", grp, "n")
                for key in keys:
                    take(self.brand_new, "groups", grp, key, "k")
        if self.cost:
            for key in ("mean", "ci95", "n"):
                take(self.cost, "cloud_route", "usd_per_check", key)
            take(self.cost, "local_route", "checks")
        if self.stability:
            for key in ("k", "n"):
                take(self.stability, "deterministic_control_ai_off", "label_agreement_all_three_identical", key)
                take(self.stability, "ai_layers_on", "pairwise_label_agreement", key)
            take(self.stability, "ai_layers_on", "items_with_all_three_runs_completed")
            take(self.stability, "ai_layers_on", "items")
        if self.route:
            for key in ("k", "n"):
                take(self.route, "verdict_agreement", "exact_label", key)
        if self.faith:
            for key in ("k", "n"):
                take(
                    self.faith,
                    "user_facing_reasons_template_only",
                    "cascade_fixture_verdicts_synthetic",
                    "all_cascade_verdicts",
                    "reasons_faithful",
                    key,
                )
        if self.t3:
            for key in ("k", "n"):
                take(self.t3, "by_route", "cloud", "reached_T3", key)
                take(self.t3, "by_route", "cloud", "forbidden_tool_call_rate", key)
        if self.fresh:
            for part in ("results", "results_second_source"):
                for grp in ("legit_all", "legit_uae", "phishing_all"):
                    for metric in ("dangerous", "warned", "degraded"):
                        for key in ("k", "n"):
                            take(self.fresh, part, "groups", grp, metric, key)
        if self.voice:
            take(self.voice, "clips")
            for metric in ("wake_accuracy", "intent_accuracy", "faq_answer_accuracy", "language_accuracy"):
                take(self.voice, "targets", "local", metric, "n")
                take(self.voice, "targets", "local", metric, "accuracy")
            take(self.voice, "targets", "local", "round_trip_s", "p95")
        for run in self.sovereign:
            take(run, "scenario_counts", "PASS")
            take(run, "egress_audit", "anthropic_sink_hits")
        for run in self.fp:
            for key in ("value", "ci95"):
                take(run, "false_positive_rate", key)
            take(run, "n")
            take(run, "target")
        return out

    # ── sources for the number tracer ────────────────────────────────────────────
    def sources(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [*self.redteam.values(), *self.fp, *self.dspy, *self.sovereign]
        out += [
            d
            for d in (
                self.message,
                self.brand_new,
                self.cost,
                self.stability,
                self.route,
                self.faith,
                self.t3,
                self.sandbox,
                self.fresh,
                self.voice,
            )
            if d
        ]
        return out

    # ── formatted lines (all values read from the files above) ───────────────────
    def redteam_line(self, budget: str) -> str | None:
        run = self.redteam.get(budget)
        if run is None:
            return None
        o = run["summary"]["overall"]
        lo, hi = o["ci95"]
        return (
            f"harmful {o['harmful']} of {o['cases']} (95% CI {pct(lo)} to {pct(hi)}), "
            f"with the model answering {o['llm_ran']} of {o['cases']} ({budget} time limits)"
        )

    def redteam_both(self) -> str | None:
        prod, ext = self.redteam_line("production"), self.redteam_line("extended")
        if prod is None or ext is None:
            return prod or ext
        return f"{prod}; {ext}"

    def message_line(self) -> str | None:
        if not self.message:
            return None
        t = self.message["results"]["test"]
        s, r = t["shipped"], t["rules_only_before"]
        return (
            f"test recall {pct(s['recall']['value'])} ({pct(s['recall']['ci_low'])} to {pct(s['recall']['ci_high'])}, "
            f"{s['recall']['k']} of {s['n_scam']} scam), false-alarm rate {pct(s['fpr']['value'])} "
            f"({pct(s['fpr']['ci_low'])} to {pct(s['fpr']['ci_high'])}, {s['fpr']['k']} of {s['n_legit']} legitimate); "
            f"rules alone reach recall {pct(r['recall']['value'])}"
        )

    def brand_new_line(self) -> str | None:
        if not self.brand_new:
            return None
        g = self.brand_new["groups"]
        look, ben = g["new_lookalike_brand_pages"], g["benign_controls_novel_hosts"]
        return (
            f"flagged Dangerous {look['dangerous_final']['k']} of {look['n']} look-alike pages on hosts in no feed; "
            f"benign controls warned {ben['warning_final']['k']} of {ben['n']}, so read warning rates next to that row"
        )

    def cost_line(self) -> str | None:
        if not self.cost:
            return None
        c = self.cost["cloud_route"]["usd_per_check"]
        return f"mean {c['mean']} USD per check on the cloud route ({c['ci95'][0]} to {c['ci95'][1]}, {c['n']} checks); the local route has zero marginal API cost, and energy was not measured"

    def stability_line(self) -> str | None:
        if not self.stability:
            return None
        ctl = self.stability["deterministic_control_ai_off"]["label_agreement_all_three_identical"]
        on = self.stability["ai_layers_on"]
        pair = on["pairwise_label_agreement"]
        return (
            f"same label on all three repeat runs for {ctl['k']} of {ctl['n']} items with the AI layers off; "
            f"with them on, repeat pairs agree {pair['k']} of {pair['n']}, and only {on['items_with_all_three_runs_completed']} of {on['items']} items completed all three runs"
        )

    def route_line(self) -> str | None:
        if not self.route:
            return None
        e = self.route["verdict_agreement"]["exact_label"]
        return f"cloud and local routes gave the same label on {e['k']} of {e['n']} fixture checks"

    def faith_line(self) -> str | None:
        if not self.faith:
            return None
        v = self.faith["user_facing_reasons_template_only"]["cascade_fixture_verdicts_synthetic"][
            "all_cascade_verdicts"
        ]
        return f"{v['reasons_faithful']['k']} of {v['reasons_faithful']['n']} shown reasons cite evidence that is in the verdict; the reasons are templates, not model text"

    def t3_line(self) -> str | None:
        if not self.t3:
            return None
        c = self.t3["by_route"]["cloud"]
        f = c["forbidden_tool_call_rate"]
        return f"the tool-using Investigator reached the third tier on {c['reached_T3']['k']} of {c['reached_T3']['n']} cloud checks and made {f['k']} forbidden tool calls in {f['n']}"

    def fp_history_line(self) -> str | None:
        if not self.fp:
            return None
        first, last = self.fp[0], self.fp[-1]
        low = min(self.fp, key=lambda d: d["false_positive_rate"]["value"])
        return (
            f"false alarms on held-out real sites: first run {pct(first['false_positive_rate']['value'])}, "
            f"lowest {pct(low['false_positive_rate']['value'])}, newest {pct(last['false_positive_rate']['value'])} "
            f"(95% CI {pct(last['false_positive_rate']['ci95'][0])} to {pct(last['false_positive_rate']['ci95'][1])}, {last['n']} sites), "
            f"against a target of {pct(last['target'])}: the target is not met"
        )

    def slide_rows(self) -> list[tuple[str, str]]:
        """Short (label, text) rows for the deck: only families that are published."""
        rows: list[tuple[str, str]] = []
        prod, ext = self.redteam.get("production"), self.redteam.get("extended")
        if prod and ext:
            po, eo = prod["summary"]["overall"], ext["summary"]["overall"]
            rows.append(
                (
                    "Red-team, synthetic",
                    f"harmful {po['harmful']} of {po['cases']}, with the model answering {po['llm_ran']} of {po['cases']} at production limits; "
                    f"harmful {eo['harmful']} of {eo['cases']}, answering {eo['llm_ran']} of {eo['cases']}, at extended limits",
                )
            )
        if self.message:
            t = self.message["results"]["test"]["shipped"]
            r = self.message["results"]["test"]["rules_only_before"]
            rows.append(
                (
                    "Scam messages with no link, synthetic, single-author, audited",
                    f"test recall {pct(t['recall']['value'])} ({pct(t['recall']['ci_low'])} to {pct(t['recall']['ci_high'])}), "
                    f"false alarms {t['fpr']['k']} of {t['n_legit']}; rules alone {pct(r['recall']['value'])}",
                )
            )
        if self.brand_new:
            g = self.brand_new["groups"]
            look, ben = g["new_lookalike_brand_pages"], g["benign_controls_novel_hosts"]
            rows.append(
                (
                    "Brand-new look-alike pages, synthetic",
                    f"Dangerous {look['dangerous_final']['k']} of {look['n']}; benign controls warned {ben['warning_final']['k']} of {ben['n']} (AI layer off)",
                )
            )
        if self.cost and self.route and self.stability:
            c = self.cost["cloud_route"]["usd_per_check"]
            st = self.stability["deterministic_control_ai_off"]["label_agreement_all_three_identical"]
            ra = self.route["verdict_agreement"]["exact_label"]
            rows.append(
                (
                    "Cost, stability, routes, fixtures",
                    f"cloud route mean {c['mean']} USD per check, local zero marginal API cost; same label on repeat runs {st['k']} of {st['n']}; cloud and local routes agree {ra['k']} of {ra['n']}",
                )
            )
        if self.faith and self.t3:
            v = self.faith["user_facing_reasons_template_only"]["cascade_fixture_verdicts_synthetic"][
                "all_cascade_verdicts"
            ]["reasons_faithful"]
            f = self.t3["by_route"]["cloud"]["forbidden_tool_call_rate"]
            rows.append(
                (
                    "Faithfulness and the tool-using Investigator",
                    f"{v['k']} of {v['n']} shown reasons cite evidence in the verdict; {f['k']} forbidden tool calls in {f['n']} Investigator checks",
                )
            )
        if self.dspy:
            rows.append(
                (
                    "DSPy prompt optimisation",
                    "ran for every model role on synthetic data; not adopted, the gains are within noise",
                )
            )
        return rows

    # ── fresh 200-site live test, voice bench, sovereign proof ───────────────────
    def _fresh_group(self, part: str, grp: str, metric: str) -> tuple[int, int] | None:
        if not self.fresh:
            return None
        m = self.fresh[part]["groups"][grp][metric]
        return int(m["k"]), int(m["n"])

    def fresh_main_line(self) -> str | None:
        d = self._fresh_group("results", "phishing_all", "dangerous")
        w = self._fresh_group("results", "legit_all", "warned")
        ld = self._fresh_group("results", "legit_all", "dangerous")
        lu = self._fresh_group("results", "legit_uae", "warned")
        if not (d and w and ld and lu):
            return None
        return (
            f"main set: {d[0]} of {d[1]} listed phishing URLs Dangerous (the feed supplied them, so this is feed coverage plus pipeline); "
            f"legitimate sites {ld[0]} of {ld[1]} Dangerous and {w[0]} of {w[1]} warned (Suspicious); of {lu[1]} UAE sites {lu[0]} warned"
        )

    def fresh_second_line(self) -> str | None:
        w = self._fresh_group("results_second_source", "phishing_all", "warned")
        d = self._fresh_group("results_second_source", "phishing_all", "dangerous")
        g = self._fresh_group("results_second_source", "phishing_all", "degraded")
        if not (w and d and g):
            return None
        return (
            f"hosts from a feed the stack does not query: {w[0]} of {w[1]} warned, only {d[0]} of {d[1]} Dangerous "
            f"(the rest Suspicious), and {g[0]} of {g[1]} could not complete every check"
        )

    def fresh_dead_line(self) -> str | None:
        """How many listed phishing URLs (second feed) were already offline when the sandbox visited."""
        dead = self._fresh_group("results_second_source", "phishing_dead_in_sandbox", "degraded")
        total = self._fresh_group("results_second_source", "phishing_all", "degraded")
        if not (dead and total):
            return None
        share = dead[0] / total[1] if total[1] else 0.0
        how = "almost half" if 0.4 <= share < 0.5 else "about half" if 0.5 <= share < 0.6 else "a share"
        return f"{how} of the listed phishing URLs in the second feed were already offline when the sandbox visited (the count is in the fresh-test artifact)"

    def fresh_caveat(self) -> str | None:
        if not self.fresh:
            return None
        return "single run on one day; legitimate labels are not hand-audited; phishing labels are the feed's own and some pages were already dead"

    def voice_line(self) -> str | None:
        if not self.voice:
            return None
        t = self.voice["targets"]["local"]
        return (
            f"wake word {pct(t['wake_accuracy']['accuracy'])}, intent {pct(t['intent_accuracy']['accuracy'])}, "
            f"FAQ answer {pct(t['faq_answer_accuracy']['accuracy'])}, language {pct(t['language_accuracy']['accuracy'])} "
            f"on {t['wake_accuracy']['n']} synthetic clips (macOS say and Polly voices, synthetic noise; not real speakers)"
        )

    def voice_speed(self) -> str | None:
        if not self.voice:
            return None
        return f"{self.voice['targets']['local']['round_trip_s']['p95']} s"

    def sovereign_line(self) -> str | None:
        if not self.sovereign:
            return None
        parts = []
        for run in self.sovereign:
            ok = run["scenario_counts"]["PASS"]
            n = sum(run["scenario_counts"].values())
            sink = run["egress_audit"]["anthropic_sink_hits"]
            model = str(run["local_model"])
            label = "Qwen" if "qwen" in model.lower() else "Inkling-2-Mini" if "inkling" in model.lower() else model
            note = (
                ""
                if run.get("status") == "passed"
                else "; the run is marked failed because the Sentinel summary fell back to a template"
            )
            parts.append(f"{label}: {ok} of {n} scenarios passed, {sink} calls to a cloud model{note}")
        return "; ".join(parts)

    def dspy_line(self) -> str | None:
        if not self.dspy:
            return None
        if any(d.get("adopted") for d in self.dspy):
            return "DSPy prompt optimisation ran for every model role; the roles it improved beyond noise are adopted, the rest are not"
        return "DSPy prompt optimisation ran for every model role and was not adopted for any of them (the gains are within noise)"


def _sovereign_latest(published: Path) -> list[dict[str, Any]]:
    """Newest sovereign-proof run per local model."""
    best: dict[str, dict[str, Any]] = {}
    for path in sorted((published / "sovereign").glob("*.json"), key=lambda p: (_stamp(p), p.name)):
        data = _read(path)
        if data and "scenario_counts" in data and "egress_audit" in data:
            best[str(data.get("local_model"))] = data
    return list(best.values())


def load(published: Path = PUBLISHED) -> Evidence:
    dspy_latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted((published / "dspy").glob("*.json")):
        data = _read(path)
        if data and "role" in data:
            key = (_stamp(path), path.name)
            if data["role"] not in dspy_latest or key >= (
                _stamp(Path(dspy_latest[data["role"]][1]["_file"])),
                dspy_latest[data["role"]][1]["_file"],
            ):
                dspy_latest[data["role"]] = (path.name, data)
    return Evidence(
        redteam=redteam_runs(published),
        fp=fp_history(published),
        message=newest(published, "message_text"),
        brand_new=newest(published, "brand_new_pages"),
        cost=newest(published, "cost_per_check"),
        stability=newest(published, "stability"),
        route=newest(published, "route_compare"),
        faith=newest(published, "faithfulness"),
        t3=newest(published, "t3_investigator"),
        sandbox=newest(published, "sandbox_t2"),
        dspy=[d for _, d in dspy_latest.values()],
        fresh=newest(published, "fresh200"),
        voice=newest(published, "voice", "voice_live_bench_*.json"),
        sovereign=_sovereign_latest(published),
    )


# Keys the headline artifact lists as `not_evaluated` that a newer published family has since measured:
# key -> (family folder, what is still open, or None when nothing is). The headline file is frozen, so the
# submission documents read this map instead of repeating a stale "not measured" list.
SUPERSEDED: dict[str, tuple[str, str | None]] = {
    "arabic_clarity": ("arabic_clarity", "arabic_clarity_human_rating"),
    "cost_per_check_llm": ("cost_per_check", None),
    "faithfulness": ("faithfulness", None),
    "flip_rate_3_runs": ("stability", None),
    "injection_attack_success_rate": ("redteam", None),
    "llm_tier_T3": ("t3_investigator", None),
    "sandbox_tier_T2": ("sandbox_t2", "sandbox_phishing_page_recall"),
    "zero_day": ("brand_new_pages", None),
    "synthetic": ("synthetic_split", None),
    "cloud_route": ("route_compare", None),
    "sovereign_route": ("route_compare", None),
}


def still_not_measured(keys: list[str], published: Path = PUBLISHED) -> list[str]:
    """`keys` minus what a newer artifact family now measures; a partly open item is renamed to what is open."""
    out: list[str] = []
    for key in keys:
        family, open_item = SUPERSEDED.get(key, ("", key))
        if family and not any((published / family).glob("*.json")):
            open_item = key
        if open_item and open_item not in out:
            out.append(open_item)
    return out
