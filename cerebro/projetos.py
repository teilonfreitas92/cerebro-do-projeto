"""Descoberta dos projetos e informações de git (somente leitura).

Os projetos vêm de ~/.claude/projects (uma pasta por projeto, com o caminho "achatado" no nome) mais os
`projetos_extra` do config.json. O caminho real é lido do campo `cwd` dentro das transcrições e conferido contra o nome
da pasta; se não der, o nome é decodificado procurando as pastas que existem de verdade.
"""
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import config
from .segredos import encurtar

# Pastas do Claude Code que NÃO são projetos
IGNORAR_NOME = ("--claude-worktrees-", "AppData-Local-Temp", "scratch-workspaces")
HOME = Path.home()
_cache_projetos = {"t": 0.0, "v": None}
_trava = threading.Lock()
_git_cache = {}


def codificar(caminho):
    """Como o Claude Code nomeia a pasta: tudo que não é letra ou dígito vira '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(caminho))


def eh_proibido(*textos, cfg=None):
    """Projeto que a pessoa mandou NUNCA entrar no painel (config.json > "nunca_entrar": pedaços de nome ou caminho)."""
    cfg = cfg if cfg is not None else config.ler_config()
    nunca = [str(x).lower() for x in (cfg.get("nunca_entrar") or []) if str(x).strip()]
    return any(n in (t or "").lower() for n in nunca for t in textos)


def _ler_cwd_do_arquivo(arq, limite_linhas=80):
    padrao = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
    try:
        with open(arq, "rb") as f:
            for i, linha in enumerate(f):
                if i >= limite_linhas:
                    break
                m = padrao.search(linha[:20000].decode("utf-8", "replace"))
                if m:
                    return m.group(1).replace("\\\\", "\\")
    except OSError:
        pass
    return ""


def decodificar_pelo_disco(nome):
    """'C--Users-ana-Projetos-loja' -> a pasta real, procurando entre as pastas que existem aquela cujo nome "achatado"
    (tudo que não é letra/dígito vira '-') casa com o começo do que sobrou. Devolve '' se não achar.
    No Linux e no Mac o caminho começa em '/', então o nome começa com '-' ('-home-ana-loja' -> /home/ana/loja)."""
    m = re.match(r"^([A-Za-z])--(.*)$", nome)
    if m:
        raiz, resto = Path(m.group(1).upper() + ":\\"), m.group(2)
    elif nome.startswith("-") and len(nome) > 1:
        raiz, resto = Path("/"), nome[1:]
    else:
        return ""

    def procurar(atual, resto):
        if not resto:
            return atual
        try:
            filhos = [f.name for f in os.scandir(atual) if f.is_dir()]
        except OSError:
            return None
        for f in sorted(filhos, key=len, reverse=True):
            enc = codificar(f).lower()
            if resto.lower() == enc or resto.lower().startswith(enc + "-"):
                r = procurar(atual / f, resto[len(enc) + 1:])
                if r:
                    return r
        return None

    r = procurar(raiz, resto)
    return str(r) if r else ""


def caminho_real(pasta_claude):
    """Caminho real do projeto a partir da pasta em ~/.claude/projects. '' se não existir mais."""
    nome = pasta_claude.name
    candidatos = []
    try:
        arquivos = sorted((f for f in os.scandir(pasta_claude) if f.name.endswith(".jsonl")),
                          key=lambda f: f.stat().st_mtime, reverse=True)[:4]
    except OSError:
        arquivos = []
    for f in arquivos:
        cwd = _ler_cwd_do_arquivo(f.path)
        if cwd:
            candidatos.append(cwd)
    for c in candidatos:
        if codificar(c) == nome and Path(c).is_dir():
            return c
    d = decodificar_pelo_disco(nome)
    return d if d and Path(d).is_dir() else ""


def _ignorado(nome, caminho):
    if any(p in nome for p in IGNORAR_NOME):
        return True
    if eh_proibido(nome, caminho):
        return True
    try:
        if Path(caminho).resolve() == HOME.resolve():           # a pasta do usuário inteira não é um projeto
            return True
    except OSError:
        return True
    if "scratch" in caminho.lower() and "appdata" in caminho.lower():
        return True
    return False


def descobrir(forcar=False):
    """Lista de projetos: [{slug, nome, caminho, claude_dir, extra, oculto}], ordenada por nome."""
    with _trava:
        if not forcar and _cache_projetos["v"] is not None and time.time() - _cache_projetos["t"] < 10:
            return _cache_projetos["v"]
        cfg = config.ler_config()
        achados = {}
        try:
            pastas = sorted(f for f in config.PROJETOS_CLAUDE.iterdir() if f.is_dir())
        except OSError:
            pastas = []
        for pasta in pastas:
            if any(p in pasta.name for p in IGNORAR_NOME) or eh_proibido(pasta.name, cfg=cfg):
                continue
            caminho = caminho_real(pasta)
            if not caminho or _ignorado(pasta.name, caminho):
                continue
            achados[pasta.name] = {"slug": pasta.name, "nome": Path(caminho).name, "caminho": caminho,
                                   "claude_dir": str(pasta), "extra": False}
        # os extras do config entram mesmo sem sessões no Claude Code
        extras = list(cfg.get("projetos_extra") or [])
        for e in extras:
            try:
                if not e or not Path(e).is_dir() or eh_proibido(e, cfg=cfg):
                    continue
            except OSError:
                continue
            slug = codificar(Path(e).resolve())
            if slug in achados or _ignorado(slug, e):
                continue
            achados[slug] = {"slug": slug, "nome": Path(e).name, "caminho": str(Path(e).resolve()),
                             "claude_dir": str(config.PROJETOS_CLAUDE / slug), "extra": True}
        ocultos = set(cfg.get("ocultos") or [])
        for p in achados.values():
            p["oculto"] = p["slug"] in ocultos
        lista = sorted(achados.values(), key=lambda p: p["nome"].lower())
        _cache_projetos.update(t=time.time(), v=lista)
        return lista


def achar(slug):
    for p in descobrir():
        if p["slug"] == slug:
            return p
    return None


def adicionar_extra(caminho):
    """Registra uma pasta como projeto. Recusa pastas que não existem e as de "nunca_entrar"."""
    p = Path(caminho)
    if not p.is_dir():
        raise ValueError("a pasta não existe")
    if eh_proibido(str(p)):
        raise ValueError("este projeto não pode ser incluído")
    real = str(p.resolve())
    config.atualizar_config(lambda c: c["projetos_extra"].append(real) if real not in c["projetos_extra"] else None)
    descobrir(forcar=True)
    return codificar(real)


# ---------------------------------------------------------------------------------------------------------------
# git, só leitura
# ---------------------------------------------------------------------------------------------------------------
def _git(pasta, *args):
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(pasta), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def info_git(pasta):
    """Ramo e último commit. Cache de 30 s para o painel geral não chamar o git a cada atualização."""
    agora = time.time()
    c = _git_cache.get(pasta)
    if c and agora - c[0] < 30:
        return c[1]
    ramo = _git(pasta, "rev-parse", "--abbrev-ref", "HEAD")
    ultimo = _git(pasta, "log", "-1", "--format=%h%x1f%s%x1f%cI")
    info = {"repositorio": bool(ramo), "ramo": ramo, "commit": "", "assunto": "", "quando": ""}
    if ultimo:
        partes = ultimo.split("\x1f")
        if len(partes) == 3:
            info.update(commit=partes[0], assunto=encurtar(partes[1], 200), quando=partes[2])
    _git_cache[pasta] = (agora, info)
    return info


def _epoch(iso):
    import datetime
    try:
        return datetime.datetime.fromisoformat(iso).timestamp()
    except (ValueError, TypeError):
        return None


TOLERANCIA_COMMIT = 180      # o Graphify refaz o mapa DEPOIS do commit; só avisa se passar disto


def estado_mapa(caminho_projeto, slug):
    """O projeto tem mapa do Graphify? A página do mapa já foi gerada pelo Cérebro? Está em dia com o último commit?"""
    graphify = Path(caminho_projeto) / "graphify-out"
    dados = config.CASA / "projetos" / slug / "mapa" / "dados.js"
    d = {"graphify": (graphify / "graph.json").is_file(), "gerado": dados.is_file(), "graph_em": None, "gerado_em": None,
         "commit_em": None, "defasado": False, "pagina_defasada": False}
    try:
        if d["graphify"]:
            d["graph_em"] = (graphify / "graph.json").stat().st_mtime
        if d["gerado"]:
            d["gerado_em"] = dados.stat().st_mtime
    except OSError:
        pass
    if d["graphify"]:
        d["commit_em"] = _epoch(info_git(caminho_projeto).get("quando"))
        if d["graph_em"] and d["commit_em"]:
            d["defasado"] = d["graph_em"] < d["commit_em"] - TOLERANCIA_COMMIT      # mapa mais velho que o último commit
        if d["graph_em"] and d["gerado_em"]:
            d["pagina_defasada"] = d["graph_em"] > d["gerado_em"] + 1               # o Graphify já refez; falta refazer a página
    return d
