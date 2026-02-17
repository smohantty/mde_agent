# Provider Setup

## Anthropic

Required env var:

- `ANTHROPIC_API_KEY`

Fallback file (auto-read by Python when env var is not set):

- `./.env` containing `ANTHROPIC_API_KEY=...`

Linux/macOS:

```bash
export ANTHROPIC_API_KEY="your_anthropic_key"
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="your_anthropic_key"
```

## Gemini

Required env var:

- `GEMINI_API_KEY`

Fallback file (auto-read by Python when env var is not set):

- `./.env` containing `GEMINI_API_KEY=...`

Linux/macOS:

```bash
export GEMINI_API_KEY="your_gemini_key"
```

Windows PowerShell:

```powershell
$env:GEMINI_API_KEY="your_gemini_key"
```

## Missing key behavior

If the selected provider key is missing, the run fails fast with `missing_provider_api_key` before any LLM API call.

## Security note

API keys are loaded from environment variables first, then `./.env` fallback values.
They are never written to config files or logs.
