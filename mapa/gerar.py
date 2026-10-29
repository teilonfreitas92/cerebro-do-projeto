#!/usr/bin/env python
r"""Cérebro do Projeto — gerador do MAPA.

Lê o mapa do Graphify do projeto (<projeto>/graphify-out\: graph.json, .graphify_analysis.json,
.graphify_labels.json) e escreve `dados.js` (o mapa já mastigado) e `historico.json` (o que entrou, saiu ou mudou
desde a geração anterior). A página (index.html + cerebro.css + cerebro.js, nesta pasta) é servida pelo servidor do
Cérebro, na aba "Mapa" do projeto; nada é escrito dentro do projeto.

Uso:
    python mapa\gerar.py --projeto C:\caminho\do\projeto            # lê <projeto>/graphify-out
    python mapa\gerar.py --projeto PASTA --esperar                     # espera o graph.json ficar mais novo (até 15 min)
    python mapa\gerar.py --entrada PASTA --saida PASTA                 # caminhos explícitos (testes)
    python mapa\gerar.py --projeto PASTA --standalone                  # copia a página junto: abre por file://

Saída padrão: ~/.cerebro/projetos\<slug>\mapa\ (o <slug> é o nome de pasta que o Claude Code usa em
~/.claude/projects). A sessão gestora vem do config.json global (~/.cerebro/config.json).

Só LÊ o mapa; nunca roda comandos do Graphify. Só ESCREVE na pasta de saída.
"""
import argparse
import ast
import datetime
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent))
from cerebro.segredos import mascarar  # noqa: E402  (docstrings e comentários também podem ter segredo esquecido)
import deptos  # noqa: E402  (departamentos configuráveis por projeto; mapa/deptos.py)
ESTATICOS = ("index.html", "cerebro.css", "cerebro.js")
# Dados do Cérebro: ~/.cerebro (ou a pasta em CEREBRO_HOME, usada pelos testes)
CASA = Path(os.environ.get("CEREBRO_HOME") or (Path.home() / ".cerebro"))
CONFIG = CASA / "config.json"            # config global do Cérebro (sessão gestora por projeto, preços, etc.)
GESTORA_PADRAO = {"nome": "", "conversa": ""}   # projeto sem gestora escolhida: a página mostra "não escolhida"
MAX_HISTORICO = 100
MAX_AMOSTRA = 40          # itens listados por categoria em cada entrada da linha do tempo
LIMITE_TEXTO = 800        # caracteres do cabeçalho de um arquivo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------------------------------------------
# Departamentos
# ---------------------------------------------------------------------------------------------------------------
def carregar_esquema(slug, arquivos):
    """Departamentos do projeto: do config.json (departamentos.<slug>) ou, sem entrada, uma cor por pasta de primeiro nível."""
    conf = None
    try:
        conf = ((ler_json(CONFIG).get("departamentos") or {}) if CONFIG.exists() else {}).get(slug)
    except (OSError, ValueError, AttributeError):
        conf = None
    try:
        if isinstance(conf, dict) and conf.get("modo") == "regras":
            return deptos.esquema_regras(conf)
    except ValueError as e:
        print(f"Aviso: departamentos do config.json inválidos ({e}); usando as pastas.", file=sys.stderr)
    return deptos.esquema_pastas(arquivos)


# ---------------------------------------------------------------------------------------------------------------
# Texto explicativo: docstring / comentário do código-fonte
# ---------------------------------------------------------------------------------------------------------------
def _limpa(linhas):
    """Junta linhas de comentário em parágrafos curtos."""
    paragrafos, atual = [], []
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            if atual:
                paragrafos.append(" ".join(atual))
                atual = []
        else:
            atual.append(ln)
    if atual:
        paragrafos.append(" ".join(atual))
    return re.sub(r"[ \t]+", " ", "\n".join(paragrafos)).strip()


def _corta(txt, limite):
    txt = mascarar(txt)                 # antes de cortar: o corte nunca expõe um pedaço de segredo
    if len(txt) <= limite:
        return txt
    corte = txt[:limite].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return corte + "…"


def _marcador(ln):
    """Remove o marcador de comentário de uma linha (//, ///, //!, #, *)."""
    s = ln.strip()
    for m in ("//!", "///", "//", "#", "*"):
        if s.startswith(m):
            return s[len(m):].strip(), True
    return s, False


