#!/usr/bin/env bash
# Remove apenas os arquivos instalados pelo Codepack; preserva dados gerados.
set -euo pipefail
DATA_DIR="${CODEPACK_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/codepack}"
BIN_DIR="${CODEPACK_BIN_DIR:-$HOME/.local/bin}"
if [[ -f "$BIN_DIR/codepack" ]] && grep -Fq '# Managed by Codepack installer' "$BIN_DIR/codepack"; then
    rm -- "$BIN_DIR/codepack"
    printf 'Launcher removido: %s\n' "$BIN_DIR/codepack"
fi
if [[ -f "$DATA_DIR/codepack.py" ]]; then
    rm -- "$DATA_DIR/codepack.py"
    rmdir -- "$DATA_DIR" 2>/dev/null || true
    printf 'Programa removido: %s\n' "$DATA_DIR/codepack.py"
fi
