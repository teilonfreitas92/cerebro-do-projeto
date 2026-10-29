"""Avisos de memória velha ou contraditória (heurística simples, SEM IA). Nunca muda nada: tudo é "a conferir".

Três tipos de aviso, cada um com o motivo explicado:
  (a) "caminho": a memória cita arquivo, caminho ou função que não existe mais no projeto (e "link": [[nome]] que não acha
      nenhuma memória);
  (b) "velha": memória com data antiga (modified do cabeçalho, ou a data do arquivo) que fala de estado/andamento
      ("em andamento", "pendente", "atualmente"...) — provavelmente já mudou;
  (c) "contradicao": duas memórias (ou uma memória e uma decisão registrada) sobre o mesmo assunto (mesmos links, mesmos
      arquivos citados ou muitas palavras em comum) com termos opostos (ligado/desligado, usar/não usar, sempre/nunca,
      "x: sim" / "x: não") ou números diferentes para a mesma coisa ("botões 28 px" / "botões 32 px").
A procura de arquivos/funções no projeto lê só nomes de arquivos e, para funções, o texto dos arquivos de código (com
limites de quantidade e tamanho). O resultado fica num cache curto por projeto.
"""
import datetime
import os
import re
import time
import unicodedata
from pathlib import Path

from . import decisoes, memoria
from .memoria_edicao import INDICE
from .segredos import encurtar

DIAS_VELHA = 30
MAX_ARQUIVOS_PROJETO = 20_000
MAX_BYTES_CODIGO = 40_000_000
MAX_POR_TIPO = 40
PULAR_PASTAS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", ".next", ".cache", ".pytest_cache",
                ".mypy_cache", ".ruff_cache", "target", ".idea", ".vscode", "graphify-out", ".claude"}
EXT_CODIGO = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".cs", ".cpp", ".c", ".h", ".hpp", ".rb",
              ".php", ".kt", ".swift", ".sql", ".sh", ".ps1", ".bat", ".html", ".css", ".vue", ".svelte", ".lua", ".mq5", ".mqh"}
_EXT_CAMINHO = ("py|js|mjs|cjs|ts|tsx|jsx|json|md|css|html|htm|yml|yaml|toml|txt|bat|ps1|sh|rs|go|java|cs|cpp|c|h|hpp|sql|ini|cfg|"
                "csv|vue|svelte|lua|mq5|mqh|rb|php|kt|swift|xml|env|lock")
_CAMINHO = re.compile(r"(?<![\w/\\.:-])((?:[A-Za-z]:[\\/]|[\\/])?(?:[\w.\-]+[\\/])*[\w\-][\w.\-]*\.(?:" + _EXT_CAMINHO + r"))(?![\w/\\-])")
_URL = re.compile(r"\b[a-z][a-z0-9+.\-]*://\S+", re.I)
_FUNCAO = re.compile(r"`(?:[A-Za-z_][\w]*\.)*([A-Za-z_][\w]{3,})\(\)?[^`]{0,40}`")
_LINK = re.compile(r"\[\[([^\]|#]{1,120})(?:[|#][^\]]*)?\]\]")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
EMBUTIDAS = {"print", "open", "range", "len", "str", "int", "float", "list", "dict", "set", "tuple", "type", "super", "input", "sorted",
             "format", "isinstance", "getattr", "setattr", "fetch", "require", "console", "setTimeout", "setInterval", "main", "init",
             "self", "this", "async", "await", "then", "catch", "json", "loads", "dumps", "read", "write", "join", "split", "strip",
             "replace", "append", "extend", "update", "items", "keys", "values", "exists", "mkdir", "resolve", "glob", "Path"}
ESTADO = re.compile(r"\b(em andamento|andamento|estado atual|status atual|pendente|pendentes|atualmente|no momento|ainda nao|"
                    r"proximo passo|proximos passos|falta fazer|em progresso|wip|in progress|work in progress|currently|ongoing|"
                    r"esta semana|nesta semana|hoje|por enquanto|temporari[oa]|provisori[oa])\b")