def comentario_a_partir_de(linhas, i):
    """Docstring ou comentário que começa na linha i (0-based). Devolve texto ou ''."""
    if i >= len(linhas):
        return ""
    s = linhas[i].strip()
    for asp in ('"""', "'''"):
        if s.startswith(asp) or s[:2].lower() in ('r"', "r'") and s[1:4] == asp:
            corpo = s.split(asp, 1)[1]
            if asp in corpo:
                return _limpa([corpo.split(asp, 1)[0]])
            acc = [corpo]
            for ln in linhas[i + 1:i + 60]:
                if asp in ln:
                    acc.append(ln.split(asp, 1)[0])
                    break
                acc.append(ln)
            return _limpa(acc)
    if s.startswith("/*"):
        acc = []
        for ln in linhas[i:i + 60]:
            acc.append(ln.strip().lstrip("/").lstrip("*").strip().replace("*/", ""))
            if "*/" in ln:
                break
        return _limpa(acc)
    if s.startswith("//") or (s.startswith("#") and not s.startswith(("#!", "#[", "#include", "#define", "#region"))):
        acc = []
        for ln in linhas[i:i + 60]:
            t, ok = _marcador(ln)
            if not ok or ln.strip().startswith("#["):
                break
            acc.append(t)
        return _limpa(acc)
    return ""


def cabecalho_do_arquivo(caminho, linhas):
    """Primeiro docstring / `//!` / comentário do topo do arquivo (até LIMITE_TEXTO caracteres)."""
    ext = caminho.rsplit(".", 1)[-1].lower() if "." in caminho else ""
    if ext in ("json", "lock", "html", "css", "md", "txt"):
        return ""
    texto = "\n".join(linhas)
    if ext == "py":
        try:
            doc = ast.get_docstring(ast.parse(texto))
            if doc:
                return _corta(_limpa(doc.split("\n")), LIMITE_TEXTO)
        except (SyntaxError, ValueError):
            pass
    for i, ln in enumerate(linhas[:30]):
        s = ln.strip()
        if not s or s.startswith("#!") or s in ("'use strict';", '"use strict";', "@echo off"):
            continue
        return _corta(comentario_a_partir_de(linhas, i), LIMITE_TEXTO)
    return ""


class LeitorFontes:
    """Lê os arquivos-fonte do projeto uma vez só."""

    def __init__(self, raiz):
        self.raiz = Path(raiz)
        self.cache = {}

    def linhas(self, rel):
        if rel not in self.cache:
            try:
                bruto = (self.raiz / rel).read_bytes()
                self.cache[rel] = bruto.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n")
            except OSError:
                self.cache[rel] = None
        return self.cache[rel]


# ---------------------------------------------------------------------------------------------------------------
# Tradução das "surpresas" do Graphify
# ---------------------------------------------------------------------------------------------------------------
TRAD_PORQUE = [
    ("inferred connection - not explicitly stated in source", "ligação inferida (não está escrita no código)"),
    ("connects across different repos/directories", "cruza pastas diferentes"),
    ("bridges separate communities", "liga grupos que não se falavam"),
    ("peripheral node", "item de borda"),
    ("unexpectedly reaches hub", "que de repente alcança o centro"),
    ("connects different file types", "mistura tipos de arquivo"),
    ("cross-file", "entre arquivos"),
]


def traduz_porque(txt):
    txt = re.sub(r"peripheral node `([^`]*)` unexpectedly reaches hub `([^`]*)`",
                 r"`\1` (item de borda) chega de repente ao centro `\2`", txt or "")
    out = []
    for parte in txt.split(";"):
        parte = parte.strip()
        for en, pt in TRAD_PORQUE:
            if parte.startswith(en):
                resto = parte[len(en):].strip()
                parte = pt + (" " + resto if resto else "")
                break
        out.append(parte)
    return "; ".join(p for p in out if p)


