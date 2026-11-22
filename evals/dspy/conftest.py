"""Makes the flat fl_* modules importable (evals/dspy has no __init__.py on purpose: a package named `dspy`
on sys.path would shadow the real library)."""

import sys
from pathlib import Path

HERE = str(Path(__file__).parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