# pares de termos opostos (sobre texto SEM acento e em minúsculas)
OPOSTOS = (
    ("ligado", r"(?<!des)\bligad[oa]s?\b", "desligado", r"\bdesligad[oa]s?\b"),
    ("ativado", r"\bativad[oa]s?\b", "desativado", r"\bdesativad[oa]s?\b|\binativ[oa]s?\b"),
    ("habilitado", r"\bhabilitad[oa]s?\b", "desabilitado", r"\bdesabilitad[oa]s?\b"),
    ("usar", r"(?<!nao )(?<!nunca )\busa[r]?\b|(?<!nao )(?<!nunca )\buse\b", "não usar", r"\b(?:nao|nunca) (?:usa[r]?|use)\b"),
    ("pode", r"(?<!nao )\bpode\b", "não pode", r"\bnao pode\b"),
    ("permitido", r"\bpermitid[oa]s?\b", "proibido", r"\bproibid[oa]s?\b"),
    ("sempre", r"\bsempre\b", "nunca", r"\bnunca\b"),
    ("sim", r":\s*sim\b", "não", r":\s*nao\b"),
    ("true", r"\btrue\b", "false", r"\bfalse\b"),
    ("aprovado", r"\baprovad[oa]s?\b", "recusado", r"\b(?:recusad|rejeitad|reprovad)[oa]s?\b"),
)
_OPOSTOS = [(a, re.compile(ra), b, re.compile(rb)) for a, ra, b, rb in OPOSTOS]
_NUMERO = re.compile(r"\b([a-z]{4,})\s+(?:(?:de|do|da|com|em|=|:|igual a)\s+)?(\d+(?:[.,]\d+)?)\s*(px|%|ms|seg|segundos|min|minutos|h|horas|dias|tokens|kb|mb|gb|mil|reais|usd)?(?![\w/:.,-]*\d)")
VAZIAS = set("""sobre como para pela pelo pelas pelos onde quando quem qual quais isso isto esse essa este esta aquele aquela
porque porem pois entao ainda tambem mais menos muito muita muitos muitas todo toda todos todas cada mesmo mesma depois antes
sempre nunca regra regras memoria memorias projeto arquivo arquivos usuario feedback reference project user should would could
about there their which where when with from that this have will what your into than them they then were been being does
apply como aplicar fazer feito deve devem pode podem ficar fica sera seria tinha temos usar nao sim""".split())
NUMERO_GENERICO = {"versao", "linha", "linhas", "passo", "passos", "item", "itens", "dias", "vezes", "fase", "etapa", "commit", "sessao",
                   "teste", "testes", "porta"}
_cache = {}
TTL_CACHE = 600


def _sem_acento(t):
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode("ascii").lower()


# ---------------------------------------------------------------------------------------------------------------
# Leitura dos documentos (memórias + decisões ativas)
# ---------------------------------------------------------------------------------------------------------------
def _data_modified(valor):
    if not valor:
        return None
    try:
        return datetime.datetime.fromisoformat(str(valor).strip().replace("Z", "+00:00")[:25]).timestamp()
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(valor))
        if m:
            try:
                return datetime.datetime(int(m[1]), int(m[2]), int(m[3])).timestamp()
            except ValueError:
                return None
    return None


def documentos(slug):
    """Memórias (sem o MEMORY.md) e decisões ATIVAS registradas no Cérebro, num formato só."""
    docs = []
    pm = memoria.pasta_memoria(slug)
    if pm.is_dir():
        for f in sorted(pm.glob("*.md")):
            if f.name == INDICE or not memoria._ID_MEMORIA.match(f.name):
                continue
            texto = memoria._ler(f) or ""
            campos, corpo = memoria._cabecalho(texto)
            mtime = f.stat().st_mtime
            data = _data_modified(campos.get("modified")) or mtime
            docs.append({"id": "mem/" + f.name, "nome": f.name, "titulo": campos.get("name") or f.name, "texto": texto,
                         "corpo": corpo, "data": data, "fonte": "memória"})
    try:
        for d in decisoes.listar(slug, so_ativas=True):
            docs.append({"id": "dec/" + d["id"], "nome": d["id"], "titulo": "Decisão: " + d["texto"][:60], "texto": d["texto"],
                         "corpo": d["texto"], "data": d.get("em") or 0, "fonte": "decisão"})
    except ValueError:
        pass
    return docs


