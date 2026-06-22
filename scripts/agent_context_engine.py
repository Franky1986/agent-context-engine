#!/usr/bin/env python3
"""Agent Context Engine CLI entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = SKILL_ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from agent_context_engine.interfaces.cli.main import main
from agent_context_engine.infrastructure.db import connect
from agent_context_engine.application.summaries import parse_iso, repair_summary_windows, summarize_window


if __name__ == "__main__":
    raise SystemExit(main())
