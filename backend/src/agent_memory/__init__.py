"""Compatibility package alias for agent_context_engine."""

from __future__ import annotations

from importlib import import_module

_pkg = import_module("agent_context_engine")

__all__ = getattr(_pkg, "__all__", [])
__path__ = _pkg.__path__
