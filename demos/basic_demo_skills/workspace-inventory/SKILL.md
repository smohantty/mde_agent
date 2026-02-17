---
name: workspace-inventory
description: Inventory files and directories in a workspace.
version: 0.1.0
tags: [workspace, inventory, files]
allowed_tools: [run_command]
---

# Purpose
Create a quick inventory of repository files and top-level folders.

# Steps
1. Prefer `rg --files` for fast file listing.
2. Summarize key directories and dominant file types.

# Output
A concise inventory report with counts and notable paths.
