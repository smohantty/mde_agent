from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.types import SkillMetadata


@dataclass
class SkillDefinition:
    metadata: SkillMetadata
    skill_dir: Path
    skill_md_path: Path
    body: str
    sections: dict[str, str]
    references: list[str]
    scripts: list[str]


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        raise ValueError("SKILL.md is missing YAML frontmatter start delimiter")

    marker = "\n---\n"
    end_idx = raw.find(marker, 4)
    if end_idx < 0:
        raise ValueError("SKILL.md is missing YAML frontmatter end delimiter")

    frontmatter = raw[4:end_idx]
    body = raw[end_idx + len(marker) :]
    data = yaml.safe_load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a mapping")
    return data, body


def _parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "Overview"
    buffer: list[str] = []

    for line in body.splitlines():
        if line.startswith("#"):
            sections[current] = "\n".join(buffer).strip()
            current = line.lstrip("#").strip() or "Untitled"
            buffer = []
        else:
            buffer.append(line)

    sections[current] = "\n".join(buffer).strip()
    return {k: v for k, v in sections.items() if v}


def _index_relative_files(base: Path) -> list[str]:
    if not base.exists():
        return []
    files = [p for p in base.rglob("*") if p.is_file()]
    return [str(p.relative_to(base.parent)).replace("\\", "/") for p in sorted(files)]


def parse_skill(skill_dir: Path) -> SkillDefinition:
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise ValueError(f"Missing SKILL.md in {skill_dir}")

    raw = skill_md_path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)

    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    if not name:
        raise ValueError(f"Skill frontmatter must include non-empty 'name' in {skill_md_path}")
    if not description:
        raise ValueError(
            f"Skill frontmatter must include non-empty 'description' in {skill_md_path}"
        )

    tags_raw = frontmatter.get("tags", [])
    tags = [str(item) for item in tags_raw] if isinstance(tags_raw, list) else []
    allowed_tools_raw = frontmatter.get("allowed_tools", [])
    allowed_tools = (
        [str(item) for item in allowed_tools_raw] if isinstance(allowed_tools_raw, list) else []
    )
    action_aliases_raw = frontmatter.get("action_aliases", {})
    action_aliases = (
        {str(key): str(value) for key, value in action_aliases_raw.items()}
        if isinstance(action_aliases_raw, dict)
        else {}
    )
    default_action_params_raw = frontmatter.get("default_action_params", {})
    default_action_params: dict[str, dict[str, Any]] = {}
    if isinstance(default_action_params_raw, dict):
        for key, value in default_action_params_raw.items():
            if isinstance(value, dict):
                default_action_params[str(key)] = {
                    str(p_key): p_val for p_key, p_val in value.items()
                }
    version = str(frontmatter.get("version", "0.1.0"))

    references = _index_relative_files(skill_dir / "references")
    scripts = _index_relative_files(skill_dir / "scripts")

    metadata = SkillMetadata(
        name=name,
        description=description,
        tags=tags,
        version=version,
        allowed_tools=allowed_tools,
        references_index=references,
        action_aliases=action_aliases,
        default_action_params=default_action_params,
    )

    return SkillDefinition(
        metadata=metadata,
        skill_dir=skill_dir,
        skill_md_path=skill_md_path,
        body=body,
        sections=_parse_sections(body),
        references=references,
        scripts=scripts,
    )
