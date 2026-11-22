"""Non-Python package data (yaml, txt, py.typed) must ship in the built wheel."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
SRC = PKG / "src" / "falcon_core"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_package_data_ships_in_wheel(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603
        [shutil.which("uv") or "uv", "build", "--wheel", "--out-dir", str(tmp_path), str(PKG)],
        check=True,
        capture_output=True,
    )
    wheel = next(tmp_path.glob("falcon_core-*.whl"))
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    expected = {
        f"falcon_core/{p.relative_to(SRC).as_posix()}"
        for p in SRC.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    missing = sorted(expected - names)
    assert not missing, f"files missing from wheel: {missing}"
    assert "falcon_core/py.typed" in names
