#!/usr/bin/env bash
set -euo pipefail
file="${1:-README.md}"
if [[ -f "$file" ]]; then
  sed -n '1,120p' "$file"
else
  echo "File not found: $file" >&2
  exit 1
fi
