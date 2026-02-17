from __future__ import annotations

from difflib import SequenceMatcher

from agent.skills.parser import SkillDefinition
from agent.types import SkillCandidate

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None


class SkillRouter:
    def __init__(self, min_score: int = 55) -> None:
        self.min_score = min_score

    @staticmethod
    def _fallback_score(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio() * 100.0

    def _score(self, task: str, skill: SkillDefinition) -> float:
        haystack = " ".join([skill.metadata.name, skill.metadata.description, *skill.metadata.tags])
        if fuzz is not None:
            return float(fuzz.partial_ratio(task, haystack))
        return self._fallback_score(task.lower(), haystack.lower())

    def prefilter(
        self, task: str, skills: list[SkillDefinition], top_k: int, min_score: int | None = None
    ) -> list[SkillCandidate]:
        threshold = min_score if min_score is not None else self.min_score
        scored: list[SkillCandidate] = []
        for skill in skills:
            score = self._score(task, skill)
            if score >= threshold:
                scored.append(
                    SkillCandidate(
                        skill_name=skill.metadata.name,
                        score=round(score, 2),
                        reason="Matched name/description/tags",
                    )
                )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]
