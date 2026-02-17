from __future__ import annotations

from agent.skills.registry import SkillRegistry
from agent.skills.router import SkillRouter


def test_prefilter_no_match_with_high_threshold(make_skill, tmp_path) -> None:
    make_skill("skill1", "alpha-tool", "handles alpha")
    make_skill("skill2", "beta-tool", "handles beta")
    skills = SkillRegistry(tmp_path).load()
    router = SkillRouter(min_score=99)
    candidates = router.prefilter("gamma", skills, top_k=5)
    assert candidates == []


def test_prefilter_returns_top_candidates(make_skill, tmp_path) -> None:
    make_skill("skill1", "searcher", "search by keyword")
    make_skill("skill2", "summarizer", "summarize content")
    skills = SkillRegistry(tmp_path).load()
    router = SkillRouter(min_score=10)
    candidates = router.prefilter("search keyword in files", skills, top_k=1)
    assert len(candidates) == 1
