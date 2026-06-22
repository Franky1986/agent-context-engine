#!/usr/bin/env python3
"""Compatibility alias for the Agent Context Engine CLI entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = SKILL_ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from agent_context_engine.interfaces.cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())