# ---------------------------------------------------------------------------------------------------------------
# (a) caminhos, funções e links que não existem
# ---------------------------------------------------------------------------------------------------------------
def indice_do_projeto(caminho_projeto, com_funcoes=True):
    """(caminhos relativos em minúsculas, nomes de arquivo em minúsculas, identificadores do código). Com limites."""
    raiz = Path(caminho_projeto)
    rels, nomes, idents = set(), set(), set()
    if not raiz.is_dir():
        return None
    lidos = n = 0
    for pasta_atual, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s not in PULAR_PASTAS and not s.startswith(".")]
        for a in arquivos:
            n += 1
            if n > MAX_ARQUIVOS_PROJETO:
                return rels, nomes, idents
            caminho = Path(pasta_atual) / a
            rel = caminho.relative_to(raiz).as_posix().lower()
            rels.add(rel)
            nomes.add(a.lower())
            if com_funcoes and caminho.suffix.lower() in EXT_CODIGO and lidos < MAX_BYTES_CODIGO:
                try:
                    if caminho.stat().st_size > 2_000_000:
                        continue
                    txt = caminho.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                lidos += len(txt)
                idents.update(_IDENT.findall(txt))
    return rels, nomes, idents


def _caminho_existe(cit, raiz, rels, nomes):
    c = cit.replace("\\", "/")
    baixo = c.lower()
    if re.match(r"^[a-z]:/|^/", baixo):                                  # absoluto: só julga se for dentro do projeto
        raiz_b = str(raiz).replace("\\", "/").lower().rstrip("/") + "/"
        if not baixo.startswith(raiz_b):
            return True
        return baixo[len(raiz_b):] in rels
    while baixo.startswith("./"):
        baixo = baixo[2:]
    if "/" not in baixo:
        return baixo in nomes
    return baixo in rels or any(r.endswith("/" + baixo) for r in rels)


def avisos_caminhos(docs, caminho_projeto, nomes_memoria, rapido=False):
    saida = []
    idx = None if rapido else indice_do_projeto(caminho_projeto)
    for d in docs:
        if d["fonte"] != "memória":
            continue
        corpo = _URL.sub(" ", d["corpo"])
        for alvo in sorted(set(_LINK.findall(corpo))):
            alvo_n = alvo.strip()
            if alvo_n.lower() not in nomes_memoria:
                saida.append({"tipo": "link", "arquivos": [d["id"]], "titulo": d["titulo"],
                              "motivo": f"o link [[{alvo_n}]] não acha nenhuma memória com esse nome (renomeada ou arquivada?)",
                              "trecho": f"[[{alvo_n}]]"})
        if idx is None:
            continue
        rels, nomes, idents = idx
        faltam = []
        for cit in sorted(set(_CAMINHO.findall(corpo))):
            if cit.lower().endswith(".md") and cit.lower().split("/")[-1].split("\\")[-1] in nomes_memoria:
                continue                                                  # outra memória
            if not _caminho_existe(cit, caminho_projeto, rels, nomes):
                faltam.append(cit)
        if faltam:
            saida.append({"tipo": "caminho", "arquivos": [d["id"]], "titulo": d["titulo"],
                          "motivo": "cita arquivo(s) que não existem mais no projeto: " + ", ".join(faltam[:5]) + (" …" if len(faltam) > 5 else ""),
                          "trecho": ", ".join(faltam[:5])})
        if idents:
            sem = sorted({f for f in _FUNCAO.findall(corpo) if f not in idents and f not in EMBUTIDAS and ("_" in f or any(ch.isupper() for ch in f[1:]) or len(f) >= 6)})
            if sem:
                saida.append({"tipo": "caminho", "arquivos": [d["id"]], "titulo": d["titulo"],
                              "motivo": "cita função(ões) que não aparecem em nenhum arquivo de código do projeto: " + ", ".join(s + "()" for s in sem[:5]),
                              "trecho": ", ".join(sem[:5])})
    return saida


