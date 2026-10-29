"""Manual do gestor DENTRO de um projeto: um bloco marcado no CLAUDE.local.md que importa o ~/.cerebro/GESTOR.md.

    <!-- cerebro:gestor:inicio -->
    @~/.cerebro/GESTOR.md
    <!-- cerebro:gestor:fim -->

CLAUDE.local.md é o arquivo de instruções LOCAIS do Claude Code (não deve ir para o git). Antes de qualquer coisa, o Cérebro
confere com o git (só leitura): `git ls-files --error-unmatch CLAUDE.local.md` (rastreado → RECUSA: o bloco iria para o
repositório) e `git check-ignore -q CLAUDE.local.md` (não ignorado → a mesma ação acrescenta "CLAUDE.local.md" ao
.git/info/exclude, a lista de ignorados só deste PC, e a prévia mostra isso).

Toda escrita passa por escrita_projeto (trava de caminho, cópia antes, escrita atômica, histórico). Idempotente: com o bloco lá,
"Ligar" não faz nada. "Desligar" tira SÓ o bloco (o resto do arquivo fica); se o arquivo ficar vazio, ele vai para a pasta de
cópias (nunca é apagado) e a linha que o Cérebro pôs no .git/info/exclude sai junto. Só roda com confirmar=True.
"""
import difflib
import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import config, escrita_projeto, projetos
from .escrita_projeto import EscritaRecusada
from .segredos import mascarar

INICIO, FIM = "<!-- cerebro:gestor:inicio -->", "<!-- cerebro:gestor:fim -->"
ARQ = "CLAUDE.local.md"
EXCLUDE = ".git/info/exclude"
MARCA_EXCLUDE = "# cerebro:gestor (CLAUDE.local.md fica fora do git)"
ACOES = {"instalar": "Ligar o manual do gestor (CLAUDE.local.md)", "remover": "Desligar o manual do gestor (tira só o bloco)"}


def linha_import():
    """'@~/.cerebro/GESTOR.md' na instalação normal; com CEREBRO_HOME em outro lugar, o caminho absoluto dele."""
    casa = Path(config.CASA)
    try:
        normal = casa.resolve() == (Path.home() / ".cerebro").resolve()
    except OSError:
        normal = False
    return "@~/.cerebro/GESTOR.md" if normal else "@" + str(casa / "GESTOR.md").replace("\\", "/")


def bloco(fim="\n"):
    return fim.join([INICIO, linha_import(), FIM]) + fim


