from __future__ import annotations

from pathlib import Path


def is_within_directory(base_dir: Path, target_path: Path) -> bool:
    base = base_dir.resolve()
    target = target_path.resolve()
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def find_out_of_tree_paths(skill_dir: Path, relative_paths: list[str]) -> list[str]:
    invalid: list[str] = []
    for rel in relative_paths:
        candidate = (skill_dir / rel).resolve()
        if not is_within_directory(skill_dir, candidate):
            invalid.append(rel)
    return invalid
