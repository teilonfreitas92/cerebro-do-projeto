"""Instalação adaptativa, etapa 2: APLICAR o plano de encaixe do inventário, item por item, com prévia e "Desfazer".

Cada item do plano vira uma ação concreta que só:
  * CRIA arquivo novo (ex.: CLAUDE.md quando não existe, .claude/agents/cerebro-*.md, ruff.toml, .github/dependabot.yml), ou
  * ACRESCENTA um bloco marcado (<!-- cerebro:inicio --> ... <!-- cerebro:fim -->) no fim do CLAUDE.md/AGENTS.md, ou
  * liga o gancho pre-commit do gitleaks (ver gancho.py: encadeia o gancho que já existir, nunca sobrescreve).
Nunca reescreve o que existe e nunca apaga. Toda escrita passa por escrita_projeto (trava de caminho, cópia de segurança em
~/.cerebro/copias/projetos/<slug>/<data-hora>/, escrita atômica, "Desfazer").

A prévia mostra os arquivos e a diferença. Aplicar REFAZ o plano no servidor (a página manda só o id da ação) e confere a
"assinatura" da prévia que o dono viu: se o projeto mudou nesse meio-tempo, recusa e pede para ver a prévia de novo.
"""
import difflib
import hashlib
import json
import os
import re
from pathlib import Path

from . import config, escrita_projeto, ferramentas, gancho, inventario, regras_agentes
from .escrita_projeto import EscritaRecusada
from .segredos import mascarar

INICIO, FIM = "<!-- cerebro:inicio -->", "<!-- cerebro:fim -->"
LIMITE_DIFF = 400                     # linhas de diferença mostradas por arquivo
ACOES = {
    "instrucoes": "Bloco do Cérebro nas instruções (CLAUDE.md / AGENTS.md)",
    "agentes": "Copiar os agentes por tipo para .claude/agents",
    "segredos": "Ligar o gitleaks no pre-commit",
    "segredos-tirar": "Tirar o gancho do gitleaks (só o que é do Cérebro)",
    "qualidade": "Configuração mínima do ruff (ruff.toml)",
    "dependencias": "Dependabot (.github/dependabot.yml)",
}
RUFF_MINIMO = """# Criado pelo Cérebro do Projeto: configuração mínima do ruff (só erros de verdade). Ajuste à vontade.
line-length = 120

[lint]
select = ["E9", "F"]
"""


