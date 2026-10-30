"""Servidor do Cérebro: aiohttp em 127.0.0.1 (NUNCA em outro endereço), com token + cookie + checagem de Host/Origin.

Proteção:
  * Escuta só em 127.0.0.1.
  * Host precisa ser 127.0.0.1:<porta> ou localhost:<porta> (anti DNS-rebinding).
  * A página é aberta por http://127.0.0.1:<porta>/?t=<token>; o servidor confere o token, troca por um cookie
    HttpOnly + SameSite=Strict (o cookie guarda um HMAC do token, não o token) e redireciona para /, tirando o token da URL.
  * Toda rota (menos /api/saude) exige o cookie. Requisições que não são GET exigem Origin da própria página e JSON.
  * Sem telemetria: nada sai do PC.
"""
import asyncio
import hmac
import json
import os
import re
import sys
import time
from pathlib import Path

from aiohttp import web

from . import (__version__, agentes, bastao, config, custos, ferramentas, ganchos_eventos, indice, mapa_auto, memoria, painel,
               projetos, propostas, regras_agentes, revisoes, rotas_ganchos, rotas_memoria, rotinas, titulos, transcricao)
from . import rotas_encaixe
from .rotas_gestor import (api_agentes_previa, api_agentes_previa_gerar, api_analise, api_analise_rodar, api_conferir, api_conferir_marcar,
                           api_decisao_nova, api_decisoes, api_departamentos, api_departamentos_salvar, api_ferramenta_execucoes,
                           api_ferramenta_rodar, api_ferramenta_saida, api_ferramentas, api_comando_aprovar, api_comando_remover, api_comandos_sugeridos, api_inventario, api_novidades,
                           api_novidades_procurar, api_novidades_visto, api_proposta, api_tarefa)
from . import rotas_backup, rotas_tarefas, tarefas_gestor
from .rotas_explicar import api_explicar, api_explicar_estado, api_explicar_parar, api_explicar_rodar
from .segredos import mascarar
from .web_util import (K_CACHE, K_COOKIE, K_ESTADO, K_PARAR, K_PORTA, K_TOKEN, SLUG, _cache_curto, _erro, _json,
                       _projeto_ou_404)

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
MAPA = RAIZ / "mapa"
COOKIE = "cerebro_sessao"


def nome_cookie(porta):
    """Um nome por porta: o navegador não separa cookies de 127.0.0.1 por porta, e dois Cérebros abertos (ex.: o seu e a
    demonstração) derrubavam a sessão um do outro."""
    return f"{COOKIE}_{porta}"
ID_SESSAO = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REL_ARQUIVO = re.compile(r"^[A-Za-z0-9_.\-]{1,120}\.jsonl$|^[A-Za-z0-9_.\-]{1,120}/subagents/agent-[A-Za-z0-9_\-]{1,80}\.jsonl$"
                         r"|^ia/[A-Za-z0-9_.\-]{1,120}/agent-ia-[A-Za-z0-9_\-]{1,80}\.jsonl$")


def _iguais(a, b):
    """Comparação em tempo constante, em BYTES (hmac.compare_digest com texto não-ASCII levanta TypeError -> 500)."""
    return hmac.compare_digest(str(a).encode("utf-8", "replace"), str(b).encode("utf-8", "replace"))


def rel_valido(rel):
    """Caminho relativo de um transcrito: só os dois formatos conhecidos e nenhum componente '.' ou '..'."""
    return bool(REL_ARQUIVO.match(rel or "")) and not any(parte in ("", ".", "..") or set(parte) == {"."} for parte in rel.split("/"))


ESTATICOS_WEB = {"app.js": "text/javascript", "ui.js": "text/javascript", "abas.js": "text/javascript", "abas2.js": "text/javascript",
                 "guia.js": "text/javascript", "bemvindo.js": "text/javascript", "backup.js": "text/javascript", "memoria.js": "text/javascript",
                 "ganchos.js": "text/javascript", "encaixe.js": "text/javascript", "explicar.js": "text/javascript",
                 "estilo.css": "text/css", "tokens.css": "text/css", "logo.svg": "image/svg+xml"}
ESTATICOS_MAPA = {"cerebro.css": "text/css", "cerebro.js": "text/javascript"}
ESTATICOS_WEB.update({"tarefas.js": "text/javascript", "tarefas.css": "text/css"})      # tarefas para o gestor e orçamento
ESTATICOS_MAPA["tarefa.js"] = "text/javascript"               # botão "Criar tarefa aqui" do mapa
ESTATICOS_WEB["ias.js"] = "text/javascript"                   # Configurações › Outras IAs
ESTATICOS_WEB["gestora.js"] = "text/javascript"              # corrente da gestora, capítulos e manual do gestor
ESTATICOS_WEB["painel.js"] = "text/javascript"               # layout de painel: barra lateral, gaveta, abas internas, paginação


def hosts_validos(porta):
    return {f"127.0.0.1:{porta}", f"localhost:{porta}"}


