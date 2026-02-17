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