# ---------------------------------------------------------------------------------------------------------------
# Planos de cada ação: lista de mudanças {rel, tipo: criar|alterar|retirar|pular, dados, nota}
# ---------------------------------------------------------------------------------------------------------------
def _texto(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        raise EscritaRecusada("o arquivo não está em UTF-8: o Cérebro não mexe nele") from None


def _bloco_instrucoes(fim="\n"):
    corpo = inventario.SNIPPET_CLAUDE_MD.strip("\n").split("\n")
    return fim.join([INICIO, *corpo, FIM]) + fim


def _plano_instrucoes(raiz, p, opcoes):
    for nome in ("CLAUDE.md", "AGENTS.md"):
        alvo = escrita_projeto.alvo_seguro(raiz, nome)
        antes = escrita_projeto.ler_existente(alvo)
        if antes is None:
            continue
        txt = _texto(antes)
        if INICIO in txt:
            return [{"rel": nome, "tipo": "pular", "nota": "o bloco do Cérebro já está neste arquivo (nada a fazer; para mudar, edite à mão)"}]
        fim = "\r\n" if "\r\n" in txt else "\n"
        base = txt if not txt or txt.endswith(("\n", "\r")) else txt + fim
        novo = base + fim + _bloco_instrucoes(fim)
        return [{"rel": nome, "tipo": "alterar", "dados": novo.encode("utf-8"), "nota": "acrescenta o bloco marcado no FIM; o resto fica como está"}]
    novo = f"# {p.get('nome') or 'Projeto'}\n\nInstruções do projeto para o Claude Code. Escreva aqui as regras do projeto.\n\n" + _bloco_instrucoes()
    return [{"rel": "CLAUDE.md", "tipo": "criar", "dados": novo.encode("utf-8"), "nota": "o projeto não tinha CLAUDE.md nem AGENTS.md"}]


def textos_dos_agentes(p, cfg):
    """{arquivo: texto} da prévia dos agentes por tipo (a que está em ~/.cerebro; se não houver, gera agora, lá)."""
    previa = regras_agentes.previa_existente(p["slug"]) or regras_agentes.gerar_previa(p["slug"], p["nome"], cfg["agentes_regras"])
    saida = {}
    for a in previa["arquivos"]:
        if re.fullmatch(r"cerebro-[a-z0-9][a-z0-9\-]{0,40}\.md", a["arquivo"]):
            saida[a["arquivo"]] = a["texto"]
    if not saida:
        raise EscritaRecusada("a prévia dos agentes está vazia: gere de novo em Configurações")
    return saida


def _plano_agentes(raiz, p, opcoes, cfg):
    conflito = (opcoes or {}).get("conflito", "pular")
    if conflito not in ("pular", "cerebro_md"):
        raise EscritaRecusada("opção de conflito inválida (pular ou cerebro_md)")
    ops = []
    for arquivo, texto in sorted(textos_dos_agentes(p, cfg).items()):
        rel = ".claude/agents/" + arquivo
        dados = texto.encode("utf-8")
        antes = escrita_projeto.ler_existente(escrita_projeto.alvo_seguro(raiz, rel))
        if antes is None:
            ops.append({"rel": rel, "tipo": "criar", "dados": dados, "nota": "agente novo"})
        elif antes.replace(b"\r\n", b"\n") == dados:
            ops.append({"rel": rel, "tipo": "pular", "nota": "já existe igual"})
        else:
            alt = rel[:-3] + ".cerebro.md"
            antes_alt = escrita_projeto.ler_existente(escrita_projeto.alvo_seguro(raiz, alt))
            diff = _diff(antes, dados, rel)
            if conflito == "cerebro_md" and antes_alt is None:
                ops.append({"rel": alt, "tipo": "criar", "dados": dados, "diff_extra": diff,
                            "nota": f"já existe {arquivo} DIFERENTE: o seu fica intacto e a versão do Cérebro vai ao lado (o Claude Code também lê este arquivo; junte à mão e apague um dos dois)"})
            else:
                ops.append({"rel": rel, "tipo": "pular", "diff_extra": diff,
                            "nota": "já existe com conteúdo DIFERENTE: não sobrescrevo (veja a diferença; escolha 'gravar ao lado' para ter a versão do Cérebro como .cerebro.md)"})
    return ops


def _plano_qualidade(raiz, p, opcoes):
    if inventario._config_lint(raiz):
        return [{"rel": "ruff.toml", "tipo": "pular", "nota": "o projeto já tem configuração de lint: respeitada"}]
    if "py" not in ferramentas.tipo_do_projeto(raiz):
        raise EscritaRecusada("nada a criar: a configuração mínima automática é só para projetos Python (ruff)")
    return [{"rel": "ruff.toml", "tipo": "criar", "dados": RUFF_MINIMO.encode("utf-8"), "nota": "configuração mínima: só erros de verdade (E9 e F)"}]


def _plano_dependencias(raiz, p, opcoes):
    for nome in (".github/dependabot.yml", ".github/dependabot.yaml"):
        if (raiz / nome).is_file():
            return [{"rel": nome, "tipo": "pular", "nota": "Dependabot já configurado: respeitado"}]
    ecos = []
    if (raiz / "requirements.txt").is_file() or (raiz / "pyproject.toml").is_file():
        ecos.append("pip")
    if (raiz / "package.json").is_file():
        ecos.append("npm")
    if (raiz / "Cargo.toml").is_file():
        ecos.append("cargo")
    if (raiz / ".github" / "workflows").is_dir():
        ecos.append("github-actions")
    if not ecos:
        raise EscritaRecusada("nada a criar: não achei requirements.txt, pyproject.toml, package.json nem Cargo.toml na raiz")
    linhas = ["# Criado pelo Cérebro do Projeto: o GitHub avisa (e propõe a correção) quando um pacote tem falha conhecida.", "version: 2", "updates:"]
    for e in ecos:
        linhas += [f"  - package-ecosystem: \"{e}\"", "    directory: \"/\"", "    schedule:", "      interval: \"weekly\""]
    return [{"rel": ".github/dependabot.yml", "tipo": "criar", "dados": ("\n".join(linhas) + "\n").encode("utf-8"),
             "nota": "só tem efeito se o projeto estiver no GitHub: " + ", ".join(ecos)}]


def _plano_segredos(raiz, p, opcoes):
    modo, ops = gancho.planejar_ligar(raiz, (opcoes or {}).get("modo"))
    return ops


def _plano_segredos_tirar(raiz, p, opcoes):
    return gancho.planejar_tirar(raiz)


def _plano(acao, raiz, p, opcoes, cfg):
    if acao == "instrucoes":
        return _plano_instrucoes(raiz, p, opcoes)
    if acao == "agentes":
        return _plano_agentes(raiz, p, opcoes, cfg)
    if acao == "qualidade":
        return _plano_qualidade(raiz, p, opcoes)
    if acao == "dependencias":
        return _plano_dependencias(raiz, p, opcoes)
    if acao == "segredos":
        return _plano_segredos(raiz, p, opcoes)
    if acao == "segredos-tirar":
        return _plano_segredos_tirar(raiz, p, opcoes)
    raise EscritaRecusada(f"ação desconhecida: {acao!r}")


# ---------------------------------------------------------------------------------------------------------------
# Prévia
# ---------------------------------------------------------------------------------------------------------------
def _diff(antes, depois, rel):
    a = (antes or b"").decode("utf-8", "replace").splitlines()
    d = (depois or b"").decode("utf-8", "replace").splitlines()
    linhas = list(difflib.unified_diff(a, d, "antes/" + rel, "depois/" + rel, n=2, lineterm=""))
    if len(linhas) > LIMITE_DIFF:
        linhas = linhas[:LIMITE_DIFF] + [f"... (+{len(linhas) - LIMITE_DIFF} linhas)"]
    return mascarar("\n".join(linhas))


def _assinatura(acao, ops, raiz):
    h = hashlib.sha256(acao.encode("utf-8"))
    for op in ops:
        alvo = Path(raiz) / op["rel"]
        try:
            antes = alvo.read_bytes() if alvo.is_file() else b""
        except OSError:
            antes = b""
        h.update(json.dumps([op["rel"], op["tipo"]]).encode("utf-8"))
        h.update(hashlib.sha256(antes).digest())
        h.update(hashlib.sha256(op.get("dados") or b"").digest())
    return h.hexdigest()[:24]


def previa(p, acao, opcoes=None, cfg=None):
    """O que a ação faria: arquivos, tipo de mudança e diferença. Não escreve nada no projeto."""
    cfg = cfg if cfg is not None else config.ler_config()
    raiz = escrita_projeto.conferir_projeto(p, cfg)
    ops = _plano(acao, raiz, p, opcoes, cfg)
    arquivos = []
    for op in ops:
        alvo = escrita_projeto.alvo_seguro(raiz, op["rel"])
        antes = escrita_projeto.ler_existente(alvo)
        if op["tipo"] in ("criar", "alterar"):
            diff = _diff(antes, op["dados"], op["rel"])
        elif op["tipo"] == "retirar":
            diff = _diff(antes, b"", op["rel"])
        else:
            diff = op.get("diff_extra", "")
        arquivos.append({"rel": op["rel"], "caminho": str(alvo), "tipo": op["tipo"], "nota": op.get("nota", ""), "diff": diff,
                         "existe": antes is not None})
    efetivas = [a for a in arquivos if a["tipo"] != "pular"]
    extra = {"modos": gancho.situacao(raiz)["modos"]} if acao == "segredos" else {}
    return {**extra, "acao": acao, "titulo": ACOES.get(acao, acao), "arquivos": arquivos, "aplicavel": bool(efetivas),
            "assinatura": _assinatura(acao, ops, raiz), "copias": str(escrita_projeto.pasta_copias(p["slug"])),
            "resumo": (f"{sum(a['tipo'] == 'criar' for a in arquivos)} arquivo(s) novo(s), {sum(a['tipo'] == 'alterar' for a in arquivos)} acrescentado(s), "
                       f"{sum(a['tipo'] == 'retirar' for a in arquivos)} retirado(s) para a pasta de cópias, {sum(a['tipo'] == 'pular' for a in arquivos)} pulado(s)")}


def previa_tudo(p, cfg=None):
    """Prévia de cada ação do plano (as que não se aplicam vêm com o motivo). Para a aba Inventário."""
    cfg = cfg if cfg is not None else config.ler_config()
    saida = {}
    try:
        raiz = escrita_projeto.conferir_projeto(p, cfg)
    except EscritaRecusada as e:
        return {"bloqueado": str(e), "acoes": {}, "historico": escrita_projeto.historico(p["slug"])[:10]}
    s = gancho.situacao(raiz)
    for acao in ACOES:
        if acao == "segredos-tirar" and "tirar" not in s["modos"]:
            continue
        if acao == "segredos" and "tirar" in s["modos"]:
            continue
        try:
            saida[acao] = previa(p, acao, None, cfg)
        except (EscritaRecusada, ValueError, OSError) as e:
            saida[acao] = {"acao": acao, "titulo": ACOES[acao], "aplicavel": False, "motivo": str(e), "arquivos": []}
    return {"bloqueado": "", "acoes": saida, "historico": escrita_projeto.historico(p["slug"])[:10], "gancho": s,
            "pode_desfazer": escrita_projeto.ultima_desfazivel(p["slug"]) is not None}


# ---------------------------------------------------------------------------------------------------------------
# Aplicar e desfazer
# ---------------------------------------------------------------------------------------------------------------
def aplicar(p, acao, confirmar=False, opcoes=None, assinatura=None, cfg=None):
    """Aplica uma ação. Exige confirmar=True (o clique na tela de confirmação ou --confirmar na CLI)."""
    if confirmar is not True:
        raise EscritaRecusada("aplicar precisa da confirmação do dono")
    cfg = cfg if cfg is not None else config.ler_config()
    if acao not in ACOES:
        raise EscritaRecusada(f"ação desconhecida: {acao!r}")
    with escrita_projeto.Aplicacao(p, acao, ACOES[acao], cfg) as ap:
        ops = _plano(acao, ap.raiz, p, opcoes, cfg)
        if assinatura is not None and assinatura != _assinatura(acao, ops, ap.raiz):
            raise EscritaRecusada("o projeto mudou desde a prévia: veja a prévia de novo antes de aplicar")
        feito = []
        for op in ops:
            if op["tipo"] == "criar":
                modo = None
                if op.get("copiar_modo_de"):
                    try:
                        modo = os.stat(ap.raiz / op["copiar_modo_de"]).st_mode & 0o777
                    except OSError:
                        modo = None
                elif op.get("executavel"):
                    modo = 0o755
                ap.criar(op["rel"], op["dados"], modo=modo)
            elif op["tipo"] == "alterar":
                ap.alterar(op["rel"], op["dados"])
            elif op["tipo"] == "retirar":
                ap.retirar(op["rel"])
            else:
                feito.append({"rel": op["rel"], "tipo": "pular", "nota": op.get("nota", "")})
                continue
            feito.append({"rel": op["rel"], "tipo": op["tipo"], "nota": op.get("nota", "")})
        if not ap.ops:
            return {"ok": True, "acao": acao, "feito": feito, "nada_a_fazer": True, "copia": ""}
    return {"ok": True, "acao": acao, "feito": feito, "nada_a_fazer": False, "copia": str(ap.pasta), "id": ap.registro["id"]}


def previa_desfazer(p, cfg=None):
    """O que o Desfazer faria (só leitura), com a diferença dos arquivos que o dono mexeu depois da aplicação."""
    return escrita_projeto.previa_desfazer(p, cfg if cfg is not None else config.ler_config())


def desfazer(p, confirmar=False, cfg=None, aceitar_mexidos=None):
    """Desfaz a última aplicação. Se o dono mexeu num arquivo depois, só com 'aceitar_mexidos' = assinatura da prévia."""
    if confirmar is not True:
        raise EscritaRecusada("desfazer precisa da confirmação do dono")
    return escrita_projeto.desfazer(p, cfg, aceitar_mexidos)
