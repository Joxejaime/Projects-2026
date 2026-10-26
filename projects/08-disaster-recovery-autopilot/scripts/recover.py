#!/usr/bin/env python3
"""Entry point for playbooks: `python scripts/recover.py restore`. Same as `python -m recovery`, runnable from any directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recovery.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
