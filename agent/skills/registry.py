from __future__ import annotations

from pathlib import Path

from agent.skills.parser import SkillDefinition, parse_skill


class SkillRegistry:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load(self) -> list[SkillDefinition]:
        if not self.skills_dir.exists():
            return []

        skill_defs: list[SkillDefinition] = []
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue
            skill_defs.append(parse_skill(child))
        return skill_defs

    @staticmethod
    def by_name(skills: list[SkillDefinition], name: str) -> SkillDefinition | None:
        for skill in skills:
            if skill.metadata.name == name:
                return skill
        return None
