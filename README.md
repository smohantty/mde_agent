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

3. Set provider credentials (choose provider):

Anthropic credentials:

API key path (direct Anthropic API):

1. Sign in to [console.anthropic.com](https://console.anthropic.com/).
2. Open **Settings -> API Keys**.
3. Create a key and copy it.
4. Set `ANTHROPIC_API_KEY`.

Auth token path (recommended if you have Claude Code installed):

1. Run `claude setup-token` and follow the browser login flow.
2. Copy the issued auth token.
3. Set `ANTHROPIC_AUTH_TOKEN`.

If both are set, this agent prefers `ANTHROPIC_AUTH_TOKEN`.

Linux/macOS:

```bash
export ANTHROPIC_API_KEY="your_key"
export ANTHROPIC_AUTH_TOKEN="your_token"
export GEMINI_API_KEY="your_key"
```

Or create a local `.env` file (auto-loaded by the agent):

```bash
cat > .env <<'EOF'
ANTHROPIC_API_KEY=your_key
ANTHROPIC_AUTH_TOKEN=your_token
GEMINI_API_KEY=your_key
EOF
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="your_key"
$env:ANTHROPIC_AUTH_TOKEN="your_token"
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

6. Run continuously in interactive CLI mode:

```bash
uv run agent chat --skills-dir demos/basic_demo_skills --provider anthropic
```

In `agent chat`, each line is treated as a task. The agent completes the task, keeps session context,
and waits for the next input. Use `Ctrl+D` to exit.
All tasks in one chat session share a single run id and append into the same `events.jsonl` and
`llm_transcript.log` with task-prefixed artifacts.

Run output includes both:

- `events.jsonl` (event stream)
- `llm_transcript.log` (human-readable LLM request/response transcript, including decode mapping)
  - includes `Raw Model Request` payload and `Raw Model Response`
  - every LLM request/response is logged with call-site tagging (`decision_loop`, `final_answer_synthesis`)

Prompt routing context includes `ALL_SKILL_FRONTMATTER` so the model can choose skills from the full catalog.
Skill delegation is optional: the model can return `selected_skill: null` and complete via direct actions.

## Config discovery order

1. `--config <path>`
2. `./agent.yaml`
3. `~/.config/agent/agent.yaml`
4. built-in defaults

## Commands

- `agent run`
- `agent chat`
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
