"""Ensures `CODEBASE_MAP.md` stays 100% synchronized with the live repository structure."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = REPO_ROOT / "CODEBASE_MAP.md"

_IGNORED_TOP_LEVEL = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "build",
    "dist",
    "smriti_v2.egg-info",
}

_TREE_ENTRY_RE = re.compile(r"^(?P<prefix>[│ ]*)(?:├── |└── )(?P<name>[^\s#]+)")


def _parse_documented_files_from_map(markdown_text: str) -> set[str]:
    in_tree_block = False
    stack: list[str] = []
    documented_files: set[str] = set()

    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```text"):
            in_tree_block = True
            continue
        if in_tree_block and stripped == "```":
            break
        if not in_tree_block:
            continue

        match = _TREE_ENTRY_RE.match(line)
        if not match:
            continue

        depth = len(match.group("prefix")) // 4
        entry_name = match.group("name")
        stack = stack[:depth]

        if entry_name.endswith("/"):
            stack.append(entry_name.rstrip("/"))
        else:
            rel_path = "/".join([*stack, entry_name])
            documented_files.add(rel_path)

    return documented_files


def _collect_actual_repo_files() -> set[str]:
    actual_files: set[str] = set()
    for path in REPO_ROOT.rglob("*"):
        rel_parts = path.relative_to(REPO_ROOT).parts
        if not rel_parts or rel_parts[0] in _IGNORED_TOP_LEVEL:
            continue
        if any(part == "__pycache__" or part.endswith(".egg-info") for part in rel_parts):
            continue
        if path.is_file():
            if path.name.startswith(".env") and path.name != ".env.example":
                continue
            actual_files.add("/".join(rel_parts))
    return actual_files


def test_codebase_map_matches_every_live_repo_file() -> None:
    assert MAP_PATH.exists(), "CODEBASE_MAP.md must exist at the repository root."
    documented = _parse_documented_files_from_map(MAP_PATH.read_text(encoding="utf-8"))
    actual = _collect_actual_repo_files()

    missing_in_map = sorted(actual - documented)
    stale_in_map = sorted(documented - actual)

    assert not missing_in_map, (
        f"Files exist in repo but are missing from CODEBASE_MAP.md: {missing_in_map}"
    )
    assert not stale_in_map, (
        f"Stale entries in CODEBASE_MAP.md no longer exist on disk: {stale_in_map}"
    )
