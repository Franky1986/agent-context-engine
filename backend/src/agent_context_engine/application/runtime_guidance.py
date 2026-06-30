from __future__ import annotations


RUNTIME_MEMORY_SANDBOX_NOTE = (
    "Sandbox: concrete runtime-memory commands can touch SQLite WAL/SHM files, "
    "locks, audit rows, retrieval logs, or metadata refreshes even when they look "
    "read-only. In filesystem-sandboxed runners, request escalated sandbox access up front."
)


def print_runtime_memory_sandbox_note() -> None:
    print("")
    print(RUNTIME_MEMORY_SANDBOX_NOTE)
