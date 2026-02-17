# Troubleshooting

## missing_provider_api_key

Set `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` depending on selected provider.

## No skills found

Check `--skills-dir` and ensure each skill has a `SKILL.md` file with valid frontmatter.

## Decode failed

The model response did not match expected structured output schema.

## Max turns exceeded

Increase `runtime.max_turns` or simplify the task.
