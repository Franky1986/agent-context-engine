"""Interim refactor workspace for Dreaming v2.

The module set in this package is the Wave-0 migration destination from
`v2.py` toward stage- and repository-based architecture.
"""

from .context import DreamV2Context, DreamV2RunArtifacts, DreamV2RunSummary, DreamV2StageContext
from .repositories import DreamV2ReconciliationDecisionRow, DreamV2Repository, DreamV2RunRow, DreamV2SessionRow, DreamV2StageRunRow

__all__ = [
    "DreamV2Context",
    "DreamV2RunArtifacts",
    "DreamV2RunSummary",
    "DreamV2StageContext",
    "DreamV2Repository",
    "DreamV2ReconciliationDecisionRow",
    "DreamV2RunRow",
    "DreamV2SessionRow",
    "DreamV2StageRunRow",
]
