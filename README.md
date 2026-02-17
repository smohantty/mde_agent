# Autonomous Skill Agent

A Python 3.12+ autonomous skill-native agent with progressive disclosure, structured event logging, and dual-provider support (Anthropic + Gemini).

## Quickstart

1. Install dependencies:

```bash
uv sync
```

2. Create default config:

```bash
uv run agent config init
```

3. Set an API key (choose provider):

Linux/macOS:

```bash
export ANTHROPIC_API_KEY="your_key"
export GEMINI_API_KEY="your_key"
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="your_key"
$env:GEMINI_API_KEY="your_key"
```

4. Run in dry-run mode first:

```bash
uv run agent run "Summarize markdown files" --skills-dir demos/basic_demo_skills --dry-run
```

5. Run with provider:

```bash
uv run agent run "Summarize markdown files" --skills-dir demos/basic_demo_skills --provider anthropic
```

Run output includes both:

- `events.jsonl` (event stream)
- `llm_transcript.log` (human-readable LLM request/response transcript, including decode mapping)
  - includes `Raw Model Request` payload and `Raw Model Response`

Prompt routing context includes `ALL_SKILL_FRONTMATTER` so the model can choose skills from the full catalog.
Skill delegation is optional: the model can return `selected_skill: null` and complete via direct actions.

## Config discovery order

1. `--config <path>`
2. `./agent.yaml`
3. `~/.config/agent/agent.yaml`
4. built-in defaults

## Commands

- `agent run`
- `agent skills list`
- `agent skills inspect`
- `agent replay`
- `agent config init`
- `agent config validate`

## Tests

```bash
uv run pytest
```

Replay LLM transcript:

```bash
uv run agent replay <run_id> --llm-transcript
```

## Quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```