def origens_validas(porta):
    return {f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"}


# ---------------------------------------------------------------------------------------------------------------
# Segurança
# ---------------------------------------------------------------------------------------------------------------
@web.middleware
async def seguranca(request, handler):
    app = request.app
    porta = app[K_PORTA]
    if request.path == ganchos_eventos.ROTA:          # receptor dos ganchos do Claude Code: regras próprias (ver rotas_ganchos.portao)
        return await rotas_ganchos.portao(request, handler)
    if request.headers.get("Host", "").lower() not in hosts_validos(porta):
        return web.Response(status=421, text="Host não permitido")
    origem = request.headers.get("Origin")
    if origem is not None and origem not in origens_validas(porta):
        return web.Response(status=403, text="Origem não permitida")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return web.Response(status=403, text="Requisição de outro site")
    if request.method not in ("GET", "HEAD"):
        if origem is None:
            return web.Response(status=403, text="Origem obrigatória")
        if "application/json" not in request.headers.get("Content-Type", ""):
            return web.Response(status=415, text="Use JSON")

    caminho = request.path
    if caminho == "/api/saude":
        return await handler(request)
    # entrada pelo link com token: troca por cookie e limpa a URL
    if caminho == "/" and "t" in request.query:
        if _iguais(request.query.get("t", ""), app[K_TOKEN]):
            resp = web.Response(status=302, headers={"Location": "/", "Cache-Control": "no-store"})
            resp.set_cookie(nome_cookie(app[K_PORTA]), app[K_COOKIE], httponly=True, samesite="Strict", path="/", max_age=60 * 60 * 24 * 30)
            return resp
        return web.Response(status=401, text=_PAGINA_NEGADA, content_type="text/html", charset="utf-8")
    enviado = request.cookies.get(nome_cookie(app[K_PORTA]), "")
    if not enviado or not _iguais(enviado, app[K_COOKIE]):
        if caminho.startswith("/api/"):
            return _erro("não autorizado", 401)
        return web.Response(status=401, text=_PAGINA_NEGADA, content_type="text/html", charset="utf-8")
    resp = await handler(request)
    if getattr(resp, "prepared", False):         # fluxo SSE já enviado: os cabeçalhos de segurança foram em _preparar_sse
        return resp
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
                                               "base-uri 'none'; form-action 'none'")
    return resp


_PAGINA_NEGADA = ("<!doctype html><meta charset=utf-8><title>Cérebro do Projeto</title>"
                  "<body style='font:16px system-ui;background:#0b0e14;color:#e8edf5;padding:48px'>"
                  "<h1>Cérebro do Projeto</h1><p>Esta página só abre pelo atalho do Cérebro "
                  "(<code>abrir_cerebro.py</code>), que inclui a chave de acesso no link.</p>")


# ---------------------------------------------------------------------------------------------------------------
# Estáticos e página
# ---------------------------------------------------------------------------------------------------------------
async def pagina(request):
    return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


async def estatico(request):
    nome = request.match_info["nome"]
    tipo = ESTATICOS_WEB.get(nome)
    if not tipo or not (WEB / nome).is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(WEB / nome, headers={"Cache-Control": "no-cache", "Content-Type": tipo + "; charset=utf-8"})


async def saude(request):
    return _json({"cerebro": True, "versao": __version__})


async def ping(request):
    request.app[K_ESTADO]["ultimo_ping"] = time.time()
    return _json({"ok": True, "versao": __version__})


# ---------------------------------------------------------------------------------------------------------------
# Projetos
# ---------------------------------------------------------------------------------------------------------------
def _cartao(p, cfg):
    slug = p["slug"]
    arquivos = indice.listar_arquivos(slug)
    sessoes = [a for a in arquivos if a["tipo"] == "sessao"]
    ultimo = max([a["mtime"] for a in arquivos], default=0)
    semana = time.time() - 7 * 86400
    recentes = sum(1 for a in sessoes if a["mtime"] >= semana)
    c = custos.hoje_e_semana(slug, cfg["precos"])
    ges = (cfg.get("gestoras") or {}).get(slug) or {}
    pend = indice.pendentes(slug, time.time() - 8 * 86400)
    return {
        "conferir": revisoes.contagem(slug, cfg), "propostas": propostas.contagem(slug),
        "tarefas": tarefas_gestor.contagem(slug),
        "slug": slug, "nome": p["nome"], "caminho": p["caminho"], "oculto": p["oculto"], "extra": p["extra"],
        "git": projetos.info_git(p["caminho"]), "sessoes_total": len(sessoes), "sessoes_recentes": recentes,
        "agentes_ativos": agentes.contar_ativos(slug), "ultima_atividade": ultimo or None,
        "hoje": {"tokens": custos.total_tokens(c["hoje"]), "custo": c["hoje"]["custo"], "sem_preco": c["hoje"]["sem_preco"]},
        "semana": {"tokens": custos.total_tokens(c["semana"]), "custo": c["semana"]["custo"], "sem_preco": c["semana"]["sem_preco"]},
        "mapa": projetos.estado_mapa(p["caminho"], slug), "gestora": ges.get("nome") or "", "indexando": pend > 0,
    }


async def api_projetos(request):
    cfg = config.ler_config()
    mostrar_ocultos = request.query.get("ocultos") == "1"
    lista = [p for p in projetos.descobrir() if mostrar_ocultos or not p["oculto"]]

    def calcular():
        saida = []
        for p in lista:
            if indice.pendentes(p["slug"], time.time() - 8 * 86400):
                indice.indexar_em_segundo_plano(p["slug"], time.time() - 8 * 86400)
            saida.append(_cartao(p, cfg))
        return saida

    cartoes = await asyncio.to_thread(_cache_curto, request.app, ("hub", mostrar_ocultos, json.dumps(cfg["precos"], sort_keys=True)), 5, calcular)
    return _json({"projetos": cartoes, "limites": painel.limites(), "tema": cfg["tema"], "primeiro_uso_concluido": bool(cfg.get("primeiro_uso_concluido"))})


