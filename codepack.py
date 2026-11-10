#!/usr/bin/env python3
"""Codepack: agregador de código com CLI e TUI, sem dependências obrigatórias."""

from __future__ import annotations

import argparse
import base64
import codecs
import fnmatch
import json
import lzma
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from collections.abc import Iterator

VERSION = "3.0.0"
FORMATS = ("txt", "json", "ndjson", "tree", "tree-dirs", "tree-json")
OUTPUT_NAMES = {
    "txt": "combinado.txt", "json": "combinado.json",
    "ndjson": "combinado.ndjson", "tree": "estrutura.txt",
    "tree-dirs": "estrutura_dirs.txt", "tree-json": "estrutura.json",
}
# Nomes de diretórios descartáveis, nunca código-fonte indispensável.
HEAVY_DIRS = {
    ".git", "node_modules", "dist", "build", "target", ".venv", "venv",
    "__pycache__", ".gradle", ".next", ".nuxt", ".turbo", ".cache",
    "coverage", ".idea", "out", "vendor", ".pytest_cache", ".mypy_cache",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz",
    ".pdf", ".zip", ".tar", ".gz", ".xz", ".7z", ".rar", ".jar",
    ".class", ".pyc", ".exe", ".dll", ".so", ".o", ".a", ".bin",
    ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".webm",
    ".mov", ".sqlite", ".db", ".wasm", ".lockb", ".map",
}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".env.development",
                   ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
                   "credentials.json", "service-account.json", "secrets.yaml", "secrets.yml"}
