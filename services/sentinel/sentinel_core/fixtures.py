"""Deterministic labelled replay stream: noise + 1 planted campaign + 1 kit reuse + 1 reputation flip.

Everything is invented: only the fictional brand "falcon_demo_bank", only `.test` domains,
every event has `source: replay`. No real brands, no live URLs, no raw text.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .ids import make_ulid

BRAND = "falcon_demo_bank"
T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
CAMPAIGN_SIMHASH = 0x9F3A_61C4_D27E_08B5
KIT_SIMHASH = 0x2B6D_E0A1_5C94_F37A


@dataclass
class Fixture:
    events: list[dict[str, Any]]
    vectors: dict[str, list[float]]
    labels: dict[str, Any]
    _n: int = field(default=0, repr=False)

    def to_jsonl(self, path: Path | str) -> None:
        Path(path).write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in self.events))


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class _Gen:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.events: list[dict[str, Any]] = []
        self.n = 0

    def emit(self, type_: str, at: datetime, payload: dict[str, Any], verdict_id: str | None = None) -> str:
        self.n += 1
        eid = f"evt_{make_ulid(at, f'{self.seed}|evt|{self.n}')}"
        self.events.append(
            {
                "schema_version": "1.0",
                "event_id": eid,
                "type": type_,
                "occurred_at": _iso(at),
                "source": "replay",
                "verdict_id": verdict_id,
                "payload": payload,
            }
        )
        return eid

    def far_simhash(self, avoid: list[int]) -> int:
        while True:
            v = self.rng.getrandbits(64)
            if all((v ^ a).bit_count() > 12 for a in avoid):
                return v

    def verdict(
        self,
        at: datetime,
        domain: str,
        verdict: str,
        simhash: int,
        brand: str | None,
        asn: str,
        registrar: str,
        type_: str = "verdict.created",
    ) -> str:
        vid = f"vrd_{self.n + 1:05d}"
        return self.emit(
            type_,
            at,
            {
                "verdict": verdict,
                "risk_score": {"dangerous": 92, "suspicious": 55, "no_warning_signs": 8}[verdict],
                "input_type": "url",
                "registrable_domain": domain,
                "brand_id": brand,
                "fingerprints": {
                    "dom_simhash": f"{simhash:016x}",
                    "asn": asn,
                    "registrar": registrar,
                    "cert_issuer": "Example CA One",
                },
                "top_signals": [],
            },
            verdict_id=vid,
        )


def generate(seed: int = 7) -> Fixture:
    g = _Gen(seed)
    used = [CAMPAIGN_SIMHASH, KIT_SIMHASH]
    vectors: dict[str, list[float]] = {}
    for i in range(16):  # orthogonal one-hot script vectors: no accidental clustering
        vectors[f"scr_noise_{i:02d}"] = [1.0 if j == i else 0.0 for j in range(16)]

    # --- background noise over ~3 days, deliberately below every threshold ---
    for i in range(60):
        at = T0 + timedelta(minutes=g.rng.randrange(0, 3 * 24 * 60))
        sh = g.far_simhash(used)
        used.append(sh)
        verdict = "no_warning_signs" if i % 6 else "suspicious"
        g.verdict(
            at,
            f"noise-{i:04d}.test",
            verdict,
            sh,
            None,
            f"AS{64600 + i % 7}",
            f"Example Registrar {i % 5}",
        )
    for i in range(4):  # 4 reports on one script (< 5): near miss for R3
        g.emit(
            "report.submitted",
            T0 + timedelta(hours=5, minutes=3 * i),
            {"kind": "scam_link", "script_fingerprint": "scr_noise_00"},
        )
    for i in range(1, 8):  # scattered single reports
        g.emit(
            "report.submitted",
            T0 + timedelta(hours=7 * i),
            {"kind": "scam_link", "script_fingerprint": f"scr_noise_{i:02d}"},
        )
    for i in range(4):  # 4 FP feedbacks on one signal (< 5): near miss for R5
        g.emit(
            "feedback.submitted",
            T0 + timedelta(hours=9, minutes=5 * i),
            {"kind": "false_positive", "signal": "domain.age"},
        )
    for i in range(6):  # FP feedback spread over different signals
        g.emit(
            "feedback.submitted",
            T0 + timedelta(hours=2 * i),
            {"kind": "false_positive", "signal": f"signal.noise_{i}"},
        )
    for i in range(2):  # only 2 lookalikes for the brand, a day before the campaign: near miss for R1
        d = ["falcon-demo-bank-help.test", "falcondemobank-sms.test"][i]
        g.emit(
            "domain.observed",
            T0 - timedelta(days=1) + timedelta(minutes=10 * i),
            {
                "domain_defanged": d.replace(".", "[.]"),
                "brand_candidates": [BRAND],
                "first_seen": _iso(T0 - timedelta(days=1)),
                "source": "ct_log_fixture",
            },
        )

    # --- planted campaign: 4 lookalikes in 38 min sharing one dom_simhash (<= 3 bits apart) ---
    c0 = T0 + timedelta(hours=26)
    campaign_ids: list[str] = []
    for i, (dom, off) in enumerate(
        [
            ("falcon-demo-bank-login.test", 0),
            ("falcondemobank-secure.test", 9),
            ("falcon-demo-bank-verify.test", 21),
            ("falcondem0bank.test", 38),
        ]
    ):
        at = c0 + timedelta(minutes=off)
        campaign_ids.append(
            g.emit(
                "domain.observed",
                at,
                {
                    "domain_defanged": dom.replace(".", "[.]"),
                    "brand_candidates": [BRAND],
                    "first_seen": _iso(at),
                    "source": "ct_log_fixture",
                },
            )
        )
        sh = CAMPAIGN_SIMHASH ^ ((1 << i) - 1 if i else 0)  # 0..3 bits flipped
        campaign_ids.append(
            g.verdict(
                at + timedelta(minutes=2),
                dom,
                "dangerous",
                sh,
                BRAND,
                "AS64500",
                "Example Registrar A",
            )
        )

    # --- kit reuse: 3 unrelated-looking domains (no brand) on one kit over ~3 h ---
    k0 = T0 + timedelta(hours=40)
    kit_ids = [
        g.verdict(
            k0 + timedelta(minutes=m),
            d,
            "dangerous",
            KIT_SIMHASH ^ x,
            None,
            f"AS{64800 + j}",
            f"Example Registrar {j}",
        )
        for j, (d, m, x) in enumerate(
            [
                ("secure-parcel-track.test", 0, 0),
                ("gov-refund-help.test", 70, 0b101),
                ("toll-fine-pay.test", 170, 0b11),
            ]
        )
    ]

    # --- reputation flip: no_warning_signs, then dangerous a day later ---
    sh = g.far_simhash(used)
    flip_ids = [
        g.verdict(
            T0 + timedelta(hours=6),
            "salary-portal-check.test",
            "no_warning_signs",
            sh,
            None,
            "AS64900",
            "Example Registrar 9",
        ),
        g.verdict(
            T0 + timedelta(hours=30),
            "salary-portal-check.test",
            "dangerous",
            sh,
            None,
            "AS64900",
            "Example Registrar 9",
            "verdict.upgraded",
        ),
    ]

    events = sorted(g.events, key=lambda e: (e["occurred_at"], e["event_id"]))
    labels = {
        "incidents": [
            {"type": "campaign", "rule_ids": ["R1", "R2"], "event_ids": sorted(campaign_ids)},
            {"type": "kit_reuse", "rule_ids": ["R2"], "event_ids": sorted(kit_ids)},
            {"type": "reputation_flip", "rule_ids": ["R4"], "event_ids": sorted(flip_ids)},
        ],
        "synthetic": True,
        "note": "Replay fixture, invented .test domains only, brand falcon_demo_bank.",
    }
    return Fixture(events=events, vectors=vectors, labels=labels)