async def api_fila(request):
    cfg = config.ler_config()
    itens = await asyncio.to_thread(_cache_curto, request.app, ("fila",), 10, lambda: painel.fila(cfg))
    return _json({"itens": itens})


async def api_visao(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    slug = p["slug"]
    if indice.pendentes(slug):
        indice.indexar_em_segundo_plano(slug)

    def calcular():
        arquivos = indice.listar_arquivos(slug)
        sessoes = [a for a in arquivos if a["tipo"] == "sessao"]
        c = custos.hoje_e_semana(slug, cfg["precos"])
        total = custos.agregar(slug, cfg["precos"])["total"]
        mem = memoria.listar(slug, p["caminho"])
        ges = (cfg.get("gestoras") or {}).get(slug) or {}
        recentes = []
        for a in sorted(arquivos, key=lambda x: -x["mtime"])[:12]:
            ind = indice.indice_se_existe(slug, a["rel"]) or {}
            meta = indice.ler_meta(slug, a)
            if a["tipo"] == "sessao":
                titulo = indice.titulo_sessao(slug, a["id"], cfg, ind)["titulo"]
            else:
                titulo = str(meta.get("description") or ind.get("primeira") or "(subagente)")
            recentes.append({"tipo": a["tipo"], "id": a["id"], "rel": a["rel"], "titulo": titulo, "mtime": a["mtime"],
                             "modelo": (max(ind["modelos"], key=ind["modelos"].get) if ind.get("modelos") else str(meta.get("model") or ""))})
        return {
            "projeto": {"slug": slug, "nome": p["nome"], "caminho": p["caminho"]},
            "git": projetos.info_git(p["caminho"]), "gestora": ges,
            "numeros": {"sessoes": len(sessoes), "subagentes": len(arquivos) - len(sessoes),
                        "agentes_ativos": agentes.contar_ativos(slug), "memorias": sum(1 for i in mem["itens"] if i["origem"] == "memoria"),
                        "contexto_fixo_tokens": mem["contexto_fixo"]["total_tokens"]},
            "hoje": c["hoje"], "semana": c["semana"], "total": total, "recentes": recentes,
            "conferir": revisoes.contagem(slug, cfg), "propostas": propostas.contagem(slug),
            "tarefas": tarefas_gestor.contagem(slug),
            "mapa": projetos.estado_mapa(p["caminho"], slug), "avisos": mem["avisos"],
            "indexando": indice.estado(slug).progresso["rodando"] or indice.pendentes(slug) > 0,
        }

    return _json(await asyncio.to_thread(calcular))


# ---------------------------------------------------------------------------------------------------------------
# Agentes ao vivo (lista e passo a passo por SSE)
# ---------------------------------------------------------------------------------------------------------------
async def api_agentes(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    ges = ((cfg.get("gestoras") or {}).get(p["slug"]) or {}).get("conversa", "")
    todas = request.query.get("todas") == "1"
    dados = await asyncio.to_thread(agentes.montar, p["slug"], cfg["precos"], ges, 24, todas, cfg)
    return _json(dados)


async def _preparar_sse(request):
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store",
                                       "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff",
                                       "Referrer-Policy": "no-referrer"})
    await resp.prepare(request)
    return resp


