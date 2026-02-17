#!/usr/bin/env bash
set -euo pipefail
keyword="${1:-TODO}"
rg -n "$keyword" || true