SENSITIVE_EXTS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
LOCKFILE_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock",
    "Gemfile.lock", "gradle.lockfile",
}
LANGUAGES = {
    "java": "java", "python": "py", "js": "js,jsx,mjs,cjs",
    "javascript": "js,jsx,mjs,cjs", "ts": "ts,tsx,mts,cts",
    "typescript": "ts,tsx,mts,cts", "c": "c,h", "cpp": "cpp,hpp,h,cc",
    "c++": "cpp,hpp,h,cc", "go": "go", "rust": "rs", "bash": "sh,bash",
    "sh": "sh", "kotlin": "kt,kts", "html": "html,htm", "css": "css,scss",
    "json": "json", "yaml": "yml,yaml", "sql": "sql", "react": "tsx,jsx",
}


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codepack",
        description=("Empacote arquivos do diretório atual para análise por IA, "
                     "com CLI e TUI interativa (estilo lazygit)."),
        epilog="""Exemplos:
  codepack                               Gerar combinado.txt da pasta atual
  codepack --tui                         Interface interativa
  codepack -m --compact --max-tokens 12000  Contexto econômico para IA
  codepack --heavy                       Incluir Git, dependências, builds e binários
  codepack --heavy --binary skip         Incluir arquivos grandes, pular binários
  codepack --heavy -j -o projeto.json    Exportar tudo em JSON (binários em base64)
  codepack /outro/projeto -o export.txt  Ler outro projeto, salvar no diretório atual
  codepack --lang typescript --ext json  Filtrar arquivos TS/TSX e JSON
  codepack -m -T                         Árvore sem artefatos

  RAIZ: por padrão é o diretório de onde o comando foi chamado (CWD).
  SAÍDA: por padrão é gravada no CWD, mesmo com raiz explicitamente diferente.
  HEAVY: percorre inclusive .git e arquivos ignorados pelo Git. Arquivos de
  segredo conhecidos continuam protegidos, salvo --include-sensitive.
  Binários são codificados em base64, o que pode aumentar MUITO os tokens.
  --compact modifica espaços em branco; --compress economiza bytes, NÃO tokens.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p.add_argument("root", nargs="?", type=Path, default=Path("."),
                   help="pasta para ler (padrão: diretório atual; saída no CWD)")
    f = p.add_argument_group("seleção de arquivos")
    f.add_argument("-i", "--include", metavar="CAMINHO", action="append", default=[],
                   help="incluir caminho, pasta ou glob; repetível")
    f.add_argument("-e", "--exclude", metavar="PADRÃO", action="append", default=[],
                   help="excluir caminho, pasta ou glob; repetível")
    f.add_argument("-nh", "--no-hidden", action="store_true", help="ignorar arquivos/pastas ocultos")
    modes = f.add_mutually_exclusive_group()
    modes.add_argument("-m", "--minimal", action="store_true",
                       help="ignorar caches, dependências, builds e lockfiles")
    modes.add_argument("-H", "--heavy", action="store_true",
                       help="incluir tudo: .git, ignored, dependências, arquivos grandes e binários")
    f.add_argument("--include-sensitive", action="store_true",
                   help="permitir arquivos conhecidos de segredo (risco: revise antes de compartilhar)")
    f.add_argument("--no-gitignore", action="store_true",
                   help="não aplicar regras do .gitignore (por padrão usa Git se disponível)")
    f.add_argument("--ext", metavar="EXT,...", default="",
                   help="extensões: py,js,tsx (sem pontos)")
    f.add_argument("--lang", metavar="LINGUAGEM", default="",
                   help="java, python, typescript, react, go, rust, etc.; combina com --ext")
    f.add_argument("--max-size", metavar="TAMANHO", type=parse_size,
                   help="tamanho máximo por arquivo: 100k, 2M, 1G (base 1024)")
    f.add_argument("--binary", choices=("auto", "skip", "base64"), default="auto",
                   help="binários: auto (base64 em --heavy, skip caso contrário), skip ou base64")

    o = p.add_argument_group("formato e destino")
    fmt = o.add_mutually_exclusive_group()
    fmt.add_argument("-j", "--json", dest="format", action="store_const", const="json", help="JSON estruturado")
    fmt.add_argument("-nj", "--ndjson", dest="format", action="store_const", const="ndjson", help="um JSON por linha")
    fmt.add_argument("-T", "--tree", dest="format", action="store_const", const="tree", help="árvore textual compacta")
    fmt.add_argument("-Td", "--tree-dirs", dest="format", action="store_const", const="tree-dirs", help="só os diretórios")
    fmt.add_argument("-Tj", "--tree-json", dest="format", action="store_const", const="tree-json", help="árvore em JSON")
    fmt.add_argument("--format", choices=FORMATS, help="formato da exportação (padrão: txt)")
    o.add_argument("-o", "--output", metavar="ARQUIVO", type=Path,
                   help="caminho do arquivo de saída (padrão: combinado/estrutura por formato)")
    o.add_argument("-c", "--compress", action="store_true", help="comprimir em .xz após a geração")
    o.add_argument("-C", "--copy", action="store_true", help="copiar TEXTO da saída para clipboard")

    t = p.add_argument_group("economia de tokens")
    t.add_argument("--compact", action="store_true",
                   help="remover linhas vazias e espaços finais (altera conteúdo textual)")
    t.add_argument("--max-tokens", type=positive_int, metavar="N",
                   help="limitar saída; arquivos que ultrapassam o orçamento são pulados inteiros")
    t.add_argument("--tokenizer", choices=("heuristic", "tiktoken"), default="heuristic",
                   help="estimativa bytes/4 (padrão) ou tiktoken opcional")
    t.add_argument("--encoding", default="o200k_base",
                   help="encoding do tiktoken opcional (padrão: o200k_base)")

    a = p.add_argument_group("execução")
    a.add_argument("--tui", action="store_true", help="abrir interface de dois painéis, tipo lazygit")
    a.add_argument("-n", "--dry-run", action="store_true", help="simular sem criar ou alterar arquivos")
    a.add_argument("-l", "--logs", action="store_true", help="exibir arquivos incluídos e ignorados por orçamento")
    a.add_argument("--version", action="version", version=f"codepack {VERSION}")
    p.set_defaults(format="txt")
    return p


def parse_size(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*", value, re.I)
    if not m:
        raise argparse.ArgumentTypeError("use 100k, 2M, 1G ou um número em bytes")
    amount = float(m.group(1))
    factor = 1024 ** ("kmgt".find(m.group(2).lower()) + 1) if m.group(2) else 1
    size = int(amount * factor)
    if size < 1:
        raise argparse.ArgumentTypeError("o tamanho deve ser positivo")
    return size


def positive_int(value: str) -> int:
    try:
        number = int(value)
        if number >= 1:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("use um inteiro positivo")


def human_size(n: int) -> str:
    amount = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{n} B"


class TokenCounter:
    def __init__(self, mode: str, encoding: str):
        self.mode = "heuristic"
        self.encoder = None
        if mode != "heuristic":
            try:
                import tiktoken  # dependência opcional
                self.encoder = tiktoken.get_encoding(encoding)
                self.mode = f"tiktoken/{encoding}"
            except (ImportError, ValueError, KeyError) as exc:
                if mode == "tiktoken":
                    raise ValueError(f"tiktoken não disponível: {exc}") from exc

    def count(self, value: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(value, disallowed_special=()))
        # Aproximação conservadora para UTF-8; NÃO é contagem exata do modelo.
        return math.ceil(len(value.encode("utf-8")) / 4)


@dataclass(frozen=True)
class Entry:
    rel: str
    path: Path
    size: int


def norm_pattern(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").strip("/")


def path_matches(rel: str, pattern: str) -> bool:
    pattern = norm_pattern(pattern)
    if not pattern:
        return False
    if rel == pattern or rel.startswith(pattern + "/"):
        return True
    if fnmatch.fnmatchcase(rel, pattern):
        return True
    # *.log casa em qualquer diretório, mas 'src/*.log' não.
    return "/" not in pattern and any(fnmatch.fnmatchcase(part, pattern) for part in rel.split("/"))


def git_list_files(root: Path) -> list[str] | None:
    if not shutil.which("git"):
        return None
    test = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, check=False)
    if test.returncode != 0 or test.stdout.strip() != b"true":
        return None
    result = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                             "--exclude-standard", "-z"], capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return [os.fsdecode(s) for s in result.stdout.split(b"\0") if s]


def binary_policy(args: argparse.Namespace) -> str:
    """Decide a serialização de binários sem depender do formato de saída."""
    return ("base64" if args.heavy else "skip") if args.binary == "auto" else args.binary


def scan_files(root: Path, args: argparse.Namespace) -> list[Entry]:
    excludes = list(args.exclude)
    if not args.heavy:
        excludes.append(".git")
    if args.minimal:
        excludes.extend(HEAVY_DIRS)
    output = output_path(args).resolve()
    compressed_output = Path(str(output) + ".xz") if output.suffix != ".xz" else output
    policy = binary_policy(args)
    previous_outputs = {*OUTPUT_NAMES.values(),
                        *(name + ".xz" for name in OUTPUT_NAMES.values())}
    ext: set[str] = {e.strip().lstrip(".").lower() for e in args.ext.split(",") if e.strip()}
    if args.lang:
        ext.update(LANGUAGES[args.lang.lower()].split(","))
    files: list[Entry] = []

    def allowed(rel: str, path: Path) -> bool:
        parts = rel.split("/")
        if args.no_hidden and any(part.startswith(".") for part in parts):
            return False
        if any(path_matches(rel, pat) for pat in excludes):
            return False
        if args.include and not any(path_matches(rel, pat) for pat in args.include):
            return False
        if not args.include_sensitive and (path.name in SENSITIVE_NAMES or
                                           (path.name.startswith(".env.") and path.name not in (".env.example", ".env.sample", ".env.template")) or
                                           path.suffix.lower() in SENSITIVE_EXTS):
            return False
        if args.minimal and path.name in LOCKFILE_NAMES:
            return False
        if policy == "skip" and path.suffix.lower() in BINARY_SUFFIXES:
            return False
        if ext and path.suffix.lower().removeprefix(".") not in ext:
            return False
        try:
            if not path.is_file() or path.is_symlink():
                return False
            # Evita auto-inclusão e crescimento exponencial em execuções repetidas.
            absolute_path = path.absolute()
            if absolute_path in (output, compressed_output):
                return False
            if path.parent == root and path.name in previous_outputs:
                return False
            size = path.stat().st_size
        except OSError:
            return False
        if args.max_size is not None and size > args.max_size:
            return False
        files.append(Entry(rel, path, size))
        return True

    # --heavy precisa enxergar arquivos ignorados pelo Git e o próprio .git.
    git_files = None if args.no_gitignore or args.heavy else git_list_files(root)
    if git_files is not None:
        for rel in git_files:
            path = root / rel
            allowed(Path(rel).as_posix(), path)
    else:
        for folder, dirs, names in os.walk(root, followlinks=False):
            parent = Path(folder)
            rel_parent = parent.relative_to(root)
            kept_dirs = []
            for d in dirs:
                rel = (rel_parent / d).as_posix()
                if (not args.heavy and d == ".git") or (args.minimal and d in HEAVY_DIRS):
                    continue
                if args.no_hidden and d.startswith("."):
                    continue
                if any(path_matches(rel, pat) for pat in excludes):
                    continue
                if (parent / d).is_symlink():
                    continue
                kept_dirs.append(d)
            dirs[:] = kept_dirs
            for name in names:
                path = parent / name
                allowed(path.relative_to(root).as_posix(), path)
    # deduplica caminhos retornados por Git sem perder ordem estável
    return sorted({entry.rel: entry for entry in files}.values(), key=lambda e: e.rel)


def read_text(entry: Entry) -> str | None:
    try:
        with entry.path.open("rb") as f:
            head = f.read(8192)
            if b"\x00" in head:
                return None
            # Rejeita binários sem NUL (dados de controle fora de \n, \t, \r).
            odd = sum(b < 32 and b not in (9, 10, 13, 12) for b in head)
            if head and odd / len(head) > .01:
                return None
            raw = head + f.read()
        return raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def is_binary_stream(entry: Entry) -> bool | None:
    """Classifica sem carregar o arquivo inteiro. None = falha de leitura."""
    decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
    try:
        with entry.path.open("rb") as stream:
            head = stream.read(8192)
            if b"\x00" in head:
                return True
            odd = sum(byte < 32 and byte not in (9, 10, 13, 12) for byte in head)
            if head and odd / len(head) > 0.01:
                return True
            decoder.decode(head, final=False)
            while block := stream.read(65536):
                if b"\x00" in block:
                    return True
                decoder.decode(block, final=False)
            decoder.decode(b"", final=True)
        return False
    except UnicodeDecodeError:
        return True
    except OSError:
        return None


def iter_text_content(entry: Entry, compact: bool) -> Iterator[str]:
    """Leitura incremental, inclusive para arquivos grandes (memória limitada)."""
    with entry.path.open("r", encoding="utf-8-sig", newline="") as stream:
        if not compact:
            while block := stream.read(65536):
                yield block
            return
        pending: list[str] = []
        size = 0
        for line in stream:
            if not line.strip():
                continue
            normalized = line.rstrip(" \t\r\n") + "\n"
            pending.append(normalized)
            size += len(normalized)
            if size >= 65536:
                yield "".join(pending)
                pending.clear()
                size = 0
        if pending:
            yield "".join(pending)


def without_trailing_newlines(chunks: Iterator[str]) -> Iterator[str]:
    """Remove LF finais para evitar linhas extras no formato TXT."""
    waiting = 0
    for chunk in chunks:
        trimmed = chunk.rstrip("\n")
        if trimmed:
            while waiting:
                count = min(waiting, 65536)
                yield "\n" * count
                waiting -= count
            yield trimmed
        waiting += len(chunk) - len(trimmed)


def iter_base64_content(entry: Entry) -> Iterator[str]:
    """Buffer múltiplo de 3: cada bloco pode ser concatenado sem padding intermediário."""
    with entry.path.open("rb") as stream:
        while block := stream.read(3 * 16384):
            yield base64.b64encode(block).decode("ascii")


def iter_entry_segments(entry: Entry, args: argparse.Namespace, binary: bool,
                        first: bool) -> Iterator[tuple[str, str | None]]:
    """(texto de saída, conteúdo textual original para contagem de linhas)."""
    if args.format == "txt":
        header = f"@@ {entry.rel}" + (" [base64]" if binary else "") + "\n"
        yield header, None
    else:
        prefix = ("," if args.format == "json" and not first else "")
        prefix += '{"path":' + json.dumps(entry.rel, ensure_ascii=False) + ',"content":"'
        yield prefix, None

    if binary:
        for content in iter_base64_content(entry):
            yield content, None
    else:
        chunks = iter_text_content(entry, args.compact)
        if args.format == "txt":
            chunks = without_trailing_newlines(chunks)
        for content in chunks:
            if args.format in ("json", "ndjson"):
                yield json.dumps(content, ensure_ascii=False)[1:-1], content
            else:
                yield content, content

    if args.format == "txt":
        yield "\n", None
    else:
        end = ('","encoding":"base64"}' if binary else '"}')
        if args.format == "ndjson":
            end += "\n"
        yield end, None


def compact_text(text: str) -> str:
    # A opção explícita pode alterar conteúdo em literais multilinha: advertir no help.
    lines = [line.rstrip(" \t") for line in text.splitlines() if line.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


def preview_entry(entry: Entry, compact: bool) -> list[str]:
    """Prévia limitada: nunca lê arquivos gigantes integralmente na TUI."""
    try:
        with entry.path.open("rb") as stream:
            raw = stream.read(65537)
        truncated = len(raw) > 65536
        raw = raw[:65536]
        if b"\x00" in raw or (raw and sum(b < 32 and b not in (9, 10, 13, 12)
                                             for b in raw[:8192]) / min(len(raw), 8192) > .01):
            return ["(arquivo binário; exportação em base64 se --heavy estiver ativo)"]
        value = raw.decode("utf-8-sig", errors="replace")
        if compact:
            value = compact_text(value)
        lines = value.splitlines()[:400]
        if truncated:
            lines.append("… (prévia limitada a 64 KiB; exportação usa arquivo completo)")
        return lines
    except OSError as exc:
        return [f"(não foi possível ler a prévia: {exc})"]


def file_chunk(entry: Entry, text: str, fmt: str, first: bool) -> str:
    if fmt == "txt":
        return f"@@ {entry.rel}\n{text.rstrip(chr(10))}\n"
    row = json.dumps({"path": entry.rel, "content": text}, ensure_ascii=False,
                     separators=(",", ":"))
    if fmt == "ndjson":
        return row + "\n"
    return ("" if first else ",") + row


def tree_lines(entries: list[Entry], fmt: str) -> list[str]:
    if fmt == "tree-dirs":
        dirs = {"."}
        for e in entries:
            parts = e.rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        return sorted(dirs)
    if fmt == "tree-json":
        paths = {e.rel: "file" for e in entries}
        for e in entries:
            parts = e.rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                paths["/".join(parts[:i])] = "dir"
        return [json.dumps({"path": p, "type": paths[p]}, ensure_ascii=False,
                           separators=(",", ":")) for p in sorted(paths)]
    # Árvore textual indentada, sem 'tree' externo.
    folders: dict = {}
    for entry in entries:
        node = folders
        for part in entry.rel.split("/"):
            node = node.setdefault(part, {})
    lines = ["."]

    def walk(node: dict, prefix: str) -> None:
        items = sorted(node.items(), key=lambda item: (bool(item[1]) is False, item[0]))
        for i, (name, children) in enumerate(items):
            last = i == len(items) - 1
            lines.append(prefix + ("└── " if last else "├── ") + name + ("/" if children else ""))
            if children:
                walk(children, prefix + ("    " if last else "│   "))
    walk(folders, "")
    return lines


def output_path(args: argparse.Namespace) -> Path:
    name = args.output if args.output is not None else Path(OUTPUT_NAMES[args.format])
    return Path(name).expanduser().absolute()


@dataclass
class Result:
    included: int = 0
    binary_encoded: int = 0
    skipped_binary: int = 0
    skipped_budget: int = 0
    lines: int = 0
    tokens: int = 0
    bytes_written: int = 0
    path: Path | None = None


def render(entries: list[Entry], args: argparse.Namespace, counter: TokenCounter,
           *, quiet: bool = False) -> Result:
    result = Result()
    policy = binary_policy(args)
    streaming = args.heavy or policy == "base64"
    if args.max_tokens is not None:
        required_wrapper = ('{"files":[]}\n' if args.format in ("json", "tree-json") else "")
        if counter.count(required_wrapper) > args.max_tokens:
            raise ValueError("orçamento insuficiente até para o formato vazio")
    dest = output_path(args)
    zipped = args.compress
    if zipped and dest.suffix != ".xz":
        dest = Path(str(dest) + ".xz")
    result.path = dest
    if args.dry_run:
        out = None
        temp_path = None
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Grava em destino temporário no mesmo sistema de arquivos e faz replace atômico.
        fd, tmp = tempfile.mkstemp(prefix=".codepack-", dir=dest.parent)
        temp_path = Path(tmp)
        os.close(fd)
        out = lzma.open(temp_path, "wt", encoding="utf-8", newline="\n") if zipped \
              else temp_path.open("w", encoding="utf-8", newline="\n")

    def emit(s: str) -> None:
        result.tokens += counter.count(s)
        if out is not None:
            out.write(s)

    try:
        if args.format in ("tree", "tree-dirs", "tree-json"):
            lines = tree_lines(entries, args.format)
            if args.format == "tree-json":
                emit('{"files":[')  # compatível com a saída legada
            for line in lines:
                chunk = (("," if result.included else "") + line) if args.format == "tree-json" else line + "\n"
                close_cost = counter.count("]}\n") if args.format == "tree-json" else 0
                if args.max_tokens is not None and (result.tokens + counter.count(chunk) + close_cost) > args.max_tokens:
                    result.skipped_budget += 1
                    continue
                emit(chunk)
                result.included += 1
            if args.format == "tree-json":
                emit("]}\n")
        else:
            opener = '{"files":[' if args.format == "json" else ""
            closer = "]}\n" if args.format == "json" else ""
            if opener:
                emit(opener)
            for entry in entries:
                # Heavy precisa suportar tanto binários quanto texto grande sem
                # armazenar o arquivo inteiro em memória.
                if streaming:
                    is_binary = is_binary_stream(entry)
                    if is_binary is None or (is_binary and policy == "skip"):
                        result.skipped_binary += 1
                        continue
                    first = result.included == 0
                    if args.max_tokens is not None:
                        required = counter.count(closer)
                        for piece, _ in iter_entry_segments(entry, args, is_binary, first):
                            required += counter.count(piece)
                        if result.tokens + required > args.max_tokens:
                            result.skipped_budget += 1
                            if args.logs and not quiet:
                                print(f"PULADO (orçamento) {entry.rel}")
                            continue
                    line_breaks = 0
                    last_character = ""
                    for piece, source in iter_entry_segments(entry, args, is_binary, first):
                        emit(piece)
                        if source:
                            line_breaks += source.count("\n")
                            last_character = source[-1]
                    result.lines += line_breaks + int(bool(last_character) and last_character != "\n")
                    result.included += 1
                    result.binary_encoded += int(is_binary)
                else:
                    content = read_text(entry)
                    if content is None:
                        result.skipped_binary += 1
                        continue
                    if args.compact:
                        content = compact_text(content)
                    chunk = file_chunk(entry, content, args.format, result.included == 0)
                    # Reserva também o fechamento do JSON antes de admitir o arquivo.
                    required = counter.count(chunk) + counter.count(closer)
                    if args.max_tokens is not None and result.tokens + required > args.max_tokens:
                        result.skipped_budget += 1
                        if args.logs and not quiet:
                            print(f"PULADO (orçamento) {entry.rel}")
                        continue
                    emit(chunk)
                    result.included += 1
                    result.lines += len(content.splitlines())
                if args.logs and not quiet:
                    print(f"+ {entry.rel}" + (" [base64]" if streaming and is_binary else ""))
            if closer:
                emit(closer)
        if out is not None:
            out.close()
            os.replace(temp_path, dest)
            result.bytes_written = dest.stat().st_size
    except BaseException:
        if out is not None and not out.closed:
            out.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return result


def copy_clipboard(path: Path, compressed: bool) -> str:
    # Segurança: nunca executar shell; evita interpretar conteúdo ou argumentos.
    if shutil.which("wl-copy"):
        command = ["wl-copy"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        command = ["xsel", "--clipboard", "--input"]
    elif shutil.which("pbcopy"):
        command = ["pbcopy"]
    elif shutil.which("clip.exe"):
        command = ["clip.exe"]
    else:
        return "clipboard indisponível: instale wl-clipboard, xclip ou xsel"
    try:
        # Cópia em streaming também funciona com exports HEAVY de vários GiB.
        with (lzma.open(path, "rb") if compressed else path.open("rb")) as stream:
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                assert process.stdin is not None
                shutil.copyfileobj(stream, process.stdin, length=1024 * 1024)
                process.stdin.close()
                if process.wait() != 0:
                    return "falha ao copiar: utilitário de clipboard retornou erro"
            except BaseException:
                process.kill()
                process.wait()
                raise
        return "texto copiado para o clipboard"
    except (OSError, lzma.LZMAError) as exc:
        return f"falha ao copiar: {exc}"


def format_result(result: Result, counter: TokenCounter, *, dry_run: bool) -> str:
    target = str(result.path) if result.path else "(sem saída)"
    mode = "SIMULAÇÃO" if dry_run else "EXPORTADO"
    size = "" if dry_run else f" | {human_size(result.bytes_written)}"
    return (f"{mode}: {result.included} itens | {result.lines} linhas | "
            f"~{result.tokens:,} tokens ({counter.mode}){size}\n"
            f"Saída: {target}\n"
            f"Binários serializados (base64): {result.binary_encoded} | "
            f"ignorados: {result.skipped_binary} binários/ilegíveis, "
            f"{result.skipped_budget} por orçamento")


def tui(stdscr, root: Path, args: argparse.Namespace, counter: TokenCounter) -> None:
    import curses
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    if curses.has_colors():
        curses.start_color()
        bg = -1
        try:
            curses.use_default_colors()
        except curses.error:
            bg = curses.COLOR_BLACK
        curses.init_pair(1, curses.COLOR_CYAN, bg)
        curses.init_pair(2, curses.COLOR_GREEN, bg)
        curses.init_pair(3, curses.COLOR_YELLOW, bg)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(5, curses.COLOR_MAGENTA, bg)
    def style(i: int) -> int:
        return curses.color_pair(i) if curses.has_colors() else curses.A_BOLD

    entries = scan_files(root, args)
    selected = {e.rel for e in entries}
    search = ""
    cursor = 0
    scroll = 0
    preview_scroll = 0
    message = "Pronto. Pressione ? para ver os atalhos."
    help_open = False

    def put(y: int, x: int, s: str, width: int, attr: int = 0) -> None:
        h, w = stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w and width > 0:
            safe = s.replace("\t", "    ").replace("\r", "")
            # addnstr evita ultrapassar os limites do terminal.
            try:
                stdscr.addnstr(y, x, safe, min(width, w - x - 1), attr)
            except curses.error:
                pass

    def prompt(label: str) -> str | None:
        h, w = stdscr.getmaxyx()
        if h < 4:
            return None
        stdscr.move(h - 2, 0)
        stdscr.clrtoeol()
        put(h - 2, 1, label, w - 3, style(3))
        stdscr.refresh()
        try:
            curses.echo()
            curses.curs_set(1)
            stdscr.move(h - 2, min(w - 2, len(label) + 1))
            raw = stdscr.getstr(h - 2, min(w - 2, len(label) + 1), max(1, w - len(label) - 4))
            return raw.decode("utf-8", errors="replace")
        except (curses.error, KeyboardInterrupt):
            return None
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 15 or w < 68:
            put(1, 2, "Aumente o terminal para pelo menos 68x15. [q] sair", max(0, w - 4))
            stdscr.refresh()
            if stdscr.getch() in (ord('q'), 27):
                return
            continue
        visible = [e for e in entries if search.casefold() in e.rel.casefold()]
        cursor = min(max(cursor, 0), max(0, len(visible) - 1))
        left_width = max(25, int(w * .46))
        list_height = h - 8
        scroll = min(scroll, max(0, len(visible) - list_height))
        if cursor < scroll:
            scroll = cursor
        if cursor >= scroll + list_height:
            scroll = cursor - list_height + 1

        total_size = sum(e.size for e in entries if e.rel in selected)
        put(0, 1, "CODEPACK", 18, style(1) | curses.A_BOLD)
        mode = "HEAVY" if args.heavy else "MINIMAL" if args.minimal else "NORMAL"
        put(0, 12, f"{root}  |  {mode}  |  {args.format.upper()}  |  {len(selected)}/{len(entries)} arquivos", w - 15)
        put(1, 1, f"~{math.ceil(total_size/4):,} tokens (prévia por bytes, antes de compactar)", w - 3, style(3))
        stdscr.hline(2, 0, curses.ACS_HLINE, w - 1)
        put(3, 1, "1 FILES", left_width - 2, style(1) | curses.A_BOLD)
        put(3, left_width + 1, "2 PREVIEW", w - left_width - 3, style(1) | curses.A_BOLD)
        for y in range(3, h - 3):
            try:
                stdscr.addch(y, left_width - 1, curses.ACS_VLINE)
            except curses.error:
                pass
        for i, entry in enumerate(visible[scroll:scroll + list_height]):
            idx = i + scroll
            mark = "[x]" if entry.rel in selected else "[ ]"
            text = f"{mark} {entry.rel}"
            attr = style(4) | curses.A_BOLD if idx == cursor else (style(2) if entry.rel in selected else 0)
            put(4 + i, 1, text.ljust(left_width - 2), left_width - 2, attr)
        if not visible:
            put(5, 2, "Nenhum arquivo corresponde à busca", left_width - 4, style(3))
        if visible:
            entry = visible[cursor]
            put(4, left_width + 1, entry.rel, w - left_width - 3, style(2))
            put(5, left_width + 1, human_size(entry.size), w - left_width - 3, style(3))
            preview_lines = preview_entry(entry, args.compact)
            preview_height = max(1, h - 11)
            for i, line in enumerate(preview_lines[preview_scroll:preview_scroll + preview_height]):
                # Recuo + numeração, sem duplicar cabeçalhos no arquivo exportado.
                put(7 + i, left_width + 1, f"{i + preview_scroll + 1:>4} │ {line}", w - left_width - 3)
            put(h - 4, left_width + 1, f"{len(preview_lines)} linhas | scroll: J/K", w - left_width - 3)
        stdscr.hline(h - 3, 0, curses.ACS_HLINE, w - 1)
        put(h - 2, 1, f"/ buscar  espaço selecionar  a todos  x nenhum  f formato  m minimal  H heavy  b orçamento", w - 3, style(1))
        put(h - 1, 1, f"g gerar  c copy:{'on' if args.copy else 'off'}  r reler  J/K prévia  ? ajuda  q sair  |  {message}", w - 3, style(3))
        if help_open:
            overlay = [
                "ATALHOS", "↑/↓, j/k  : navegar arquivos", "Espaço     : marcar/desmarcar",
                "a / x      : marcar todos / nenhum (visíveis)", "/          : buscar por caminho",
                "J / K      : rolar a prévia", "f          : alternar formato",
                "m          : ligar/desligar filtro minimal", "H          : ligar/desligar modo heavy",
                "o          : ligar/desligar compactação",
                "b          : definir orçamento de tokens (0 = sem limite)",
                "c          : copiar após exportar", "r          : reler lista de arquivos",
                "g          : gerar saída", "? / q      : fechar ajuda / sair",
            ]
            start_x = max(2, (w - 52) // 2)
            start_y = max(3, (h - len(overlay) - 2) // 2)
            for index, line in enumerate(overlay):
                put(start_y + index, start_x, (" " + line).ljust(50), 50,
                    style(4) if index == 0 else curses.A_REVERSE)
        stdscr.refresh()
        key = stdscr.getch()
        if help_open:
            help_open = False
            continue
        if key in (ord('q'), 27):
            break
        elif key in (curses.KEY_DOWN, ord('j')):
            cursor = min(cursor + 1, len(visible) - 1) if visible else 0
            preview_scroll = 0
        elif key in (curses.KEY_UP, ord('k')):
            cursor = max(0, cursor - 1)
            preview_scroll = 0
        elif key == ord('J'):
            preview_scroll += 3
        elif key == ord('K'):
            preview_scroll = max(0, preview_scroll - 3)
        elif key == ord(' ') and visible:
            name = visible[cursor].rel
            if name in selected:
                selected.remove(name)
            else:
                selected.add(name)
        elif key == ord('a'):
            selected.update(e.rel for e in visible)
        elif key == ord('x'):
            selected.difference_update(e.rel for e in visible)
        elif key == ord('/'):
            value = prompt("Buscar (vazio = todos): ")
            if value is not None:
                search, cursor, scroll, preview_scroll = value, 0, 0, 0
        elif key == ord('f'):
            args.format = FORMATS[(FORMATS.index(args.format) + 1) % len(FORMATS)]
            message = f"Formato: {args.format}"
        elif key == ord('o'):
            args.compact = not args.compact
            message = "Compactação textual LIGADA (altera whitespace)" if args.compact else "Compactação desligada"
        elif key == ord('m'):
            all_previous_selected = len(selected) == len(entries)
            args.minimal = not args.minimal
            if args.minimal:
                args.heavy = False
            new_entries = scan_files(root, args)
            new_names = {e.rel for e in new_entries}
            # Mantém seleções manuais; se tudo estava marcado, marca novos itens.
            if all_previous_selected:
                selected = new_names
            else:
                selected.intersection_update(new_names)
            entries = new_entries
            cursor, scroll, preview_scroll = 0, 0, 0
            message = f"Modo minimal: {'on' if args.minimal else 'off'}"
        elif key == ord('H'):
            all_previous_selected = len(selected) == len(entries)
            args.heavy = not args.heavy
            if args.heavy:
                args.minimal = False
            new_entries = scan_files(root, args)
            new_names = {e.rel for e in new_entries}
            selected = new_names if all_previous_selected else selected.intersection(new_names)
            entries = new_entries
            cursor, scroll, preview_scroll = 0, 0, 0
            message = ("HEAVY ligado: .git, ignored, binários e arquivos grandes"
                       if args.heavy else "HEAVY desligado")
        elif key == ord('b'):
            value = prompt("Orçamento estimado (0 = sem limite): ")
            if value is not None:
                try:
                    budget = int(value)
                    if budget < 0:
                        raise ValueError
                    args.max_tokens = budget or None
                    message = f"Orçamento: {args.max_tokens or 'sem limite'}"
                except ValueError:
                    message = "Use um número inteiro não negativo"
        elif key == ord('c'):
            args.copy = not args.copy
            message = f"Clipboard: {'on' if args.copy else 'off'}"
        elif key == ord('r'):
            entries = scan_files(root, args)
            selected.intersection_update(e.rel for e in entries)
            cursor, scroll, preview_scroll = 0, 0, 0
            message = "Lista atualizada"
        elif key == ord('?'):
            help_open = True
        elif key == ord('g'):
            try:
                selected_entries = [e for e in entries if e.rel in selected]
                result = render(selected_entries, args, counter, quiet=True)
                message = ("Simulado" if args.dry_run else "Gerado") + f": {result.included} itens, ~{result.tokens} tokens"
                if args.copy and not args.dry_run:
                    message += " | " + copy_clipboard(result.path, args.compress)
            except (OSError, ValueError, lzma.LZMAError) as exc:
                message = f"Erro: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"não é um diretório: {root}")
    if args.lang and args.lang.lower() not in LANGUAGES:
        parser.error(f"linguagem desconhecida: {args.lang} (opções: {', '.join(sorted(LANGUAGES))})")
    if args.output is not None and args.output.expanduser().is_dir():
        parser.error("--output deve indicar arquivo, não diretório")
    if args.copy and args.dry_run:
        parser.error("--copy não pode ser usado com --dry-run")
    try:
        counter = TokenCounter(args.tokenizer, args.encoding)
    except ValueError as exc:
        parser.error(str(exc))
    if args.tui:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("--tui exige terminal interativo (TTY)")
        try:
            import curses
            curses.wrapper(tui, root, args, counter)
            return 0
        except ImportError:
            parser.error("--tui requer curses (padrão em Linux/macOS)")
    entries = scan_files(root, args)
    try:
        result = render(entries, args, counter)
        print(format_result(result, counter, dry_run=args.dry_run))
        if args.copy and not args.dry_run:
            print(copy_clipboard(result.path, args.compress))
    except (OSError, ValueError, lzma.LZMAError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
