from __future__ import annotations

from pathlib import Path

import pytest

from agent.skills.parser import parse_skill


def test_parse_skill_success(make_skill) -> None:
    skill_dir = make_skill("skill1", "skill-one", "Skill description")
    parsed = parse_skill(skill_dir)
    assert parsed.metadata.name == "skill-one"
    assert parsed.references


def test_parse_skill_action_aliases_and_defaults(make_skill) -> None:
    skill_dir = make_skill(
        "skill2",
        "skill-two",
        "Skill with action mappings",
        extra_frontmatter=[
            "action_aliases:",
            "  list_files: run_command",
            "default_action_params:",
            "  list_files:",
            "    command: rg --files",
        ],
    )
    parsed = parse_skill(skill_dir)
    assert parsed.metadata.action_aliases["list_files"] == "run_command"
    assert parsed.metadata.default_action_params["list_files"]["command"] == "rg --files"


def test_parse_skill_missing_description(tmp_path: Path) -> None:
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\n---\n\n# Purpose\nNo description\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        parse_skill(skill_dir)
