"""Shared helpers for the eval tooling: paths, keyed hashing, git SHA, URL refang.

Public outputs never carry a plain URL or domain: they carry HMAC-SHA256 hashes keyed with a local secret
(``data/private/hash.key``, generated on first use, never committed), so a hash cannot be reversed by guessing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "evals" / "manifests"
ITEMS_MANIFEST = MANIFEST_DIR / "items.manifest.jsonl"
SPLITS_LOCK = ROOT / "evals" / "splits.lock"
RESULTS_DIR = ROOT / "evals" / "results"
BASELINE = ROOT / "evals" / "baseline.json"
LEGIT_CSV = ROOT / "evals" / "datasets" / "legit_urls.csv"
MODEL_DIR = ROOT / "packages" / "falcon_core" / "src" / "falcon_core" / "scoring" / "model"
PARAMS_YAML = ROOT / "packages" / "falcon_core" / "src" / "falcon_core" / "scoring" / "params.yaml"

SEED = 20261122


def data_dir() -> Path:
    """FL_DATA_DIR (the ``data`` dir) or the MAIN checkout's data dir, so worktrees share data/private."""
    env = os.environ.get("FL_DATA_DIR")
    if env:
        return Path(env)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        main = Path(out).parent / "data"
        if (main / "private").exists():
            return main
    except (OSError, subprocess.CalledProcessError):
        pass
    return ROOT / "data"


def private_dir() -> Path:
    return data_dir() / "private"


def get_key(create: bool = False) -> bytes:
    """The HMAC key. ``create=True`` generates it on first use; otherwise a missing key is an error."""
    path = private_dir() / "hash.key"
    if not path.exists():
        if not create:
            raise FileNotFoundError("data/private/hash.key is missing: run `python -m evals.datasets.build` first")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    return bytes.fromhex(path.read_text().strip())


def hmac_hex(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def refang(url: str) -> str:
    """Undo the defanged scheme prefix used in committed CSVs (``hxxps://`` -> ``https://``)."""
    return url.replace("hxxp", "http", 1) if url.startswith("hxxp") else url


_extractor = None


def registrable_domain(url: str) -> str:
    """eTLD+1 using the bundled PSL snapshot incl. private domains (no network); same rule as the collector."""
    global _extractor
    import tldextract

    if _extractor is None:
        _extractor = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
    host = urlsplit(url).hostname or ""
    ext = _extractor(host)
    return (ext.top_domain_under_public_suffix or host).lower()


def git_sha(dirty: bool = True) -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty_out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return sha + ("-dirty" if dirty and dirty_out else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def load_lock_dataset_hash() -> str:
    return str(json.loads(SPLITS_LOCK.read_text())["dataset_hash"])
