"""Gancho pre-commit do gitleaks (acha senha/chave antes do commit), só por clique do dono e só no checkout principal.

Nunca sobrescreve um gancho que já existe:
  * sem gancho: cria .git/hooks/pre-commit (marcado como do Cérebro);
  * com gancho do projeto: ENCADEIA. O antigo é guardado ao lado como pre-commit.cerebro-anterior (e copiado para
    ~/.cerebro/copias antes) e o gancho do Cérebro chama ele primeiro: se o antigo falhar, o commit para como antes;
  * projeto que usa o framework pre-commit (.pre-commit-config.yaml): acrescenta um bloco marcado na lista "repos" do arquivo,
    sem mexer no resto.
Tirar = só o que é do Cérebro (pelo marcador): volta o gancho antigo, ou tira o bloco do .pre-commit-config.yaml.
O .pre-commit-config.yaml só é regravado se for lido INTEIRO e exato: arquivo maior que LIMITE_YAML ou que não seja UTF-8 é
recusado (nunca grava uma versão cortada ou com caracteres trocados).
Este módulo só PLANEJA (lista de mudanças); quem grava é o encaixe, pela escrita_projeto (trava, cópia e desfazer).
"""
import re
from pathlib import Path

from . import projetos

MARCA = "cerebro:gancho-gitleaks"
REL_GANCHO = ".git/hooks/pre-commit"
REL_ANTERIOR = ".git/hooks/pre-commit.cerebro-anterior"
REL_CONFIG = ".pre-commit-config.yaml"
INICIO_YAML, FIM_YAML = "# cerebro:inicio gitleaks", "# cerebro:fim gitleaks"
LIMITE_YAML = 1_000_000

TEXTO_GANCHO = f"""#!/bin/sh
# {MARCA}
# Gancho instalado pelo Cérebro do Projeto: procura senhas e chaves nos arquivos do commit com o gitleaks.
# Para tirar, use o Cérebro (aba Inventário) ou: python cerebro_cli.py encaixe <projeto> --aplicar segredos-tirar --confirmar
ANTERIOR="$(dirname "$0")/pre-commit.cerebro-anterior"
if [ -f "$ANTERIOR" ]; then
  "$ANTERIOR" "$@" || exit $?
fi
if command -v gitleaks >/dev/null 2>&1; then
  if gitleaks git --help >/dev/null 2>&1; then
    gitleaks git --pre-commit --staged --redact --no-banner || {{ echo "gitleaks: possível segredo no commit (veja acima). Commit cancelado." >&2; exit 1; }}
  else
    gitleaks protect --staged --redact --no-banner || {{ echo "gitleaks: possível segredo no commit (veja acima). Commit cancelado." >&2; exit 1; }}
  fi
else
  echo "Cérebro: gitleaks não encontrado neste PC; o commit segue sem a verificação de segredos." >&2
fi
exit 0
"""


def _ler(p, limite=LIMITE_YAML):
    """Só para OLHAR (procurar o marcador). Nunca use o resultado para regravar o arquivo: veja _ler_para_regravar."""
    try:
        return Path(p).read_bytes()[:limite].decode("utf-8", "replace")
    except OSError:
        return ""


def _ler_para_regravar(p, limite=LIMITE_YAML):
    """O texto INTEIRO e exato do arquivo, ou ValueError: grande demais ou fora do UTF-8 = recusa (nada é regravado)."""
    dados = Path(p).read_bytes()
    if len(dados) > limite:
        raise ValueError(f"o {Path(p).name} é grande demais para eu mexer com segurança ({len(dados) // 1024} KB; limite "
                         f"{limite // 1024} KB): acrescente à mão o bloco mostrado na prévia")
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"o {Path(p).name} não está em UTF-8: não mexo para não trocar caracteres; acrescente à mão") from None


def _bloco_yaml(recuo, fim_de_linha):
    linhas = [INICIO_YAML, "- repo: local", "  hooks:", "  - id: gitleaks-cerebro", "    name: gitleaks (segredos, ligado pelo Cérebro)",
              "    entry: gitleaks protect --staged --redact --no-banner", "    language: system", "    pass_filenames: false", FIM_YAML]
    return fim_de_linha.join(recuo + x for x in linhas) + fim_de_linha


def _yaml_com_bloco(texto):
    """Acrescenta o bloco no fim da lista 'repos:' (só se 'repos:' for a última chave do arquivo). None se não for seguro."""
    linhas = texto.splitlines()
    pos_repos = next((i for i, l in enumerate(linhas) if re.match(r"^repos:\s*(#.*)?$", l)), None)
    if pos_repos is None:
        return None
    if any(re.match(r"^[A-Za-z_\"']", l) for l in linhas[pos_repos + 1:]):
        return None                                           # há outra chave depois de repos: não arrisco mexer
    recuo = None
    for l in linhas[pos_repos + 1:]:
        m = re.match(r"^(\s*)-\s+repo:", l)
        if m:
            recuo = m.group(1)
            break
    if recuo is None:
        return None
    fim = "\r\n" if "\r\n" in texto else "\n"
    base = texto if texto.endswith(("\n", "\r")) else texto + fim
    return base + _bloco_yaml(recuo, fim)


