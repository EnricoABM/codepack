#!/usr/bin/env bash
# Instala o comando 'codepack' no PATH do usuário sem requerer sudo.
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${CODEPACK_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/codepack}"
BIN_DIR="${CODEPACK_BIN_DIR:-$HOME/.local/bin}"

if [[ ! -f "$SOURCE_DIR/codepack.py" ]]; then
    printf 'Erro: codepack.py não está junto de install.sh.\n' >&2
    exit 1
fi

mkdir -p -- "$DATA_DIR" "$BIN_DIR"
if [[ -e "$BIN_DIR/codepack" ]] && ! grep -Fq '# Managed by Codepack installer' "$BIN_DIR/codepack"; then
    printf 'Erro: %s já existe e não parece ser do Codepack; nada foi sobrescrito.\n' "$BIN_DIR/codepack" >&2
    exit 1
fi

install -m 755 -- "$SOURCE_DIR/codepack.py" "$DATA_DIR/codepack.py"
{
    printf '#!/usr/bin/env bash\n# Managed by Codepack installer\n'
    printf 'exec python3 %q "$@"\n' "$DATA_DIR/codepack.py"
} > "$BIN_DIR/codepack"
chmod 755 -- "$BIN_DIR/codepack"

printf 'Codepack instalado em: %s\n' "$BIN_DIR/codepack"
printf 'Programa Python: %s\n' "$DATA_DIR/codepack.py"
case ":$PATH:" in
    *":$BIN_DIR:"*) printf 'Uso: codepack --help (a partir de qualquer pasta)\n' ;;
    *)
        printf '\nO diretório de comandos ainda não está no PATH.\n'
        printf 'Execute na sessão atual:\n  export PATH="%s:$PATH"\n' "$BIN_DIR"
        printf 'Adicione a mesma linha ao ~/.bashrc ou ~/.zshrc para persistir.\n'
        ;;
esac
