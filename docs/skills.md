# Skills

Each skill lives in its own directory and must include `SKILL.md` with YAML frontmatter.

Expected layout:

```text
<skill-name>/
  SKILL.md
  references/
  scripts/
```

The orchestrator uses progressive disclosure:

1. Stage 0: frontmatter metadata
2. Stage 1: summary sections
3. Stage 2: requested references
4. Stage 3: script descriptors

Optional frontmatter keys for action normalization:

- `action_aliases`: map provider/model-specific action names to canonical actions (`run_command`, `call_skill`, `ask_user`, `finish`).
- `default_action_params`: map action names to default `params` payloads used when the model omits required fields.

Example:

```yaml
action_aliases:
  list_files: run_command
default_action_params:
  list_files:
    command: rg --files
```

## See also

- [Architecture: Skill System](architecture.md#skill-system) — class diagram for SkillDefinition, SkillRegistry, SkillRouter, DisclosureEngine
- [Decision Loop: Self-Handoff Detection & Recovery](decision-loop.md#self-handoff-detection--recovery) — how `default_action_params` are used in recovery
- [Architecture: Action System](architecture.md#action-system) — canonical action types and decoder normalization
