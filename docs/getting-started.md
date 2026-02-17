# Getting Started

## Install

```bash
uv sync
```

## Initialize config

```bash
uv run agent config init
```

## Dry run

```bash
uv run agent run "inventory workspace" --skills-dir demos/basic_demo_skills --dry-run
```

## First real run

```bash
uv run agent run "create a checklist" --skills-dir demos/basic_demo_skills --provider gemini
```