def _yaml_sem_bloco(texto):
    """Tira só as linhas entre os marcadores do Cérebro (inclusive). None se não houver bloco."""
    linhas = texto.splitlines(keepends=True)
    ini = next((i for i, l in enumerate(linhas) if l.strip() == INICIO_YAML), None)
    fim = next((i for i, l in enumerate(linhas) if l.strip() == FIM_YAML and ini is not None and i > ini), None)
    if ini is None or fim is None:
        return None
    return "".join(linhas[:ini] + linhas[fim + 1:])


def situacao(raiz):
    """Como está o pre-commit do projeto e o que dá para fazer. Só leitura."""
    raiz = Path(raiz)
    git = raiz / ".git"
    d = {"repositorio": git.is_dir(), "worktree": git.is_file(), "hooks_path": "", "gancho": "", "do_cerebro": False, "anterior": False,
         "framework": (raiz / REL_CONFIG).is_file(), "no_config": False, "modos": [], "motivo": ""}
    if d["worktree"]:
        d["motivo"] = "esta pasta é uma worktree: o gancho vai só no checkout principal"
        return d
    if not d["repositorio"]:
        d["motivo"] = "a pasta não é um repositório git (não há .git)"
        return d
    d["hooks_path"] = projetos._git(raiz, "config", "--get", "core.hooksPath")
    if d["hooks_path"]:
        d["motivo"] = f"o projeto usa core.hooksPath ({d['hooks_path']}): os ganchos ficam em outra pasta; ligue o gitleaks lá à mão"
        return d
    gancho = raiz / REL_GANCHO
    if gancho.is_file():
        txt = _ler(gancho)
        d["do_cerebro"] = MARCA in txt
        d["gancho"] = "do Cérebro" if d["do_cerebro"] else ("do framework pre-commit" if "pre-commit" in txt and "INSTALL_PYTHON" in txt else "do projeto")
    d["anterior"] = (raiz / REL_ANTERIOR).is_file()
    if d["framework"]:
        d["no_config"] = INICIO_YAML in _ler(raiz / REL_CONFIG)
    if d["do_cerebro"] or d["no_config"]:
        d["modos"] = ["tirar"]
        return d
    if d["framework"]:
        d["modos"].append("config")
    d["modos"].append("encadear" if d["gancho"] else "novo")
    return d


def planejar_ligar(raiz, modo=None):
    """Lista de mudanças para ligar o gitleaks. modo: None (o recomendado), 'config', 'encadear' ou 'novo'."""
    s = situacao(raiz)
    if s["motivo"]:
        raise ValueError(s["motivo"])
    if "tirar" in s["modos"]:
        raise ValueError("o gitleaks já está ligado pelo Cérebro neste projeto")
    modo = modo or s["modos"][0]
    if modo not in s["modos"]:
        raise ValueError(f"modo indisponível aqui: {modo} (possíveis: {', '.join(s['modos'])})")
    raiz = Path(raiz)
    if modo == "config":
        atual = _ler_para_regravar(raiz / REL_CONFIG)
        novo = _yaml_com_bloco(atual)
        if novo is None:
            raise ValueError("não achei um jeito seguro de acrescentar ao .pre-commit-config.yaml (a lista 'repos:' precisa ser a última chave); "
                             "acrescente à mão o bloco mostrado na prévia")
        return modo, [{"rel": REL_CONFIG, "tipo": "alterar", "dados": novo.encode("utf-8"),
                       "nota": "acrescenta um gancho local do gitleaks no fim da lista repos (rode 'pre-commit install' se ainda não rodou)"}]
    gancho = TEXTO_GANCHO.encode("utf-8")
    if modo == "novo":
        return modo, [{"rel": REL_GANCHO, "tipo": "criar", "dados": gancho, "executavel": True, "nota": "gancho novo"}]
    if s["anterior"]:
        raise ValueError("já existe um pre-commit.cerebro-anterior nesta pasta; confira os ganchos à mão antes")
    antigo = (raiz / REL_GANCHO).read_bytes()
    return modo, [{"rel": REL_ANTERIOR, "tipo": "criar", "dados": antigo, "executavel": True, "copiar_modo_de": REL_GANCHO,
                   "nota": "o gancho que já existia, guardado ao lado (o do Cérebro chama ele primeiro)"},
                  {"rel": REL_GANCHO, "tipo": "alterar", "dados": gancho, "nota": "passa a ser o gancho do Cérebro, que chama o antigo e depois o gitleaks"}]


def planejar_tirar(raiz):
    """Lista de mudanças para tirar SÓ o que é do Cérebro."""
    s = situacao(raiz)
    raiz = Path(raiz)
    ops = []
    if s["no_config"]:
        novo = _yaml_sem_bloco(_ler_para_regravar(raiz / REL_CONFIG))
        if novo is not None:
            ops.append({"rel": REL_CONFIG, "tipo": "alterar", "dados": novo.encode("utf-8"), "nota": "tira só o bloco marcado do Cérebro"})
    if s["do_cerebro"]:
        if s["anterior"]:
            ops.append({"rel": REL_GANCHO, "tipo": "alterar", "dados": (raiz / REL_ANTERIOR).read_bytes(), "nota": "volta o gancho que existia antes"})
            ops.append({"rel": REL_ANTERIOR, "tipo": "retirar", "nota": "a cópia ao lado deixa de ser usada (vai para a pasta de cópias do Cérebro)"})
        else:
            ops.append({"rel": REL_GANCHO, "tipo": "retirar", "nota": "o gancho era só do Cérebro (vai para a pasta de cópias do Cérebro)"})
    if not ops:
        raise ValueError("não há gancho do Cérebro neste projeto")
    return ops
