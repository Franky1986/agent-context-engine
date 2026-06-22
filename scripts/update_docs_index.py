#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_INDEX = REPO_ROOT / "docs" / "index.md"
START = "<!-- spec-index:start -->"
END = "<!-- spec-index:end -->"


def _title_for(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    return path.name


def _category_for(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).parts
    if parts[:3] == ("backend", "src", "agent_memory"):
        if len(parts) > 3:
            return f"Backend / {parts[3]}"
        return "Backend"
    if parts[:3] == ("frontend", "src", "features"):
        return "Frontend features"
    if parts[0] == "docs":
        return "Documentation"
    return "Other"


def spec_paths() -> list[Path]:
    ignored = {".git", "node_modules", "__pycache__", "dist"}
    paths: list[Path] = []
    for path in REPO_ROOT.rglob("*.spec.md"):
        if any(part in ignored for part in path.parts):
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(REPO_ROOT).as_posix())


def render_spec_index() -> str:
    grouped: dict[str, list[Path]] = {}
    for path in spec_paths():
        grouped.setdefault(_category_for(path), []).append(path)

    lines = [START, ""]
    if not grouped:
        lines.append("_No `.spec.md` files found yet._")
    for category in sorted(grouped):
        lines.append(f"### {category}")
        for path in grouped[category]:
            rel = path.relative_to(REPO_ROOT).as_posix()
            title = _title_for(path)
            lines.append(f"- [{title}](../{rel}) - `{rel}`")
        lines.append("")
    lines.append(END)
    return "\n".join(lines).rstrip() + "\n"


def desired_index_text(current: str) -> str:
    generated = render_spec_index()
    if START in current and END in current:
        before, rest = current.split(START, 1)
        _, after = rest.split(END, 1)
        return before.rstrip() + "\n\n" + generated + after.lstrip()
    suffix = "\n" if current.endswith("\n") else "\n\n"
    return current + suffix + generated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail when docs/index.md is not in sync")
    args = parser.parse_args()

    current = DOCS_INDEX.read_text(encoding="utf-8") if DOCS_INDEX.exists() else "# Documentation Index\n"
    desired = desired_index_text(current)
    if args.check:
        if current != desired:
            print("docs/index.md is out of date. Run: python3 scripts/update_docs_index.py", file=sys.stderr)
            return 1
        print("docs/index.md spec index is up to date")
        return 0
    DOCS_INDEX.write_text(desired, encoding="utf-8")
    print(f"updated {DOCS_INDEX.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
