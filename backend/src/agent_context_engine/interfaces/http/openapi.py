from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).resolve().parents[5] / "contracts" / "openapi.yaml"


@lru_cache(maxsize=1)
def openapi_spec() -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised through monitor startup paths
        raise RuntimeError(
            "PyYAML is required to serve /api/openapi.json. "
            "Run `./scripts/agent-context-engine repair-installation --apply` or install backend dependencies into `.venv`."
        ) from exc
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
