"""Snapshot store under ``data/private/snapshots`` (a mounted volume). Never served to callers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _write(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _mkdir(self, path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)

    def save_screenshot(self, png: bytes) -> str:
        """Store a /render screenshot; returns its sha256 (the file name)."""
        sha = hashlib.sha256(png).hexdigest()
        d = self.root / "screens"
        self._mkdir(d)
        # Group/other readable on purpose: the API container (another uid) mounts this volume read-only to
        # build the operator evidence pack. Only screens/ is relaxed; DOMs and features stay 0600/0700.
        os.chmod(d, 0o755)  # noqa: S103 - intentional, see above
        _write(d / f"{sha}.png", png, 0o644)
        return sha

    def save_snapshot(
        self,
        *,
        dom: str,
        screenshot: bytes | None,
        redirects: list[dict[str, Any]],
        network: dict[str, Any],
        features: dict[str, Any],
    ) -> tuple[str, str, str | None]:
        """Write {dom, screenshot, redirect chain, network summary} for evals replay.

        Returns ``(snapshot_id, dom_sha256, screenshot_sha256)``; the id is the DOM sha256.
        """
        dom_bytes = dom.encode()
        snapshot_id = hashlib.sha256(dom_bytes).hexdigest()
        d = self.root / snapshot_id
        self._mkdir(d)
        _write(d / "dom.html", dom_bytes)
        shot_sha = None
        if screenshot:
            shot_sha = hashlib.sha256(screenshot).hexdigest()
            _write(d / "screenshot.png", screenshot)
        _write(d / "redirects.json", json.dumps(redirects, ensure_ascii=False).encode())
        _write(d / "network.json", json.dumps(network, ensure_ascii=False).encode())
        _write(d / "features.json", json.dumps(features, ensure_ascii=False).encode())
        return snapshot_id, snapshot_id, shot_sha
