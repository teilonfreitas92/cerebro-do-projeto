"""Memória e decisões do projeto (SOMENTE LEITURA nesta versão).

Lê o que o Claude Code guarda como memória do projeto (~/.claude/projects/<slug>/memory/: um índice
MEMORY.md e um arquivo por fato, com cabeçalho `---`) e os documentos fixos do projeto (CLAUDE.md, AGENTS.md).
Calcula o "contexto fixo": quanto do MEMORY.md + CLAUDE.md + AGENTS.md é carregado em TODA conversa (estimativa de
tokens = caracteres / 4) — a base da economia de tokens.
"""
import re
from pathlib import Path

from . import config
from .segredos import encurtar, mascarar

LIMITE_LEITURA = 400_000          # bytes lidos por arquivo
AVISO_MEMORY_BYTES = 12 * 1024    # avisa quando o MEMORY.md passa disto (ele é lido inteiro a cada conversa)
_ID_MEMORIA = re.compile(r"^[A-Za-z0-9_.\-]{1,120}\.md$")
TIPOS = ("user", "feedback", "project", "reference")


def estimar_tokens(chars):
    return int(round(chars / 4))


def _ler(caminho):
    try:
        with open(caminho, "rb") as f:
            return f.read(LIMITE_LEITURA).decode("utf-8", "replace")
    except OSError:
        return None


def _cabecalho(texto):
    """Campos do cabeçalho `---` (name, description, type, modified), mesmo aninhados em metadata:."""
    if not texto.startswith("---"):
        return {}, texto
    fim = texto.find("\n---", 3)
    if fim < 0:
        return {}, texto
    bloco = texto[3:fim]
    campos = {}
    for m in re.finditer(r"^\s*(name|description|type|modified|originSessionId)\s*:\s*(.*)$", bloco, re.M):
        v = m.group(2).strip().strip('"').strip("'").replace('\\"', '"')
        campos.setdefault(m.group(1), v)
    corpo = texto[fim + 4:].lstrip("\r\n")
    return campos, corpo


def _marcas(*partes):
    t = " ".join(p for p in partes if p).upper()
    return {"regra": "REGRA" in t or "REQUISITO" in t,
            "decisao": "DECISÃO" in t or "DECISAO" in t or "DECIDIU" in t or "APROVADO" in t,
            "plano": "PLANO" in t or "ARQUITETURA" in t}


def _entrada(origem, nome, caminho, id_):
    texto = _ler(caminho)
    if texto is None:
        return None
    st = Path(caminho).stat()
    campos, corpo = _cabecalho(texto)
    titulo = encurtar(campos.get("name") or nome, 120)
    descricao = campos.get("description") or ""
    if not descricao:
        for linha in corpo.splitlines():
            if linha.strip() and not linha.startswith("#"):
                descricao = linha.strip()[:200]
                break
    tipo = campos.get("type") if campos.get("type") in TIPOS else ""
    marcas = _marcas(descricao, corpo[:600])
    return {"id": id_, "origem": origem, "arquivo": nome, "titulo": titulo, "descricao": mascarar(descricao[:300]),
            "tipo": tipo, "modificado": st.st_mtime, "chars": len(texto), "tokens": estimar_tokens(len(texto)), **marcas}


def pasta_memoria(slug):
    return config.PROJETOS_CLAUDE / slug / "memory"


def listar(slug, caminho_projeto):
    """Tudo que forma a memória e as regras do projeto + o contexto fixo."""
    itens = []
    fixos = []
    pm = pasta_memoria(slug)
    indice_md = pm / "MEMORY.md"
    if indice_md.is_file():
        e = _entrada("memoria", "MEMORY.md", indice_md, "mem/MEMORY.md")
        if e:
            e["tipo"] = "índice"
            itens.append(e)
            fixos.append({"nome": "MEMORY.md (índice da memória)", "chars": e["chars"], "tokens": e["tokens"],
                          "bytes": indice_md.stat().st_size})
    if pm.is_dir():
        for f in sorted(pm.glob("*.md")):
            if f.name == "MEMORY.md" or not _ID_MEMORIA.match(f.name):
                continue
            e = _entrada("memoria", f.name, f, "mem/" + f.name)
            if e:
                itens.append(e)
    for doc in ("CLAUDE.md", "AGENTS.md"):
        caminho = Path(caminho_projeto) / doc
        if caminho.is_file():
            e = _entrada("projeto", doc, caminho, "proj/" + doc)
            if e:
                e["tipo"] = "documento"
                itens.append(e)
                fixos.append({"nome": doc, "chars": e["chars"], "tokens": e["tokens"], "bytes": caminho.stat().st_size})
    glob = config.CLAUDE / "CLAUDE.md"
    if glob.is_file():
        e = _entrada("global", "CLAUDE.md (global do usuário)", glob, "global/CLAUDE.md")
        if e:
            e["tipo"] = "documento"
            itens.append(e)
    total = sum(x["tokens"] for x in fixos)
    glob_tokens = next((e["tokens"] for e in itens if e["origem"] == "global"), 0)
    avisos = []
    for x in fixos:
        if x["nome"].startswith("MEMORY.md") and x["bytes"] > AVISO_MEMORY_BYTES:
            avisos.append(f"MEMORY.md tem {x['bytes'] // 1024} KB (acima de 12 KB): cada conversa nova paga isso. Vale enxugar o índice.")
    itens.sort(key=lambda e: (e["origem"] != "memoria" or e["arquivo"] != "MEMORY.md", -e["modificado"]))
    return {"itens": itens, "contexto_fixo": {"arquivos": fixos, "total_tokens": total, "global_tokens": glob_tokens,
                                               "total_chars": sum(x["chars"] for x in fixos)},
            "avisos": avisos, "pasta_memoria": str(pm), "existe": pm.is_dir()}


def _caminho_do_id(slug, caminho_projeto, id_):
    origem, _, nome = (id_ or "").partition("/")
    if origem == "mem" and _ID_MEMORIA.match(nome):
        return pasta_memoria(slug) / nome
    if origem == "proj" and nome in ("CLAUDE.md", "AGENTS.md"):
        return Path(caminho_projeto) / nome
    if origem == "global" and nome == "CLAUDE.md":
        return config.CLAUDE / "CLAUDE.md"
    return None


def conteudo(slug, caminho_projeto, id_):
    """Texto (mascarado) de um item da lista. None se o id não for válido."""
    c = _caminho_do_id(slug, caminho_projeto, id_)
    if c is None or not c.is_file():
        return None
    return mascarar(_ler(c) or "")


def buscar(slug, caminho_projeto, termo, limite=40):
    """Busca de texto simples (sem diferenciar maiúsculas) em toda a memória e nos documentos fixos."""
    termo = (termo or "").strip().lower()
    if len(termo) < 2:
        return []
    achados = []
    for e in listar(slug, caminho_projeto)["itens"]:
        c = _caminho_do_id(slug, caminho_projeto, e["id"])
        texto = _ler(c) if c else None
        if not texto:
            continue
        texto = mascarar(texto)                       # primeiro mascara o texto INTEIRO; só depois procura e recorta
        baixo = texto.lower()
        i = baixo.find(termo)
        if i < 0:
            continue
        ini = max(0, i - 70)
        trecho = texto[ini:i + len(termo) + 110].replace("\n", " ")
        achados.append({"id": e["id"], "titulo": e["titulo"], "arquivo": e["arquivo"], "origem": e["origem"],
                        "trecho": trecho, "ocorrencias": baixo.count(termo)})
        if len(achados) >= limite:
            break
    achados.sort(key=lambda a: -a["ocorrencias"])
    return achados
