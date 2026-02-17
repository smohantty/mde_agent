---
name: content-summarizer
description: Summarize selected text files into concise bullet points.
version: 0.1.0
tags: [summarize, content, notes]
allowed_tools: [run_command]
action_aliases:
  list_files: run_command
  find_markdown_files: run_command
  identify_markdown_files: run_command
  read_file: run_command
  read_file_content: run_command
  extract_sections: run_command
  extract_key_sections: run_command
  generate_summary: run_command
  aggregate_summaries: run_command
default_action_params:
  list_files:
    command: 'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**"'
  find_markdown_files:
    command: 'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**"'
  identify_markdown_files:
    command: 'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**"'
  read_file:
    command: 'f=$(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 1); if [ -n "$f" ]; then echo "## $f"; sed -n "1,120p" "$f"; else echo "no markdown files found"; fi'
  read_file_content:
    command: 'f=$(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 1); if [ -n "$f" ]; then echo "## $f"; sed -n "1,120p" "$f"; else echo "no markdown files found"; fi'
  extract_sections:
    command: 'f=$(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 1); if [ -n "$f" ]; then echo "## $f"; echo "-- START --"; sed -n "1,40p" "$f"; echo "-- END --"; tail -n 40 "$f"; else echo "no markdown files found"; fi'
  extract_key_sections:
    command: 'f=$(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 1); if [ -n "$f" ]; then echo "## $f"; echo "-- START --"; sed -n "1,40p" "$f"; echo "-- END --"; tail -n 40 "$f"; else echo "no markdown files found"; fi'
  generate_summary:
    command: 'for f in $(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 10); do echo "## $f"; echo "line_count: $(wc -l < "$f")"; echo "headings:"; rg "^#" "$f" | head -n 5; echo; done'
  aggregate_summaries:
    command: 'for f in $(rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n 10); do echo "## $f"; echo "line_count: $(wc -l < "$f")"; echo "headings:"; rg "^#" "$f" | head -n 5; echo; done'
---

# Purpose
Turn long content into concise summaries.

# Steps
1. Identify target files.
2. Extract the first and last sections to preserve context.
3. Produce short summaries and key takeaways.

# Output
Bullet summary with key points and open questions.
