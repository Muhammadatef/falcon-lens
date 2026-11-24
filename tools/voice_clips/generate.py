"""Entry point: `uv run --extra mlx python generate.py --engine macos --lang ar_ae --out ../../web/public/voice/ar_ae`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_clips.generate import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
