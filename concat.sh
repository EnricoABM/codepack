#!/usr/bin/env bash
# Wrapper de compatibilidade para quem usava o script Bash original.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/codepack.py" "$@"
