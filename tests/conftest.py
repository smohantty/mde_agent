from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def make_skill(tmp_path: Path):
    def _make(
        folder: str,
        name: str,
        description: str,
        extra_body: str = "",
        extra_frontmatter: list[str] | None = None,
    ) -> Path:
        skill_dir = tmp_path / folder
        (skill_dir / "references").mkdir(parents=True, exist_ok=True)
        (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (skill_dir / "references" / "a.md").write_text("reference content", encoding="utf-8")
        (skill_dir / "scripts" / "run.sh").write_text(
            "#!/usr/bin/env bash\necho hi\n", encoding="utf-8"
        )
        frontmatter_extra = extra_frontmatter or []
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    f"name: {name}",
                    f"description: {description}",
                    "version: 0.1.0",
                    "tags: [demo, test]",
                    "allowed_tools: [run_command]",
                    *frontmatter_extra,
                    "---",
                    "",
                    "# Purpose",
                    "Do something useful.",
                    "",
                    "# Steps",
                    "1. Step one",
                    extra_body,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return skill_dir

    return _make