# ---------------------------------------------------------------------------------------------------------------
# (b) memória velha que fala de estado
# ---------------------------------------------------------------------------------------------------------------
def avisos_velhas(docs, dias=DIAS_VELHA, agora=None):
    agora = agora or time.time()
    saida = []
    for d in docs:
        if d["fonte"] != "memória":
            continue
        idade = (agora - (d["data"] or agora)) / 86400
        if idade < dias:
            continue
        m = ESTADO.search(_sem_acento(d["corpo"]))
        if m:
            saida.append({"tipo": "velha", "arquivos": [d["id"]], "titulo": d["titulo"],
                          "motivo": f"fala de estado (\"{m.group(1)}\") e não muda há {int(idade)} dias: o estado provavelmente já é outro",
                          "trecho": _trecho(d["corpo"], m.group(1))})
    return saida


def _trecho(texto, termo):
    baixo = _sem_acento(texto)
    i = baixo.find(termo)
    if i < 0:
        return encurtar(texto, 160)
    return encurtar(texto[max(0, i - 60):i + len(termo) + 80].replace("\n", " "), 200)


# ---------------------------------------------------------------------------------------------------------------
# (c) pares possivelmente contraditórios
# ---------------------------------------------------------------------------------------------------------------
def _assunto(d):
    t = _sem_acento(_URL.sub(" ", d["corpo"] + " " + d["titulo"]))
    palavras = {w for w in re.findall(r"[a-z]{5,}", t) if w not in VAZIAS}
    links = {x.strip().lower() for x in _LINK.findall(d["corpo"])}
    arquivos = {c.lower().replace("\\", "/").split("/")[-1] for c in _CAMINHO.findall(d["corpo"])}
    numeros = {}
    for m in _NUMERO.finditer(t):
        chave = m.group(1)
        if chave in VAZIAS or chave in NUMERO_GENERICO:
            continue
        numeros.setdefault((chave, m.group(3) or ""), set()).add(m.group(2).replace(",", "."))
    termos = {}
    for a, ra, b, rb in _OPOSTOS:
        tem_a, tem_b = bool(ra.search(t)), bool(rb.search(t))
        if tem_a != tem_b:
            termos[(a, b)] = a if tem_a else b
    return {"palavras": palavras, "links": links | {d["nome"].lower().removesuffix(".md")}, "arquivos": arquivos, "numeros": numeros,
            "termos": termos, "texto": t}


def _mesmo_assunto(x, y):
    """Motivo (texto) se as duas falam da mesma coisa, ou None."""
    if (x["links"] & y["links"]) - {""}:
        comuns = (x["links"] & y["links"])
        return "citam a mesma memória (" + ", ".join(sorted(comuns)[:3]) + ")"
    arq = x["arquivos"] & y["arquivos"]
    if arq:
        return "citam o(s) mesmo(s) arquivo(s): " + ", ".join(sorted(arq)[:3])
    comuns = x["palavras"] & y["palavras"]
    uniao = x["palavras"] | y["palavras"]
    if len(comuns) >= 3 and uniao and len(comuns) / len(uniao) >= 0.25:
        return "muitas palavras em comum (" + ", ".join(sorted(comuns)[:5]) + ")"
    return None


