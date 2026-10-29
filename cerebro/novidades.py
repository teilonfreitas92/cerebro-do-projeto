"""Vigia de novidades (SOB DEMANDA): ferramentas e técnicas novas que podem melhorar o projeto.

Só consulta páginas PÚBLICAS de releases (API pública do GitHub), com GET, sem login e sem mandar nada do projeto: a única
coisa que sai do PC é o pedido "qual é a última versão de <dono>/<repositório>". A lista de fontes é local e curada
(config.json > fontes_novidades); só aceita repositórios no formato dono/nome e só fala com api.github.com por HTTPS.
Compara com a última versão que a pessoa marcou como vista e mostra "novo desde a última vez"; versão nova de uma
ferramenta que já está instalada vira PROPOSTA de atualização (nada é instalado sozinho). Sem rede ou erro da API:
mostra o aviso e segue, sem quebrar.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import armazem, config, ferramentas, propostas
from .segredos import encurtar

HOSTS_PERMITIDOS = {"api.github.com"}
REPO = re.compile(r"^[A-Za-z0-9_.\-]{1,100}/[A-Za-z0-9_.\-]{1,100}$")
LIMITE_RESPOSTA = 400_000
USER_AGENT = "cerebro-do-projeto (leitura de releases publicas)"


def _arquivo():
    config.garantir_casa()
    return config.CASA / "novidades.json"


def url_permitida(url):
    p = urllib.parse.urlparse(url)
    return p.scheme == "https" and (p.hostname or "").lower() in HOSTS_PERMITIDOS and not p.username and not p.password


def buscar_json(url, timeout=8):
    """GET simples de uma URL permitida. Devolve (status, objeto). Levanta OSError em falha de rede."""
    if not url_permitida(url):
        raise ValueError("endereço não permitido")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not url_permitida(r.geturl()):
                raise ValueError("redirecionamento para endereço não permitido")
            corpo = r.read(LIMITE_RESPOSTA + 1)
            if len(corpo) > LIMITE_RESPOSTA:
                raise ValueError("resposta grande demais")
            return r.status, json.loads(corpo.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None


def _numeros(v):
    m = re.search(r"\d+(?:\.\d+)+", v or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def comparar_versao(instalada, ultima):
    """'atualizada' | 'desatualizada' | '' (não deu para comparar)."""
    a, b = _numeros(instalada), _numeros(ultima)
    if not a or not b:
        return ""
    return "desatualizada" if a < b else "atualizada"


def fontes_validas(cfg):
    saida = []
    for f in cfg.get("fontes_novidades") or []:
        if isinstance(f, dict) and re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,40}", str(f.get("id", ""))) and REPO.match(str(f.get("repo", ""))):
            saida.append({"id": f["id"], "nome": str(f.get("nome") or f["id"])[:60], "repo": f["repo"], "tipo": str(f.get("tipo") or "")[:20],
                          "o_que": str(f.get("o_que") or "")[:200], "ferramenta": str(f.get("ferramenta") or "")})
    return saida


def _ultima_versao(repo, buscar):
    """(tag, nome, publicado, url, resumo) da última release; se o repositório não usa releases, a última tag."""
    status, d = buscar(f"https://api.github.com/repos/{repo}/releases/latest")
    if status == 200 and isinstance(d, dict) and d.get("tag_name"):
        url = str(d.get("html_url") or "")
        if not url.startswith("https://github.com/"):
            url = f"https://github.com/{repo}/releases"
        corpo = re.sub(r"\s+", " ", re.sub(r"[#*`>\[\]]", "", str(d.get("body") or ""))).strip()
        return {"tag": str(d["tag_name"])[:60], "nome": encurtar(str(d.get("name") or d["tag_name"]), 80), "publicado": str(d.get("published_at") or "")[:25],
                "url": url, "resumo": encurtar(corpo, 280)}
    if status in (404, 200):
        status2, d2 = buscar(f"https://api.github.com/repos/{repo}/tags?per_page=1")
        if status2 == 200 and isinstance(d2, list) and d2 and isinstance(d2[0], dict) and d2[0].get("name"):
            return {"tag": str(d2[0]["name"])[:60], "nome": str(d2[0]["name"])[:60], "publicado": "", "url": f"https://github.com/{repo}/tags", "resumo": ""}
        raise LookupError("sem releases nem tags públicas")
    if status == 403:
        raise LookupError("limite de consultas da API pública atingido; tente mais tarde")
    raise LookupError(f"resposta {status}")


def estado():
    return armazem.ler_json(_arquivo(), {"v": 1, "fontes": {}, "ultima_busca": None, "erro": ""})


def procurar(cfg, buscar=None, agora=None):
    """Consulta as fontes e atualiza novidades.json. Devolve o estado completo + 'novas' (propostas criadas agora)."""
    buscar = buscar or buscar_json
    agora = agora or time.time()
    fontes = fontes_validas(cfg)
    erros, achados = [], {}
    for f in fontes:
        try:
            achados[f["id"]] = _ultima_versao(f["repo"], buscar)
        except (OSError, ValueError, LookupError) as e:
            erros.append(f"{f['nome']}: {e}")
        except Exception as e:                       # resposta estranha da API não pode derrubar o painel
            erros.append(f"{f['nome']}: resposta inesperada ({type(e).__name__})")
    sem_rede = bool(fontes) and not achados and bool(erros)

    instaladas = {}
    try:
        for d in ferramentas.detectar(str(config.CASA)):
            instaladas[d["id"]] = d
        v = ferramentas.versao_graphify()
        instaladas["graphify"] = {"id": "graphify", "instalada": bool(v), "versao": v, "nome": "Graphify"}
    except Exception:
        pass

    novas_props = []

    def mudar(d):
        d["ultima_busca"] = agora
        d["erro"] = "; ".join(erros)[:600]
        d["sem_rede"] = sem_rede
        d["fontes_ids"] = [f["id"] for f in fontes]
        for f in fontes:
            v = achados.get(f["id"])
            if v is None:
                continue
            e = d["fontes"].setdefault(f["id"], {})
            e.update(nome=f["nome"], repo=f["repo"], tipo=f["tipo"], o_que=f["o_que"], ferramenta=f["ferramenta"], ultima=v, consultada_em=agora)
            if not e.get("visto_tag"):                       # primeira vez: é o ponto de partida, não novidade
                e["visto_tag"], e["visto_em"] = v["tag"], agora
            ferr = instaladas.get(f["ferramenta"]) if f["ferramenta"] else None
            if ferr and ferr["instalada"]:
                e["instalada"] = ferr["versao"]
                e["situacao"] = comparar_versao(ferr["versao"], v["tag"])
                if e["situacao"] == "desatualizada":
                    novas_props.append(propostas.proposta(
                        "novidade", f"atualizar|{f['id']}|{v['tag']}", f"Atualizar {f['nome']} para {v['tag']}",
                        f"Instalada: {ferr['versao']}. Última versão pública: {v['tag']}" + (f" ({v['publicado'][:10]})" if v["publicado"] else "")
                        + ". Atualizar traz correções; precisa da sua aprovação para instalar.", "P", "baixo", "ferramentas"))
            else:
                e.pop("instalada", None)
                e.pop("situacao", None)
            if e["visto_tag"] != v["tag"] and f["tipo"] == "plataforma":
                novas_props.append(propostas.proposta(
                    "novidade", f"novo|{f['id']}|{v['tag']}", f"{f['nome']} lançou {v['tag']}",
                    (v["resumo"] + " " if v["resumo"] else "") + f"Ler as novidades e ver se algo ajuda o projeto: {v['url']}", "P", "baixo", "plataforma"))
        return d

    armazem.atualizar_json(_arquivo(), {"v": 1, "fontes": {}, "ultima_busca": None, "erro": ""}, mudar)
    criadas = propostas.sincronizar(propostas.ESCOPO_CEREBRO, novas_props, agora, obsoletar=False) if novas_props else []
    return {**montar(cfg), "novas": criadas, "erros": erros, "sem_rede": sem_rede}


def marcar_visto(fonte_id=None):
    """Marca a versão atual como vista (some o 'novo desde a última vez'). Sem id = todas."""
    def mudar(d):
        for fid, e in d["fontes"].items():
            if fonte_id in (None, "", fid) and e.get("ultima"):
                e["visto_tag"], e["visto_em"] = e["ultima"]["tag"], time.time()
        return d

    armazem.atualizar_json(_arquivo(), {"v": 1, "fontes": {}, "ultima_busca": None, "erro": ""}, mudar)


def montar(cfg):
    """O que a aba Novidades mostra (sem consultar a rede)."""
    d = estado()
    ativas = set(d.get("fontes_ids") or [f["id"] for f in fontes_validas(cfg)])
    itens = []
    for f in fontes_validas(cfg):
        e = (d.get("fontes") or {}).get(f["id"]) or {}
        v = e.get("ultima")
        itens.append({"id": f["id"], "nome": f["nome"], "repo": f["repo"], "tipo": f["tipo"], "o_que": f["o_que"],
                      "ultima": v, "visto_tag": e.get("visto_tag"), "novo": bool(v and e.get("visto_tag") and e["visto_tag"] != v["tag"]),
                      "instalada": e.get("instalada"), "situacao": e.get("situacao"), "consultada_em": e.get("consultada_em")})
    intervalo = int((cfg.get("rotinas") or {}).get("vigia_novidades_dias") or 3)
    ultima = d.get("ultima_busca")
    return {"fontes": itens, "ultima_busca": ultima, "erro": d.get("erro", ""), "sem_rede": bool(d.get("sem_rede")),
            "proxima_em": (ultima + intervalo * 86400) if ultima else None, "intervalo_dias": intervalo,
            "automatica": bool((cfg.get("rotinas") or {}).get("novidades_automatica")),
            "propostas": [p for p in propostas.listar(propostas.ESCOPO_CEREBRO) if p.get("origem") == "novidade"], "ativas": sorted(ativas)}
