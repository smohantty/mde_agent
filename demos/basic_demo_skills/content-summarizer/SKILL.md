---
name: content-summarizer
description: Summarize selected text files into concise bullet points.
version: 0.1.0
tags: [summarize, content, notes]
allowed_tools: [run_command]
---

# Purpose
Turn long content into concise summaries.

# Steps
1. Identify target files.
2. Extract the first and last sections to preserve context.
3. Produce short summaries and key takeaways.

# Scripts
- `scripts/preview_file.sh <path>`: Preview up to 120 lines from a file on demand.
- Prefer script usage for file preview before composing summaries.

# Output
Bullet summary with key points and open questions.