async def _enviar(resp, dados):
    await resp.write(("data: " + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode("utf-8"))


async def sse_lista(request):
    """Empurra a árvore de agentes quando ela muda (confere a cada 3 s enquanto a aba está aberta)."""
    p = _projeto_ou_404(request)
    app = request.app
    resp = await _preparar_sse(request)
    app[K_ESTADO]["sse_ativos"] += 1
    ultimo, ultimo_envio = "", 0.0
    try:
        while True:
            cfg = config.ler_config()
            ges = ((cfg.get("gestoras") or {}).get(p["slug"]) or {}).get("conversa", "")
            todas = request.query.get("todas") == "1"
            dados = await asyncio.to_thread(agentes.montar, p["slug"], cfg["precos"], ges, 24, todas, cfg)
            corpo = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
            if corpo != ultimo:
                await resp.write(("data: " + corpo + "\n\n").encode("utf-8"))
                ultimo, ultimo_envio = corpo, time.time()
            elif time.time() - ultimo_envio > 15:
                await resp.write(b": ping\n\n")
                ultimo_envio = time.time()
            app[K_ESTADO]["ultimo_ping"] = time.time()
            await ganchos_eventos.esperar_novidade(3)      # acorda na hora quando chega evento dos ganchos
    except (ConnectionResetError, asyncio.CancelledError, ConnectionError):
        pass
    finally:
        app[K_ESTADO]["sse_ativos"] -= 1
    return resp


async def sse_passos(request):
    """Passo a passo de UM agente: primeiro o final do arquivo, depois só o que for escrito (posição em bytes)."""
    p = _projeto_ou_404(request)
    rel = request.query.get("arquivo", "")
    if not rel_valido(rel):
        return _erro("arquivo inválido")
    caminho = indice.caminho_arquivo(p["slug"], rel)
    if not caminho.is_file():
        return _erro("arquivo não encontrado", 404)
    app = request.app
    resp = await _preparar_sse(request)
    app[K_ESTADO]["sse_ativos"] += 1
    ferramentas = {}
    try:
        pos = await asyncio.to_thread(transcricao.posicao_inicial_da_cauda, caminho, 1_500_000)
        inicio = pos
        passos, pos = await asyncio.to_thread(transcricao.ler_passos, caminho, pos, ferramentas)
        omitidos = max(0, len(passos) - 150)
        await _enviar(resp, {"tipo": "inicio", "passos": passos[-150:], "omitidos": omitidos, "cortado": inicio > 0})
        ultimo_envio = time.time()
        while True:
            await asyncio.sleep(1)
            try:
                tam = caminho.stat().st_size
            except OSError:
                break
            if tam > pos:
                novos, pos = await asyncio.to_thread(transcricao.ler_passos, caminho, pos, ferramentas, 4_000_000)
                if novos:
                    await _enviar(resp, {"tipo": "passos", "passos": novos})
                    ultimo_envio = time.time()
            elif time.time() - ultimo_envio > 15:
                await resp.write(b": ping\n\n")
                ultimo_envio = time.time()
            app[K_ESTADO]["ultimo_ping"] = time.time()
    except (ConnectionResetError, asyncio.CancelledError, ConnectionError):
        pass
    finally:
        app[K_ESTADO]["sse_ativos"] -= 1
    return resp


# ---------------------------------------------------------------------------------------------------------------
# Sessões, memória, custos, ferramentas, configurações
# ---------------------------------------------------------------------------------------------------------------
async def api_sessoes(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    slug = p["slug"]
    ges = ((cfg.get("gestoras") or {}).get(slug) or {}).get("conversa", "")
    if indice.pendentes(slug):
        indice.indexar_em_segundo_plano(slug)

    def calcular():
        arquivos = indice.listar_arquivos(slug)
        agreg = custos.agregar(slug, cfg["precos"])["por_arquivo"]
        subs = {}
        for a in arquivos:
            if a["tipo"] == "subagente":
                subs[a["sessao"]] = subs.get(a["sessao"], 0) + 1
        saida = []
        for a in arquivos:
            if a["tipo"] != "sessao":
                continue
            ind = indice.indice_se_existe(slug, a["rel"])
            acc = agreg.get(a["rel"])
            tit = indice.titulo_sessao(slug, a["id"], cfg, ind or {})
            saida.append({
                "id": a["id"], "rel": a["rel"], "titulo": tit["titulo"], "titulo_fonte": tit["fonte"], "titulo_original": tit["original"], "resumo": tit["resumo"],
                "primeira": (ind or {}).get("primeira", ""), "inicio": (ind or {}).get("inicio"), "fim": (ind or {}).get("fim") or a["mtime"],
                "mtime": a["mtime"], "tam": a["tam"], "indexado": ind is not None, "gestora": a["id"] == ges,
                "mensagens": acc["mensagens"] if acc else 0, "tokens": custos.total_tokens(acc) if acc else 0,
                "custo": acc["custo"] if acc and not acc["sem_preco"] else None, "subagentes": subs.get(a["id"], 0),
                "modelo": (max(ind["modelos"], key=ind["modelos"].get) if ind and ind.get("modelos") else ""),
                "ramo": (ind or {}).get("branch", ""),
                "ferramentas": sorted(((ind or {}).get("tools") or {}).items(), key=lambda kv: -kv[1])[:5],
                "bastao": bastao.estado_sessao(ind, cfg),          # contexto do último turno e se passou do limite
            })
        saida.sort(key=lambda s: -s["mtime"])
        return saida

    est = indice.estado(slug)
    return _json({"sessoes": await asyncio.to_thread(calcular), "gestora": ges,
                  "indexando": est.progresso["rodando"], "progresso": est.progresso})


async def api_memoria(request):
    p = _projeto_ou_404(request)
    q = request.query.get("q", "")
    if q:
        return _json({"busca": await asyncio.to_thread(memoria.buscar, p["slug"], p["caminho"], q)})
    return _json(await asyncio.to_thread(memoria.listar, p["slug"], p["caminho"]))


async def api_memoria_arquivo(request):
    p = _projeto_ou_404(request)
    txt = await asyncio.to_thread(memoria.conteudo, p["slug"], p["caminho"], request.query.get("id", ""))
    if txt is None:
        return _erro("item não encontrado", 404)
    return _json({"texto": txt})


async def api_custos(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    slug = p["slug"]
    if indice.pendentes(slug):
        indice.indexar_em_segundo_plano(slug)

    def calcular():
        d = custos.agregar(slug, cfg["precos"])
        arquivos = {a["rel"]: a for a in indice.listar_arquivos(slug)}
        por_sessao, por_sub = [], []
        sub_por_sessao = {}
        for rel, acc in d["por_arquivo"].items():
            a = arquivos.get(rel)
            if a is None:
                continue
            ind = indice.indice_se_existe(slug, rel) or {}
            if a["tipo"] == "sessao":
                por_sessao.append({"id": a["id"], "titulo": indice.titulo_sessao(slug, a["id"], cfg, ind)["titulo"], **acc})
            else:
                meta = indice.ler_meta(slug, a)
                por_sub.append({"id": a["id"], "sessao": a["sessao"], "titulo": str(meta.get("description") or ind.get("primeira") or "(subagente)"),
                                "modelo": str(meta.get("model") or ""), **acc})
                s = sub_por_sessao.setdefault(a["sessao"], _soma_vazia())
                for k in ("entrada", "saida", "cache_leitura", "cache_escrita", "mensagens", "custo", "sem_preco"):
                    s[k] += acc[k]
        for s in por_sessao:
            s["subagentes"] = sub_por_sessao.get(s["id"])
        por_sessao.sort(key=lambda s: -(s["custo"] or 0) - custos.total_tokens(s) * 1e-9)
        por_sub.sort(key=lambda s: -(s["custo"] or 0) - custos.total_tokens(s) * 1e-9)
        dias = sorted(d["por_dia"].items())[-30:]
        return {"total": d["total"], "por_modelo": d["por_modelo"], "por_dia": dias, "por_sessao": por_sessao[:30],
                "por_subagente": por_sub[:30], "modelos_sem_preco": d["modelos_sem_preco"], "precos": cfg["precos"],
                "fonte_precos": cfg["fonte_precos"], "limites": painel.limites()}

    est = indice.estado(slug)
    dados = await asyncio.to_thread(calcular)
    dados["indexando"] = est.progresso["rodando"]
    dados["progresso"] = est.progresso
    return _json(dados)


def _soma_vazia():
    return {"entrada": 0, "saida": 0, "cache_leitura": 0, "cache_escrita": 0, "mensagens": 0, "custo": 0.0, "sem_preco": 0}


async def api_mapa_estado(request):
    p = _projeto_ou_404(request)
    est = await asyncio.to_thread(projetos.estado_mapa, p["caminho"], p["slug"])
    rot = config.ler_config()["rotinas"]
    return _json({**est, "vigia": mapa_auto.estado(p["slug"]), "automatico": bool(rot.get("mapa_automatico", True)),
                  "intervalo_s": int(rot.get("mapa_vigia_segundos") or 30)})


async def api_config(request):
    cfg = config.ler_config()
    saida = dict(cfg)
    saida["versao_cerebro"] = __version__
    saida["porta_em_uso"] = request.app[K_PORTA]
    saida["projetos"] = [{"slug": p["slug"], "nome": p["nome"], "caminho": p["caminho"], "oculto": p["oculto"], "extra": p["extra"]}
                         for p in projetos.descobrir()]
    return _json(saida)


def _validar_precos(precos):
    if not isinstance(precos, dict) or len(precos) > 100:
        raise ValueError("tabela de preços inválida")
    limpo = {}
    for modelo, v in precos.items():
        if not isinstance(modelo, str) or not re.fullmatch(r"[A-Za-z0-9._\-]{3,80}", modelo) or not isinstance(v, dict):
            raise ValueError(f"modelo inválido: {modelo!r}")
        item = {}
        for campo in custos.CAMPOS:
            n = v.get(campo)
            if not isinstance(n, (int, float)) or isinstance(n, bool) or n < 0 or n > 10000:
                raise ValueError(f"preço inválido em {modelo}/{campo}")
            item[campo] = float(n)
        item["derivados"] = [c for c in (v.get("derivados") or []) if c in custos.CAMPOS]
        limpo[modelo] = item
    return limpo


async def api_config_salvar(request):
    try:
        corpo = await request.json()
        if not isinstance(corpo, dict):
            raise ValueError("corpo inválido")
    except ValueError:
        return _erro("JSON inválido")

    def mudar(cfg):
        if "tema" in corpo:
            if corpo["tema"] not in ("escuro", "claro"):
                raise ValueError("tema inválido")
            cfg["tema"] = corpo["tema"]
        if "porta" in corpo:
            n = corpo["porta"]
            if not isinstance(n, int) or isinstance(n, bool) or not 1024 <= n <= 65535 or n in config.portas_proibidas():
                raise ValueError("porta inválida ou reservada")
            cfg["porta"] = n
        if "rotinas" in corpo:
            r = corpo["rotinas"]
            r = r if isinstance(r, dict) else {}
            for k in ("autoevolucao_dias", "vigia_novidades_dias"):
                if k not in r:
                    continue
                v = r.get(k)
                if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 365:
                    raise ValueError("intervalo de rotina inválido (1 a 365 dias)")
                cfg["rotinas"][k] = v
            for k in ("analise_automatica", "novidades_automatica", "mapa_automatico"):
                if k in r:
                    if not isinstance(r[k], bool):
                        raise ValueError(f"{k} precisa ser verdadeiro ou falso")
                    cfg["rotinas"][k] = r[k]
            if "mapa_vigia_segundos" in r:
                v = r["mapa_vigia_segundos"]
                if not isinstance(v, int) or isinstance(v, bool) or not 10 <= v <= 3600:
                    raise ValueError("intervalo do vigia do mapa inválido (10 a 3600 segundos)")
                cfg["rotinas"]["mapa_vigia_segundos"] = v
        if "revisao_dias" in corpo:
            v = corpo["revisao_dias"]
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 90:
                raise ValueError("janela da fila a conferir inválida (1 a 90 dias)")
            cfg["revisao_dias"] = v
        if "agentes_regras" in corpo:
            cfg["agentes_regras"] = regras_agentes.validar_regras(corpo["agentes_regras"])
        if "primeiro_uso_concluido" in corpo:
            if not isinstance(corpo["primeiro_uso_concluido"], bool):
                raise ValueError("primeiro_uso_concluido precisa ser verdadeiro ou falso")
            cfg["primeiro_uso_concluido"] = corpo["primeiro_uso_concluido"]
        if "sem_pagina_minutos" in corpo:
            v = corpo["sem_pagina_minutos"]
            if not isinstance(v, int) or isinstance(v, bool) or not 5 <= v <= 1440:
                raise ValueError("tempo inválido (5 a 1440 minutos)")
            cfg["sem_pagina_minutos"] = v
        if "ocultos" in corpo:
            o = corpo["ocultos"]
            if not isinstance(o, list) or not all(isinstance(x, str) and SLUG.match(x) for x in o):
                raise ValueError("lista de ocultos inválida")
            cfg["ocultos"] = sorted(set(o))
        if "precos" in corpo:
            cfg["precos"] = _validar_precos(corpo["precos"])

    try:
        await asyncio.to_thread(config.atualizar_config, mudar)
    except ValueError as e:
        return _erro(str(e))
    projetos.descobrir(forcar=True)
    request.app[K_CACHE].clear()
    return await api_config(request)


async def api_gestora(request):
    p = _projeto_ou_404(request)
    try:
        corpo = await request.json()
        conversa = corpo.get("conversa", "") if isinstance(corpo, dict) else None
        apelido = str(corpo.get("nome", "")).strip()[:80] if isinstance(corpo, dict) else ""
    except ValueError:
        return _erro("JSON inválido")
    if conversa is None or not isinstance(conversa, str):
        return _erro("conversa inválida")
    if conversa == "":
        config.atualizar_config(lambda c: c["gestoras"].pop(p["slug"], None))
        request.app[K_CACHE].clear()
        return _json({"ok": True, "gestora": None})
    if not ID_SESSAO.match(conversa):
        return _erro("identificador de sessão inválido")
    arq = next((a for a in indice.listar_arquivos(p["slug"]) if a["tipo"] == "sessao" and a["id"] == conversa), None)
    if arq is None:
        return _erro("esta sessão não existe neste projeto", 404)
    ind = indice.indice_se_existe(p["slug"], arq["rel"]) or {}
    nome = mascarar(apelido) if apelido else titulos.escolher(p["slug"], conversa, ind, indice.titulo_do_dono(p["slug"], conversa))["titulo"]
    config.atualizar_config(lambda c: c["gestoras"].__setitem__(p["slug"], {"conversa": conversa, "nome": nome}))
    request.app[K_CACHE].clear()
    return _json({"ok": True, "gestora": {"conversa": conversa, "nome": nome}})


async def api_projeto_extra(request):
    try:
        corpo = await request.json()
        caminho = corpo.get("caminho", "") if isinstance(corpo, dict) else ""
        slug = await asyncio.to_thread(projetos.adicionar_extra, caminho)
    except (ValueError, OSError) as e:
        return _erro(str(e))
    request.app[K_CACHE].clear()
    return _json({"ok": True, "slug": slug})


async def api_encerrar(request):
    request.app[K_PARAR].set()
    return _json({"ok": True})


# ---------------------------------------------------------------------------------------------------------------
# Mapa (módulo mapa/, servido com o mesmo token e cookie)
# ---------------------------------------------------------------------------------------------------------------
async def api_mapa_gerar(request):
    """Gera (de novo) a página do mapa a partir do graphify-out do projeto. Só LÊ o graphify-out; escreve em ~/.cerebro."""
    p = _projeto_ou_404(request)
    if not (Path(p["caminho"]) / "graphify-out" / "graph.json").is_file():
        return _erro("este projeto ainda não tem o mapa do Graphify", 409)

    ok, saida = await asyncio.to_thread(mapa_auto.gerar_agora, p["slug"], p["caminho"])
    request.app[K_CACHE].clear()
    if ok is None:
        return _erro(saida, 409)
    return _json({"ok": bool(ok), "saida": saida, "erro": "" if ok else saida}, 200 if ok else 500)


async def api_mapa_criar(request):
    """Primeiro uso: roda o Graphify NO projeto (só quando a pessoa clica) e monta a página do mapa."""
    p = _projeto_ou_404(request)
    exe = ferramentas.exe_graphify()
    if not exe:
        return _erro("o Graphify não está instalado neste PC. Instale com: uv tool install graphifyy  (ou: pip install graphifyy) e tente de novo.", 409)
    ok, saida = await asyncio.to_thread(mapa_auto.criar_mapa, p["slug"], p["caminho"], exe)
    request.app[K_CACHE].clear()
    if ok is None:
        return _erro(saida, 409)
    gi = ""
    try:
        gi = (Path(p["caminho"]) / ".gitignore").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    ja = any(l.strip().rstrip("/") in ("graphify-out", "/graphify-out") for l in gi.splitlines())
    return _json({"ok": bool(ok), "saida": saida, "erro": "" if ok else saida, "sugestao_gitignore": "graphify-out/", "ja_no_gitignore": ja}, 200 if ok else 500)


async def mapa_arquivo(request):
    p = _projeto_ou_404(request)
    nome = request.match_info.get("nome") or "index.html"
    pasta_dados = config.CASA / "projetos" / p["slug"] / "mapa"
    sem_cache = {"Cache-Control": "no-store"}
    if nome == "index.html":
        if not (pasta_dados / "dados.js").is_file():
            return web.Response(status=404, text=_PAGINA_SEM_MAPA, content_type="text/html", charset="utf-8")
        return web.FileResponse(MAPA / "index.html", headers={"Cache-Control": "no-cache"})
    if nome in ESTATICOS_MAPA:
        return web.FileResponse(MAPA / nome, headers={"Cache-Control": "no-cache", "Content-Type": ESTATICOS_MAPA[nome] + "; charset=utf-8"})
    if nome == "dados.js":
        f = pasta_dados / "dados.js"
        if not f.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(f, headers={**sem_cache, "Content-Type": "text/javascript; charset=utf-8"})
    if nome == "historico.json":
        f = pasta_dados / "historico.json"
        if not f.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(f, headers={**sem_cache, "Content-Type": "application/json; charset=utf-8"})
    if nome == "gestora.json":     # a sessão gestora vale na hora, direto do config.json (sem refazer o mapa)
        ges = (config.ler_config().get("gestoras") or {}).get(p["slug"]) or {"nome": "", "conversa": ""}
        return _json({"nome": ges.get("nome", ""), "conversa": ges.get("conversa", "")})
    raise web.HTTPNotFound()


_PAGINA_SEM_MAPA = ("<!doctype html><meta charset=utf-8><title>Mapa</title>"
                    "<body style='font:15px system-ui;background:#0b0e14;color:#e8edf5;padding:32px'>"
                    "<p>O mapa deste projeto ainda não foi gerado.</p>")


# ---------------------------------------------------------------------------------------------------------------
# Montagem e execução
# ---------------------------------------------------------------------------------------------------------------
def criar_app(porta, token=None):
    app = web.Application(middlewares=[seguranca])
    app[K_PORTA] = porta
    app[K_TOKEN] = token or config.ler_token()
    app[K_COOKIE] = config.valor_cookie(app[K_TOKEN])
    app[K_CACHE] = {}
    app[K_ESTADO] = {"ultimo_ping": time.time(), "sse_ativos": 0}
    app[K_PARAR] = asyncio.Event()
    r = app.router
    r.add_get("/", pagina)
    r.add_get("/static/{nome}", estatico)
    r.add_get("/api/saude", saude)
    r.add_get("/api/ping", ping)
    r.add_get("/api/projetos", api_projetos)
    r.add_get("/api/fila", api_fila)
    r.add_get("/api/config", api_config)
    r.add_post("/api/config", api_config_salvar)
    r.add_post("/api/projetos/extra", api_projeto_extra)
    r.add_post("/api/encerrar", api_encerrar)
    r.add_get("/api/p/{slug}/visao", api_visao)
    r.add_get("/api/p/{slug}/agentes", api_agentes)
    r.add_get("/api/p/{slug}/agentes/stream", sse_lista)
    r.add_get("/api/p/{slug}/passos", sse_passos)
    r.add_get("/api/p/{slug}/sessoes", api_sessoes)
    r.add_get("/api/p/{slug}/memoria", api_memoria)
    r.add_get("/api/p/{slug}/memoria/arquivo", api_memoria_arquivo)
    r.add_get("/api/p/{slug}/custos", api_custos)
    r.add_get("/api/p/{slug}/ferramentas", api_ferramentas)
    r.add_post("/api/p/{slug}/ferramentas/rodar", api_ferramenta_rodar)
    r.add_get("/api/p/{slug}/comandos/sugeridos", api_comandos_sugeridos)
    r.add_post("/api/p/{slug}/comandos/aprovar", api_comando_aprovar)
    r.add_post("/api/p/{slug}/comandos/remover", api_comando_remover)
    r.add_get("/api/p/{slug}/ferramentas/execucoes", api_ferramenta_execucoes)
    r.add_get("/api/p/{slug}/ferramentas/saida", api_ferramenta_saida)
    r.add_get("/api/p/{slug}/conferir", api_conferir)
    r.add_post("/api/p/{slug}/conferir", api_conferir_marcar)
    r.add_get("/api/p/{slug}/decisoes", api_decisoes)
    r.add_post("/api/p/{slug}/decisoes", api_decisao_nova)
    r.add_get("/api/p/{slug}/analise", api_analise)
    r.add_post("/api/p/{slug}/analise", api_analise_rodar)
    r.add_post("/api/p/{slug}/propostas/{pid}", api_proposta)
    r.add_post("/api/p/{slug}/tarefas/{tid}", api_tarefa)
    r.add_get("/api/novidades", api_novidades)
    r.add_post("/api/novidades/procurar", api_novidades_procurar)
    r.add_post("/api/novidades/visto", api_novidades_visto)
    r.add_get("/api/p/{slug}/inventario", api_inventario)
    r.add_get("/api/p/{slug}/agentes/previa", api_agentes_previa)
    r.add_post("/api/p/{slug}/agentes/previa", api_agentes_previa_gerar)
    r.add_get("/api/p/{slug}/departamentos", api_departamentos)
    r.add_post("/api/p/{slug}/departamentos", api_departamentos_salvar)
    r.add_get("/api/p/{slug}/mapa/estado", api_mapa_estado)
    r.add_post("/api/p/{slug}/mapa/gerar", api_mapa_gerar)
    r.add_post("/api/p/{slug}/mapa/criar", api_mapa_criar)
    r.add_get("/api/p/{slug}/explicar", api_explicar)
    r.add_get("/api/p/{slug}/explicar/estado", api_explicar_estado)
    r.add_post("/api/p/{slug}/explicar/rodar", api_explicar_rodar)
    r.add_post("/api/p/{slug}/explicar/parar", api_explicar_parar)
    r.add_post("/api/p/{slug}/gestora", api_gestora)
    rotas_backup.registrar(r)                       # backup, restauração e rotinas no Windows (rotas_backup.py)
    rotas_memoria.registrar(r)                     # memória mais forte: editar, compactar, avisos, decisões, passa-bastão
    rotas_tarefas.registrar(r)
    from . import rotas_ias
    rotas_ias.registrar(r)                          # outras IAs: chaves (só entram) e modelos (rotas_ias.py)
    r.add_get("/mapa/{slug}/", mapa_arquivo)
    r.add_get("/mapa/{slug}/{nome}", mapa_arquivo)
    rotas_ganchos.registrar(app)
    rotas_encaixe.registrar(app)              # encaixe no projeto, cópia dos agentes e instalação de ferramentas (só com confirmação)
    from . import rotas_gestora
    rotas_gestora.registrar(app)              # troca da sessão gestora, capítulos e manual do gestor (GESTOR.md / CLAUDE.local.md)
    return app


async def _vigia(app, intervalo=30):
    """Encerra o servidor depois de N minutos sem nenhuma página aberta (a página manda /api/ping; SSE conta como aberta)
    e sem nenhum evento dos ganchos do Claude Code nesse tempo (se fechar, o próximo gancho liga de novo: cerebro_hook.py)."""
    while not app[K_PARAR].is_set():
        await asyncio.sleep(intervalo)
        limite = config.ler_config().get("sem_pagina_minutos", 30) * 60
        if ganchos_eventos.hooks_ativos():
            continue                                  # o Claude Code está mandando eventos: os ganchos precisam do servidor no ar
        if app[K_ESTADO]["sse_ativos"] == 0 and time.time() - app[K_ESTADO]["ultimo_ping"] > limite:
            print("Nenhuma página aberta há muito tempo: encerrando o Cérebro.", flush=True)
            app[K_PARAR].set()


async def _laco_mapa(app):
    """O mapa se atualiza sozinho: confere a data do graph.json de cada projeto (barato) e gera a página quando ficou mais novo.
    A primeira conferência acontece já na abertura do servidor."""
    while not app[K_PARAR].is_set():
        try:
            feitos = await asyncio.to_thread(mapa_auto.varrer)
            if feitos:
                app[K_CACHE].clear()
                print("Mapa atualizado: " + ", ".join(feitos), flush=True)
        except Exception as e:                       # o vigia nunca derruba o servidor
            print(f"Vigia do mapa: {type(e).__name__}: {e}", flush=True)
        espera = (config.ler_config().get("rotinas") or {}).get("mapa_vigia_segundos", 30)
        try:
            await asyncio.wait_for(app[K_PARAR].wait(), timeout=max(10, int(espera)))
        except asyncio.TimeoutError:
            pass


async def _laco_rotinas(app, primeira_espera=20, intervalo=300):
    """Análise automática (sem IA) e, se ligada, busca de novidades: só rodam com o servidor aberto, quando o prazo passou."""
    try:
        await asyncio.wait_for(app[K_PARAR].wait(), timeout=primeira_espera)
        return
    except asyncio.TimeoutError:
        pass
    while not app[K_PARAR].is_set():
        try:
            feitas = await asyncio.to_thread(rotinas.tick)
            if feitas:
                app[K_CACHE].clear()
                print("Rotina: " + ", ".join(feitas), flush=True)
        except Exception as e:
            print(f"Rotinas: {type(e).__name__}: {e}", flush=True)
        try:
            from . import ligacoes
            await asyncio.to_thread(ligacoes.avisar_alertas)       # orçamento/backup → aviso do Windows (uma vez por dia cada)
            await asyncio.to_thread(ligacoes.rotina_retencao)      # transcrições antigas da gestora (só projetos autorizados)
        except Exception as e:
            print(f"Alertas: {type(e).__name__}: {e}", flush=True)
        try:
            await asyncio.wait_for(app[K_PARAR].wait(), timeout=intervalo)
        except asyncio.TimeoutError:
            pass


def _pid_vivo(pid):
    """O processo existe e ainda não terminou?"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            codigo = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(codigo))) and codigo.value == 259    # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def registrar_instancia(porta):
    """Grava servidor.json (pid e porta) SÓ se não houver outro servidor vivo registrado: um segundo servidor em outra porta
    não sobrescreve o arquivo do primeiro. Devolve True se este processo ficou como o registrado."""
    arq = config.CASA / "servidor.json"
    try:
        outro = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        outro = None
    if isinstance(outro, dict) and outro.get("pid") != os.getpid() and _pid_vivo(outro.get("pid")):
        return False
    arq.write_text(json.dumps({"pid": os.getpid(), "porta": porta, "inicio": time.time(), "versao": __version__}), encoding="utf-8")
    return True


def liberar_instancia():
    """Apaga o servidor.json só se o pid dentro dele for o deste processo."""
    arq = config.CASA / "servidor.json"
    try:
        if json.loads(arq.read_text(encoding="utf-8")).get("pid") == os.getpid():
            config.remover(arq)
    except (OSError, ValueError, AttributeError):
        pass


async def _rodar(porta):
    app = criar_app(porta)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.HOST, porta)
    await site.start()
    registrar_instancia(porta)
    print(f"Cérebro do Projeto {__version__} no ar em http://{config.HOST}:{porta}/  (só nesta máquina)", flush=True)
    tarefa = asyncio.create_task(_vigia(app))
    tarefas_fundo = [asyncio.create_task(_laco_mapa(app)), asyncio.create_task(_laco_rotinas(app))]
    # aquece o índice dos últimos dias em segundo plano (sem travar a página)
    for p in projetos.descobrir():
        if not p["oculto"]:
            indice.indexar_em_segundo_plano(p["slug"], time.time() - 8 * 86400)
    try:
        await app[K_PARAR].wait()
    finally:
        tarefa.cancel()
        for tf in tarefas_fundo:
            tf.cancel()
        ferramentas.parar_todos()
        indice.salvar_tudo()
        liberar_instancia()
        await runner.cleanup()


def executar(porta=None):
    cfg = config.ler_config()
    porta = porta or cfg.get("porta") or config.PORTA_PADRAO
    if porta in config.portas_proibidas(cfg):
        print(f"A porta {porta} é reservada para outro produto; escolha outra em --porta.", file=sys.stderr)
        return 2
    try:
        asyncio.run(_rodar(porta))
    except OSError as e:
        print(f"Não consegui abrir a porta {porta}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0
