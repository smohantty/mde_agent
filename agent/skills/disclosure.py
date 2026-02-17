from __future__ import annotations

from dataclasses import dataclass, field

from agent.security.provenance import find_out_of_tree_paths
from agent.skills.parser import SkillDefinition


@dataclass
class DisclosedContext:
    stage: int
    snippets: dict[str, str] = field(default_factory=dict)
    total_bytes: int = 0
    total_tokens: int = 0


class DisclosureEngine:
    def __init__(self, max_bytes: int, max_tokens: int) -> None:
        self.max_bytes = max_bytes
        self.max_tokens = max_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return (len(text) + 3) // 4

    def stage1(self, skill: SkillDefinition) -> DisclosedContext:
        snippets: dict[str, str] = {}
        keys = list(skill.sections.keys())[:2]
        for key in keys:
            snippets[f"section:{key}"] = skill.sections[key]

        content = "\n\n".join(snippets.values())
        return DisclosedContext(
            stage=1,
            snippets=snippets,
            total_bytes=len(content.encode("utf-8")),
            total_tokens=self.estimate_tokens(content),
        )

    def stage2(self, skill: SkillDefinition, requested_paths: list[str]) -> DisclosedContext:
        invalid = find_out_of_tree_paths(skill.skill_dir, requested_paths)
        safe_paths = [p for p in requested_paths if p not in invalid]

        snippets: dict[str, str] = {}
        used_bytes = 0
        used_tokens = 0
        for rel in safe_paths:
            absolute = (skill.skill_dir / rel).resolve()
            if not absolute.exists() or not absolute.is_file():
                continue
            text = absolute.read_text(encoding="utf-8", errors="replace")
            text_bytes = len(text.encode("utf-8"))
            text_tokens = self.estimate_tokens(text)
            if used_bytes + text_bytes > self.max_bytes:
                continue
            if used_tokens + text_tokens > self.max_tokens:
                continue
            snippets[rel] = text
            used_bytes += text_bytes
            used_tokens += text_tokens

        for rel in invalid:
            snippets[f"warning:{rel}"] = "Blocked by provenance validation"

        return DisclosedContext(
            stage=2,
            snippets=snippets,
            total_bytes=used_bytes,
            total_tokens=used_tokens,
        )

    def stage3(self, skill: SkillDefinition) -> DisclosedContext:
        snippets: dict[str, str] = {}
        for rel in skill.scripts:
            snippets[f"script:{rel}"] = "declared"

        content = "\n".join(snippets.keys())
        return DisclosedContext(
            stage=3,
            snippets=snippets,
            total_bytes=len(content.encode("utf-8")),
            total_tokens=self.estimate_tokens(content),
        )