# ---------------------------------------------------------------------------------------------------------------
# Leitura do mapa
# ---------------------------------------------------------------------------------------------------------------
def slug_do_projeto(pasta):
    """Mesmo nome de pasta que o Claude Code usa em ~/.claude/projects: tudo que não é letra/dígito vira '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(pasta).resolve()))


def ler_config(slug):
    """Sessão gestora do projeto, do config.json global; se faltar ou estiver quebrado, devolve 'não escolhida'."""
    gestora = dict(GESTORA_PADRAO)
    try:
        g = (ler_json(CONFIG).get("gestoras") or {}).get(slug)
        if isinstance(g, dict):
            gestora = {"nome": str(g.get("nome") or ""), "conversa": str(g.get("conversa") or "")}
    except (OSError, ValueError, AttributeError):
        pass
    return {"sessaoGestora": gestora}


def ler_json(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def ler_json_opcional(caminho):
    """Arquivos auxiliares do Graphify: o `graphify update` (sem IA) não cria o .graphify_analysis.json; sem ele o mapa usa as
    comunidades que já vêm dentro do graph.json."""
    try:
        d = ler_json(caminho)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def git(raiz, *args):
    try:
        r = subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def tipo_do_item(n, eh_arquivo):
    """0 arquivo · 1 classe · 2 função · 3 método · 4 símbolo · 5 dependência externa · 6 pacote/conceito."""
    if eh_arquivo:
        return 0
    if n.get("external") or (n.get("file_type") == "concept" and not n.get("source_file")):
        return 5
    if n.get("file_type") == "concept":
        return 6
    lab = n.get("label", "")
    if lab.startswith(".") and lab.endswith("()"):
        return 3
    if n.get("_callable_class"):
        return 1
    if lab.endswith("()"):
        return 2
    return 4


TIPOS = ["arquivo", "classe", "função", "método", "símbolo", "dependência externa", "pacote ou conceito"]
RELACOES = ["calls", "indirect_call", "imports", "imports_from", "contains", "method", "references", "case_of",
            "uses", "inherits", "re_exports", "declares", "implements"]
IDX_REL = {r: i for i, r in enumerate(RELACOES)}


def processar(entrada, raiz, slug=None, esquema=None):
    g = ler_json(entrada / "graph.json")
    analise = ler_json_opcional(entrada / ".graphify_analysis.json")
    rotulos = ler_json_opcional(entrada / ".graphify_labels.json")
    if not isinstance(analise.get("communities"), dict) or not analise["communities"]:
        comunidades = defaultdict(list)
        for n in g["nodes"]:
            comunidades[str(n.get("community", 0))].append(n["id"])
        analise = {**analise, "communities": dict(comunidades)}
    for n in g["nodes"]:                                   # sem arquivo de rótulos: usa o nome da comunidade que está no próprio nó
        if n.get("community_name"):
            rotulos.setdefault(str(n.get("community", 0)), str(n["community_name"]))
    fontes = LeitorFontes(raiz)
    ligs_g = g.get("links") or g.get("edges") or []

    # ---- grupos (nome em pt-BR do arquivo de rótulos) ----
    com_ids = sorted(analise["communities"].keys(), key=lambda k: int(k))
    nome_grupo, usados = {}, Counter()
    for c in com_ids:
        nome = (rotulos.get(c) or "").strip() or f"Grupo {c}"
        usados[nome] += 1
        if usados[nome] > 1:
            nome = f"{nome} ({usados[nome]})"
        nome_grupo[c] = nome
    grupo_de_id = {}
    for c, ids in analise["communities"].items():
        for i in ids:
            grupo_de_id[i] = c
    for n in g["nodes"]:  # nós que a análise não listou (não deve ocorrer): usa a comunidade do próprio nó
        grupo_de_id.setdefault(n["id"], str(n.get("community", 0)))
    ordem_grupos = {c: i for i, c in enumerate(com_ids)}
    for c in set(grupo_de_id.values()):
        if c not in ordem_grupos:
            ordem_grupos[c] = len(ordem_grupos)
            com_ids.append(c)
            nome_grupo[c] = (rotulos.get(c) or f"Grupo {c}")

    # ---- entidades: arquivos primeiro, depois os demais itens (rationale vira texto, não ponto) ----
    arquivos = sorted({n["source_file"] for n in g["nodes"] if n.get("source_file")})
    esq = esquema or (carregar_esquema(slug, arquivos) if slug else deptos.esquema_pastas(arquivos))
    idx_arq = {f: i for i, f in enumerate(arquivos)}
    eh_no_arquivo, ja_tem = {}, set()
    for n in g["nodes"]:
        f = n.get("source_file")
        if f and n["file_type"] == "code" and n["label"] == f.rsplit("/", 1)[-1] and f not in ja_tem:
            eh_no_arquivo[n["id"]] = f
            ja_tem.add(f)
    ent_de_id = {nid: idx_arq[f] for nid, f in eh_no_arquivo.items()}
    # Nome, linha, tipo, grupo, departamento de cada entidade
    nF = len(arquivos)
    nome = [f.rsplit("/", 1)[-1] for f in arquivos]
    arq = list(range(nF))
    lin = [1] * nF
    tipo = [0] * nF
    grp = [None] * nF
    dep = [esq.indice(f) for f in arquivos]
    ids_ent = [None] * nF
    for nid, f in eh_no_arquivo.items():
        grp[idx_arq[f]] = ordem_grupos[grupo_de_id[nid]]
        ids_ent[idx_arq[f]] = nid
    rationale_nos = []
    for n in g["nodes"]:
        nid = n["id"]
        if nid in ent_de_id:
            continue
        if n["file_type"] == "rationale":
            rationale_nos.append(n)
            continue
        f = n.get("source_file") or ""
        e = len(nome)
        ent_de_id[nid] = e
        nome.append(n["label"])
        arq.append(idx_arq.get(f, -1))
        loc = str(n.get("source_location") or "")
        lin.append(int(loc[1:]) if loc[1:].isdigit() else 0)
        tipo.append(tipo_do_item(n, False))
        grp.append(ordem_grupos[grupo_de_id[nid]])
        dep.append(esq.indice(f))
        ids_ent.append(nid)
    total = len(nome)

    # Grupo do arquivo sem nó próprio: o da maioria dos seus itens
    por_arq = defaultdict(list)
    for e in range(nF, total):
        if arq[e] >= 0:
            por_arq[arq[e]].append(e)
    for a in range(nF):
        if grp[a] is None:
            cont = Counter(grp[e] for e in por_arq.get(a, []))
            grp[a] = cont.most_common(1)[0][0] if cont else 0

    # ---- ligações ----
    ligas, vistos = [], set()
    expl_bruta = defaultdict(list)       # entidade -> [(linha, texto, truncado)]
    rationale_por_id = {n["id"]: n for n in rationale_nos}
    for l in ligs_g:
        s, t, rel = l["source"], l["target"], l["relation"]
        if rel == "rationale_for":
            r = rationale_por_id.get(s)
            e = ent_de_id.get(t)
            if r is not None and e is not None:
                loc = str(r.get("source_location") or "")
                expl_bruta[e].append((r.get("source_file") or "", int(loc[1:]) if loc[1:].isdigit() else 0, r["label"]))
            continue
        es, et = ent_de_id.get(s), ent_de_id.get(t)
        if es is None or et is None or es == et or rel not in IDX_REL:
            continue
        inf = 1 if l.get("confidence") == "INFERRED" else 0
        chave = (es, et, IDX_REL[rel])
        if chave in vistos:
            continue
        vistos.add(chave)
        ligas.append((es, et, IDX_REL[rel] * 2 + inf))

    # ---- departamento dos itens sem arquivo (externos): o do grupo; grupo: maioria dos itens com arquivo ----
    cont_g = defaultdict(Counter)
    for e in range(total):
        if dep[e] >= 0:
            cont_g[grp[e]][dep[e]] += 1
    viz_g = defaultdict(Counter)
    for s, t, _ in ligas:
        if dep[s] >= 0:
            viz_g[grp[t]][dep[s]] += 1
        if dep[t] >= 0:
            viz_g[grp[s]][dep[t]] += 1
    nG = len(com_ids)
    dep_grupo = []
    for gi in range(nG):
        c = cont_g.get(gi) or viz_g.get(gi)
        dep_grupo.append(c.most_common(1)[0][0] if c else esq.indice_padrao)
    for e in range(total):
        if dep[e] < 0:
            dep[e] = dep_grupo[grp[e]]

    # ---- explicações ----
    expl = {}
    for e, lista in expl_bruta.items():
        textos, vistos_t = [], set()
        for f, ln, label in sorted(lista, key=lambda x: x[1]):
            txt = label
            if label.endswith("…") and f:
                ls = fontes.linhas(f)
                if ls and ln:
                    achado = comentario_a_partir_de(ls, ln - 1)
                    if achado and achado[:12].lower() == label[:12].lower():
                        txt = _corta(achado, 700)
            if txt not in vistos_t:
                vistos_t.add(txt)
                textos.append(txt)
        expl[e] = "\n".join(textos[:3])
    for a in range(nF):          # arquivo: o cabeçalho do código vale mais que o texto cortado do mapa
        ls = fontes.linhas(arquivos[a])
        cab = cabecalho_do_arquivo(arquivos[a], ls) if ls else ""
        if cab:
            expl[a] = cab

    # ---- explicações por IA (opcional): só para quem não tem texto próprio; sem o arquivo explicacoes.json nada muda ----
    ia = {}
    if slug:
        try:
            from cerebro import explicar_ia
            no_por_id = {n["id"]: n for n in g["nodes"]}
            ia = explicar_ia.complementar(slug, expl, [(e, no_por_id[ids_ent[e]]) for e in range(total) if not expl.get(e) and ids_ent[e] in no_por_id],
                                          lambda f: fontes.linhas(f) if f else None)
        except Exception as ex:                                   # a explicação por IA nunca derruba o mapa
            print(f"Aviso: explicações por IA ignoradas ({type(ex).__name__}: {ex}).", file=sys.stderr)

    # ---- nº de itens por grupo, coesão, gods, surpresas ----
    n_itens = Counter(grp)
    for n in rationale_nos:
        n_itens[ordem_grupos[grupo_de_id[n["id"]]]] += 1
    coesao = analise.get("cohesion", {})
    grupos = [{"n": nome_grupo[c], "d": dep_grupo[i], "t": n_itens.get(i, 0),
               "c": round(float(coesao.get(c, 0) or 0), 3)} for i, c in enumerate(com_ids)]
    gods = []
    for gd in analise.get("gods", [])[:10]:
        e = ent_de_id.get(gd["id"])
        if e is not None:
            gods.append({"e": e, "g": gd.get("degree", 0)})
    por_rotulo = defaultdict(list)
    for e in range(nF, total):
        por_rotulo[nome[e]].append(e)
    surpresas = []
    for s in analise.get("surprises", [])[:20]:
        sf = s.get("source_files") or ["", ""]
        surpresas.append({
            "a": s.get("source", ""), "b": s.get("target", ""),
            "fa": sf[0] if sf else "", "fb": sf[1] if len(sf) > 1 else "",
            "rel": s.get("relation", ""), "inf": s.get("confidence") == "INFERRED",
            "por": traduz_porque(s.get("why", "")),
        })
    for s in surpresas:      # índice do item quando o rótulo + arquivo apontam para um só
        for chave, fch in (("ea", "fa"), ("eb", "fb")):
            cand = [e for e in por_rotulo.get(s["a" if chave == "ea" else "b"], [])
                    if arq[e] >= 0 and arquivos[arq[e]] == s[fch]]
            s[chave] = cand[0] if len(cand) == 1 else -1

    hash_g = hashlib.sha1((entrada / "graph.json").read_bytes()).hexdigest()
    n_expl = sum(1 for e in expl if expl[e] and e not in ia)      # só texto do próprio código (o da IA vai à parte)
    dados = {
        "meta": {
            "commit": g.get("built_at_commit", "") or "",
            "ramo": "", "data": "", "hash": hash_g,
            "versaoGraphify": (g.get("graph") or {}).get("graphify_version", ""),
            "totais": {"itens": total - nF, "arquivos": nF, "grupos": nG, "ligacoes": len(ligas),
                       "rationale": len(rationale_nos), "explicados": n_expl, "explicadosIA": len(ia)},
        },
        "deptos": esq.nomes, "cores": esq.cores, "ancoras": esq.ancoras, "tipos": TIPOS, "relacoes": RELACOES,
        "arquivos": arquivos,
        "grupos": grupos,
        "nos": {"n": nome, "a": arq, "l": lin, "k": tipo, "g": grp, "d": dep},
        "expl": {str(k): v for k, v in expl.items() if v},
        "ia": {str(k): v for k, v in ia.items()},      # índice -> 0 explicação automática (IA) atual · 1 desatualizada
        "lig": [x for s, t, r in ligas for x in (s, t, r)],
        "gods": gods, "surpresas": surpresas,
    }
    # estado para a comparação com a próxima geração
    estado = {
        "hash": hash_g, "commit": dados["meta"]["commit"],
        "arquivos": arquivos,
        "grupos": [x["n"] for x in grupos],
        "itens": {ids_ent[e]: [nome[e], arquivos[arq[e]] if arq[e] >= 0 else "", tipo[e]] for e in range(nF, total)},
        "ligs": [f"{ids_ent[s] or arquivos[s]}>{r}>{ids_ent[t] or arquivos[t]}" for s, t, r in ligas],
        "rot": {(ids_ent[e] or arquivos[e]): nome[e] for e in range(total)},
    }
    return dados, estado


# ---------------------------------------------------------------------------------------------------------------
# Histórico (comparação com a geração anterior)
# ---------------------------------------------------------------------------------------------------------------
def amostra(lista, limite=MAX_AMOSTRA):
    return list(lista)[:limite]


def comparar(antigo, novo):
    a_f, n_f = set(antigo["arquivos"]), set(novo["arquivos"])
    a_g, n_g = set(antigo["grupos"]), set(novo["grupos"])
    a_i, n_i = antigo["itens"], novo["itens"]
    ent_i = sorted(set(n_i) - set(a_i))
    sai_i = sorted(set(a_i) - set(n_i))
    a_l, n_l = set(antigo["ligs"]), set(novo["ligs"])
    ent_l = sorted(n_l - a_l)
    sai_l = sorted(a_l - n_l)

    def desc_lig(chave, rot):
        s, r, t = chave.split(">", 2)
        return [rot.get(s, s), RELACOES[int(r) // 2], rot.get(t, t)]

    return {
        "arquivos": {"entrou": amostra(sorted(n_f - a_f)), "saiu": amostra(sorted(a_f - n_f)),
                     "nEntrou": len(n_f - a_f), "nSaiu": len(a_f - n_f)},
        "grupos": {"entrou": amostra(sorted(n_g - a_g)), "saiu": amostra(sorted(a_g - n_g)),
                   "nEntrou": len(n_g - a_g), "nSaiu": len(a_g - n_g)},
        "itens": {"entrou": [n_i[i][:2] for i in amostra(ent_i)], "saiu": [a_i[i][:2] for i in amostra(sai_i)],
                  "nEntrou": len(ent_i), "nSaiu": len(sai_i)},
        "ligacoes": {"entrou": [desc_lig(c, novo["rot"]) for c in amostra(ent_l)],
                     "saiu": [desc_lig(c, antigo["rot"]) for c in amostra(sai_l)],
                     "nEntrou": len(ent_l), "nSaiu": len(sai_l)},
    }


def atualizar_historico(saida, dados, estado, raiz):
    caminho_estado = saida / ".estado.json.gz"
    caminho_hist = saida / "historico.json"
    historico = []
    if caminho_hist.exists():
        try:
            historico = ler_json(caminho_hist)
        except (OSError, ValueError):
            historico = []
    antigo = None
    if caminho_estado.exists():
        try:
            with gzip.open(caminho_estado, "rt", encoding="utf-8") as f:
                antigo = json.load(f)
        except (OSError, ValueError):
            antigo = None
    m = dados["meta"]
    mudou = antigo is None or antigo.get("hash") != estado["hash"]
    if mudou:
        entrada = {
            "id": estado["hash"][:10], "data": m["data"], "commit": m["commit"], "ramo": m["ramo"],
            "totais": {"itens": m["totais"]["itens"], "arquivos": m["totais"]["arquivos"],
                       "grupos": m["totais"]["grupos"], "ligacoes": m["totais"]["ligacoes"]},
            "inicial": antigo is None,
        }
        if antigo is not None:
            entrada["mudancas"] = comparar(antigo, estado)
        historico.insert(0, entrada)
        historico = historico[:MAX_HISTORICO]
        tmp = caminho_estado.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(estado, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, caminho_estado)
    return historico, mudou


# ---------------------------------------------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------------------------------------------
def escrever_atomico(destino, texto):
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(tmp, destino)


def esperar_grafo(entrada, limite=900):
    """Espera o graph.json ficar mais novo que o momento do disparo e parar de ser escrito."""
    t0 = time.time()
    alvo = entrada / "graph.json"
    print(f"Esperando {alvo} ficar mais novo que agora (até {limite // 60} min)…", flush=True)
    while time.time() - t0 < limite:
        try:
            if alvo.stat().st_mtime > t0:
                tam, ate = -1, time.time() + 4
                while time.time() < ate:          # espera o tamanho parar de mudar
                    t = alvo.stat().st_size
                    if t != tam:
                        tam, ate = t, time.time() + 3
                    time.sleep(0.5)
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser(description="Gera o mapa do Cérebro do Projeto a partir do mapa do Graphify.")
    ap.add_argument("--projeto", default=None, help="pasta do projeto; lê <projeto>/graphify-out")
    ap.add_argument("--entrada", default=None, help="pasta graphify-out com graph.json e afins (padrão: <projeto>/graphify-out)")
    ap.add_argument("--saida", default=None, help="pasta de saída (padrão: ~/.cerebro/projetos/<slug>/mapa)")
    ap.add_argument("--raiz", default=None, help="raiz do projeto, para ler os cabeçalhos dos arquivos")
    ap.add_argument("--esperar", action="store_true",
                    help="espera o graph.json ficar mais novo que o disparo (até 15 min) e então gera")
    ap.add_argument("--standalone", action="store_true",
                    help="copia index.html, cerebro.css e cerebro.js para a saída (abre por file://, sem servidor)")
    a = ap.parse_args()
    if not a.projeto and not a.entrada:
        ap.error("informe --projeto <pasta do projeto> (ou --entrada <pasta graphify-out>)")
    projeto = Path(a.projeto).resolve() if a.projeto else None
    entrada = Path(a.entrada) if a.entrada else projeto / "graphify-out"
    raiz = a.raiz or (str(projeto) if projeto else None)
    if not raiz:
        marca = entrada / ".graphify_root"
        raiz = marca.read_text(encoding="utf-8").strip() if marca.exists() else str(entrada.parent)
    slug = slug_do_projeto(projeto or raiz)
    saida = Path(a.saida) if a.saida else CASA / "projetos" / slug / "mapa"
    if not a.esperar and not (entrada / "graph.json").exists():
        print(f"Não achei {entrada / 'graph.json'}: este projeto ainda não tem o mapa do Graphify.", file=sys.stderr)
        return 2
    if a.esperar and not esperar_grafo(entrada):
        print("O graph.json não ficou mais novo em 15 minutos; nada gerado.")
        return 0
    t0 = time.time()
    dados, estado = processar(entrada, raiz, slug)
    m = dados["meta"]
    m["ramo"] = git(raiz, "branch", "--show-current")
    m["projeto"] = {"slug": slug, "pasta": str(raiz), "nome": Path(raiz).name}
    m["data"] = datetime.datetime.fromtimestamp((entrada / "graph.json").stat().st_mtime).astimezone().isoformat(timespec="seconds")
    saida.mkdir(parents=True, exist_ok=True)
    historico, mudou = atualizar_historico(saida, dados, estado, raiz)
    dados["historico"] = historico
    dados["config"] = ler_config(slug)
    dados["meta"]["geradoEm"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    escrever_atomico(saida / "dados.js", "window.CEREBRO = " + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + ";\n")
    escrever_atomico(saida / "historico.json", json.dumps(historico, ensure_ascii=False, indent=1) + "\n")
    if a.standalone:
        for nome_arq in ESTATICOS:
            shutil.copyfile(AQUI / nome_arq, saida / (nome_arq + ".tmp"))
            os.replace(saida / (nome_arq + ".tmp"), saida / nome_arq)
    t = m["totais"]
    print(f"Mapa gerado em {time.time() - t0:.1f}s: {t['grupos']} grupos, {t['arquivos']} arquivos, {t['itens']} itens, "
          f"{t['ligacoes']} ligações, {t['explicados']} com explicação. Histórico: {len(historico)} entradas"
          f"{' (nova)' if mudou else ' (mapa igual ao anterior)'}.")
    print(f"Saída: {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
