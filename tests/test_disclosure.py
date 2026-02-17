from __future__ import annotations

from agent.skills.disclosure import DisclosureEngine
from agent.skills.parser import parse_skill


def test_disclosure_stage1(make_skill) -> None:
    skill_dir = make_skill("skill1", "alpha", "desc")
    skill = parse_skill(skill_dir)
    engine = DisclosureEngine(max_bytes=1000, max_tokens=1000)
    data = engine.stage1(skill)
    assert data.stage == 1
    assert data.snippets


def test_disclosure_stage2_blocks_path_traversal(make_skill) -> None:
    skill_dir = make_skill("skill1", "alpha", "desc")
    skill = parse_skill(skill_dir)
    engine = DisclosureEngine(max_bytes=1000, max_tokens=1000)
    data = engine.stage2(skill, ["../secrets.txt", "references/a.md"])
    assert any(key.startswith("warning:") for key in data.snippets)
    assert "references/a.md" in data.snippets
