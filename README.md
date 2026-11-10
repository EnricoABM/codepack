# Codepack

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Bash](https://img.shields.io/badge/Bash-CLI-4EAA25?logo=gnubash&logoColor=white)
![TUI](https://img.shields.io/badge/Interface-TUI-30363D?logo=gnometerminal&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-suportado-FCC624?logo=linux&logoColor=black)
![macOS](https://img.shields.io/badge/macOS-suportado-000000?logo=apple&logoColor=white)

**Codepack** é uma ferramenta de terminal que reúne arquivos de um projeto em uma única saída, facilitando o compartilhamento de código e a criação de contexto para IAs. Oferece uma **CLI** e uma interface interativa (**TUI**) inspirada no LazyGit, com filtros, múltiplos formatos de exportação e opções para reduzir o consumo de tokens.

## Requisitos e dependências

- **Python 3.10+** e **Bash**, em Linux ou macOS.
- **Sem pacotes Python obrigatórios:** a TUI utiliza `curses`, da biblioteca padrão no Linux/macOS.
- **Opcionais:** Git (leitura das regras do `.gitignore`), `tiktoken` (contagem mais precisa de tokens) e `wl-copy`, `xclip`, `xsel` ou `pbcopy` (área de transferência, conforme o sistema).

Para habilitar a contagem com `tiktoken`:

```bash
python3 -m pip install tiktoken
```

## Instalação

Clone ou baixe o repositório e, **dentro da pasta do projeto**, execute:

```bash
chmod +x install.sh
./install.sh
```

O instalador disponibiliza o comando `codepack` em `~/.local/bin`, sem `sudo`. Se o terminal não reconhecer o comando, adicione o diretório ao seu `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Para persistir essa configuração, acrescente a linha ao `~/.bashrc` ou `~/.zshrc`.

## Uso rápido

Execute o Codepack **a partir da pasta que deseja processar**. Por padrão, `combinado.txt` será criado nessa mesma pasta.

```bash
codepack                                # Concatenar arquivos do diretório atual
codepack --tui                          # Abrir a interface interativa
codepack -m --compact --max-tokens 12000 # Contexto otimizado para IA
codepack --heavy                        # Incluir dependências, builds e binários
codepack --heavy --binary skip          # Modo heavy sem conteúdo binário
codepack --lang typescript              # Filtrar por linguagem
codepack -j -o contexto.json            # Exportar em JSON
codepack -T                              # Exportar estrutura em árvore
codepack --dry-run                      # Simular sem criar arquivos
codepack --help                         # Ver todas as opções
```

Para processar outra pasta, informe seu caminho: `codepack /caminho/do/projeto`. A saída continua sendo salva no diretório em que o comando foi executado, salvo quando `-o` especificar outro destino.

### Modos de operação

| Modo    | Comando       | Descrição                                                                             |
| ------- | ------------- | ------------------------------------------------------------------------------------- |
| Padrão  | `codepack`    | Seleção normal, respeitando `.gitignore` quando possível.                             |
| Minimal | `codepack -m` | Exclui dependências, builds, caches e lockfiles.                                      |
| Heavy   | `codepack -H` | Inclui diretórios ignorados e arquivos grandes; binários são convertidos para Base64. |

> **Atenção:** o modo Heavy pode gerar saídas muito grandes. Arquivos com nomes sensíveis conhecidos permanecem excluídos por padrão; ainda assim, revise qualquer conteúdo antes de compartilhá-lo. `--compact` altera espaços em branco e a estimativa padrão de tokens é aproximada.

Para mais opções, consulte `codepack --help`.