def rodar_git(raiz, args):
    """Código de saída do git (só leitura) ou None se o git não existe. Sem shell, sem janela, tempo limite."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(raiz), *args], capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return r.returncode
    except (OSError, subprocess.SubprocessError):
        return None


def situacao_git(raiz):
    """{repo, rastreado, ignorado}. Repositório sem git instalado → recusa (não dá para conferir)."""
    if not (Path(raiz) / ".git").is_dir():
        return {"repo": False, "rastreado": False, "ignorado": False}
    rastreado = rodar_git(raiz, ["ls-files", "--error-unmatch", ARQ])
    ignorado = rodar_git(raiz, ["check-ignore", "-q", ARQ])
    if rastreado is None or ignorado is None:
        raise EscritaRecusada("não consegui rodar o git para conferir se o CLAUDE.local.md está fora do repositório")
    return {"repo": True, "rastreado": rastreado == 0, "ignorado": ignorado == 0}


def _texto(b):
    try:
        return (b or b"").decode("utf-8")
    except UnicodeDecodeError:
        raise EscritaRecusada("o arquivo não está em UTF-8: o Cérebro não mexe nele") from None


def _sem_bloco(txt):
    """Texto sem o bloco (e sem a linha em branco que o Cérebro pôs antes dele). None se não há bloco inteiro."""
    i = txt.find(INICIO)
    j = txt.find(FIM, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return None
    fim_bloco = j + len(FIM)
    for quebra in ("\r\n", "\n"):
        if txt.startswith(quebra, fim_bloco):
            fim_bloco += len(quebra)
            break
    antes = txt[:i]
    for quebra in ("\r\n", "\n"):                     # a linha em branco que separa o bloco do texto de antes
        if antes.endswith(quebra + quebra) or (antes == quebra):
            antes = antes[: -len(quebra)]
            break
    return antes + txt[fim_bloco:]


def _plano(raiz, acao):
    git = situacao_git(raiz)
    alvo = escrita_projeto.alvo_seguro(raiz, ARQ)
    antes = escrita_projeto.ler_existente(alvo)
    txt = _texto(antes) if antes is not None else None
    ops = []
    if acao == "instalar":
        if git["rastreado"]:
            raise EscritaRecusada("o CLAUDE.local.md deste projeto está no git (rastreado): o bloco iria para o repositório. "
                                  "Tire-o do git antes (git rm --cached CLAUDE.local.md) ou deixe o manual desligado aqui.")
        if txt is not None and INICIO in txt:
            ops.append({"rel": ARQ, "tipo": "pular", "nota": "o bloco do manual já está neste arquivo (nada a fazer)"})
        elif txt is None:
            ops.append({"rel": ARQ, "tipo": "criar", "dados": bloco().encode("utf-8"), "nota": "cria o arquivo só com o bloco"})
        else:
            fim = "\r\n" if "\r\n" in txt else "\n"
            base = txt if not txt or txt.endswith(("\n", "\r")) else txt + fim
            ops.append({"rel": ARQ, "tipo": "alterar", "dados": (base + (fim if base.strip() else "") + bloco(fim)).encode("utf-8"),
                        "nota": "acrescenta o bloco marcado no FIM; o resto fica como está"})
        if git["repo"] and not git["ignorado"]:
            ex = escrita_projeto.ler_existente(escrita_projeto.alvo_seguro(raiz, EXCLUDE))
            ex_txt = _texto(ex) if ex is not None else ""
            if ARQ not in [linha.strip() for linha in ex_txt.splitlines()]:
                novo = (ex_txt if not ex_txt or ex_txt.endswith("\n") else ex_txt + "\n") + MARCA_EXCLUDE + "\n" + ARQ + "\n"
                ops.append({"rel": EXCLUDE, "tipo": "alterar" if ex is not None else "criar", "dados": novo.encode("utf-8"),
                            "nota": "o git ainda não ignora o CLAUDE.local.md: acrescenta a linha na lista de ignorados SÓ deste PC "
                                    "(.git/info/exclude, não vai para o repositório)"})
        return ops, git
    if acao == "remover":
        if txt is None or _sem_bloco(txt) is None:
            return [{"rel": ARQ, "tipo": "pular", "nota": "não há bloco do manual neste projeto"}], git
        resto = _sem_bloco(txt)
        if resto.strip():
            ops.append({"rel": ARQ, "tipo": "alterar", "dados": resto.encode("utf-8"), "nota": "tira só o bloco; o resto fica"})
        else:
            ops.append({"rel": ARQ, "tipo": "retirar", "nota": "o arquivo só tinha o bloco: vai para a pasta de cópias (não é apagado)"})
            ex = escrita_projeto.ler_existente(escrita_projeto.alvo_seguro(raiz, EXCLUDE)) if git["repo"] else None
            ex_txt = _texto(ex) if ex is not None else ""
            if MARCA_EXCLUDE in ex_txt:
                linhas = ex_txt.splitlines(keepends=True)
                novas, pular = [], False
                for linha in linhas:
                    if linha.strip() == MARCA_EXCLUDE:
                        pular = True
                        continue
                    if pular and linha.strip() == ARQ:
                        pular = False
                        continue
                    pular = False
                    novas.append(linha)
                ops.append({"rel": EXCLUDE, "tipo": "alterar", "dados": "".join(novas).encode("utf-8"),
                            "nota": "tira a linha que o Cérebro pôs no .git/info/exclude"})
        return ops, git
    raise EscritaRecusada(f"ação desconhecida: {acao!r}")


def _diff(antes, depois, rel):
    a = (antes or b"").decode("utf-8", "replace").splitlines()
    d = (depois or b"").decode("utf-8", "replace").splitlines()
    return mascarar("\n".join(difflib.unified_diff(a, d, "antes/" + rel, "depois/" + rel, n=2, lineterm="")))


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


def instalado(p):
    try:
        txt = (Path(p["caminho"]) / ARQ).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return INICIO in txt


def previa(p, acao, cfg=None):
    """O que Ligar/Desligar faria (arquivos, diferença, situação no git). Não escreve nada."""
    raiz = escrita_projeto.conferir_projeto(p, cfg)
    ops, git = _plano(raiz, acao)
    arquivos = []
    for op in ops:
        alvo = escrita_projeto.alvo_seguro(raiz, op["rel"])
        antes = escrita_projeto.ler_existente(alvo)
        diff = _diff(antes, op.get("dados") or b"", op["rel"]) if op["tipo"] in ("criar", "alterar", "retirar") else ""
        arquivos.append({"rel": op["rel"], "tipo": op["tipo"], "nota": op.get("nota", ""), "diff": diff, "existe": antes is not None})
    return {"acao": acao, "titulo": ACOES.get(acao, acao), "arquivos": arquivos, "git": git, "instalado": instalado(p),
            "aplicavel": any(a["tipo"] != "pular" for a in arquivos), "assinatura": _assinatura(acao, ops, raiz),
            "copias": str(escrita_projeto.pasta_copias(p["slug"]))}


def aplicar(p, acao, confirmar=False, assinatura=None, cfg=None):
    """Liga (instalar) ou desliga (remover). Exige confirmar=True; com 'assinatura', recusa se o projeto mudou desde a prévia."""
    if confirmar is not True:
        raise EscritaRecusada("precisa da confirmação do dono")
    if acao not in ACOES:
        raise EscritaRecusada(f"ação desconhecida: {acao!r}")
    with escrita_projeto.Aplicacao(p, "manual-gestor", ACOES[acao], cfg) as ap:
        ops, _ = _plano(ap.raiz, acao)
        if assinatura is not None and assinatura != _assinatura(acao, ops, ap.raiz):
            raise EscritaRecusada("o projeto mudou desde a prévia: veja a prévia de novo")
        feito = []
        for op in ops:
            if op["tipo"] == "criar":
                ap.criar(op["rel"], op["dados"])
            elif op["tipo"] == "alterar":
                ap.alterar(op["rel"], op["dados"])
            elif op["tipo"] == "retirar":
                ap.retirar(op["rel"])
            feito.append({"rel": op["rel"], "tipo": op["tipo"], "nota": op.get("nota", "")})
        if not ap.ops:
            return {"ok": True, "acao": acao, "feito": feito, "nada_a_fazer": True, "copia": ""}
    return {"ok": True, "acao": acao, "feito": feito, "nada_a_fazer": False, "copia": str(ap.pasta), "id": ap.registro["id"]}


def projetos_com_bloco():
    return [p for p in projetos.descobrir(forcar=True) if p.get("caminho") and instalado(p)]


def desinstalar_passo(perguntar, saida):
    """Usado pelo desinstalar.py: lista os projetos com o bloco e oferece tirar (só o bloco, com cópia antes)."""
    try:
        lista = projetos_com_bloco()
    except (OSError, ValueError) as e:
        saida(f"      Não consegui procurar: {e}")
        return []
    if not lista:
        saida("      Nenhum projeto tem o bloco do manual do gestor: nada a tirar.")
        return []
    saida("      Projetos com o bloco do manual no CLAUDE.local.md: " + ", ".join(p["nome"] for p in lista))
    if not perguntar("Tirar o bloco desses projetos (só o bloco; cópia de segurança antes)?"):
        saida("      Mantido.")
        return []
    feitos = []
    for p in lista:
        try:
            aplicar(p, "remover", confirmar=True)
            feitos.append(p["nome"])
        except (EscritaRecusada, OSError, ValueError) as e:
            saida(f"      {p['nome']}: não tirei ({e})")
    saida("      Bloco tirado de: " + (", ".join(feitos) or "nenhum"))
    return feitos