def avisos_contradicoes(docs, limite_docs=400):
    saida = []
    feats = [(d, _assunto(d)) for d in docs[:limite_docs]]
    for i in range(len(feats)):
        d1, f1 = feats[i]
        for j in range(i + 1, len(feats)):
            d2, f2 = feats[j]
            motivos = []
            assunto = _mesmo_assunto(f1, f2)
            if assunto:
                for par, lado in f1["termos"].items():
                    outro = f2["termos"].get(par)
                    if outro and outro != lado:
                        motivos.append(f"uma diz \"{lado}\" e a outra \"{outro}\"")
            for chave, vals in f1["numeros"].items():
                outros = f2["numeros"].get(chave)
                if outros and not (vals & outros) and (assunto or chave[1]):
                    motivos.append(f"números diferentes para \"{chave[0]}{(' (' + chave[1] + ')') if chave[1] else ''}\": "
                                   f"{', '.join(sorted(vals))} × {', '.join(sorted(outros))}")
            if motivos:
                saida.append({"tipo": "contradicao", "arquivos": [d1["id"], d2["id"]], "titulo": f"{d1['titulo']}  ×  {d2['titulo']}",
                              "motivo": "; ".join(motivos[:3]) + (f" — {assunto}" if assunto else ""),
                              "trecho": encurtar(d1["corpo"].strip().split("\n")[0], 120) + "  ×  " + encurtar(d2["corpo"].strip().split("\n")[0], 120)})
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Junta tudo (com cache curto)
# ---------------------------------------------------------------------------------------------------------------
def _assinatura(slug):
    pm = memoria.pasta_memoria(slug)
    try:
        itens = sorted((f.name, f.stat().st_mtime_ns) for f in pm.glob("*.md"))
    except OSError:
        itens = []
    try:
        dec = decisoes._arquivo(slug).stat().st_mtime_ns
    except (OSError, ValueError):
        dec = 0
    return (tuple(itens), dec)


def avisos(slug, caminho_projeto, dias=DIAS_VELHA, rapido=False, usar_cache=True):
    """Todos os avisos "a conferir" do projeto. rapido=True pula a procura de arquivos/funções no projeto (usa o cache se houver)."""
    ass = _assinatura(slug)
    c = _cache.get(slug)
    if usar_cache and c and c["assinatura"] == ass and time.time() - c["em"] < TTL_CACHE and (rapido or not c["rapido"]):
        return c["dados"]
    docs = documentos(slug)
    nomes_memoria = {d["nome"].lower() for d in docs if d["fonte"] == "memória"}
    nomes_memoria |= {n.removesuffix(".md") for n in list(nomes_memoria)}
    nomes_memoria |= {_sem_acento(d["titulo"]).strip() for d in docs if d["fonte"] == "memória"} | {d["titulo"].lower().strip() for d in docs if d["fonte"] == "memória"}
    lista = (avisos_caminhos(docs, caminho_projeto, nomes_memoria, rapido) + avisos_velhas(docs, dias) + avisos_contradicoes(docs))
    por_tipo = {}
    final = []
    for a in lista:
        por_tipo[a["tipo"]] = por_tipo.get(a["tipo"], 0) + 1
        if por_tipo[a["tipo"]] <= MAX_POR_TIPO:
            a["motivo"] = encurtar(a["motivo"], 400)
            a["trecho"] = encurtar(a["trecho"], 300)
            a["titulo"] = encurtar(a["titulo"], 200)
            final.append(a)
    dados = {"avisos": final, "contagem": por_tipo, "total": len(lista), "rapido": rapido, "dias_velha": dias,
             "nota": "Heurística simples, sem IA: cada item é só um palpite para você conferir. Nada é mudado sozinho."}
    _cache[slug] = {"assinatura": ass, "em": time.time(), "rapido": rapido, "dados": dados}
    return dados


def itens_fila(p, cfg=None):
    """Itens para "Precisa de você" (rápido: sem varrer o projeto, a não ser que a aba já tenha feito e esteja no cache)."""
    dias = int(((cfg or {}).get("memoria_avisos") or {}).get("dias_velha") or DIAS_VELHA)
    d = avisos(p["slug"], p["caminho"], dias=dias, rapido=True)
    if not d["total"]:
        return []
    c = d["contagem"]
    partes = []
    if c.get("contradicao"):
        partes.append(f"{c['contradicao']} par(es) possivelmente contraditório(s)")
    if c.get("velha"):
        partes.append(f"{c['velha']} memória(s) velha(s) falando de estado")
    if c.get("caminho") or c.get("link"):
        partes.append(f"{c.get('caminho', 0) + c.get('link', 0)} citação(ões) de arquivo/função/link que não existe mais")
    return [{"nivel": "aviso", "projeto": p["slug"], "titulo": f"{p['nome']}: memória a conferir",
             "texto": "; ".join(partes) + ". Só palpites: confira na aba Memória e decisões (nada é mudado sozinho).", "aba": "memoria"}]
