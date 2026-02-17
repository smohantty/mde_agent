---
name: keyword-search-extractor
description: Search files by keyword and extract relevant snippets.
version: 0.1.0
tags: [search, grep, extract]
allowed_tools: [run_command]
---

# Purpose
Find where important terms appear and capture useful excerpts.

# Steps
1. Use `rg -n "<keyword>"` for line-level matches.
2. Group matches by file and summarize.

# Output
A structured list of findings by file and line.
