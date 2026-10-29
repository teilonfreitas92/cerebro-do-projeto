"""Rotas dos ganchos do Claude Code, da statusLine e dos avisos do Windows.

POST /api/hooks/evento  (receptor; NÃO usa o cookie da página)
  * Host precisa ser 127.0.0.1/localhost:<porta> (como o resto);
  * QUALQUER cabeçalho Origin é recusado (o receptor não é chamado por navegador: um site não consegue fingir ser o gancho);
  * segredo próprio no cabeçalho X-Cerebro-Hooks (~/.cerebro/hooks_token, nunca o token da página);
  * corpo até 256 KB, JSON tolerante (quebrado = ignorado), resposta rápida: {} ou só additionalContext de um ouvinte.
As outras rotas (estado, prévia, ligar/desligar, avisos) são da página e passam pela segurança de sempre (cookie + Origin + JSON).
"""
import asyncio
import hmac
import os
import time

from aiohttp import web

from . import avisos, ganchos_claude, ganchos_eventos
from .web_util import K_PORTA, _corpo, _erro, _json


def _iguais(a, b):
    return hmac.compare_digest(str(a).encode("utf-8", "replace"), str(b).encode("utf-8", "replace"))


async def portao(request, handler):
    """Chamado pelo middleware de segurança do servidor ANTES das regras da página, só para a rota do receptor."""
    porta = request.app[K_PORTA]
    if request.headers.get("Host", "").lower() not in {f"127.0.0.1:{porta}", f"localhost:{porta}"}:
        return web.Response(status=421, text="Host não permitido")
    if "Origin" in request.headers or "Sec-Fetch-Site" in request.headers:
        return web.Response(status=403, text="O receptor dos ganchos não aceita chamadas de páginas")
    if request.method != "POST":
        return web.Response(status=405, text="Use POST")
    esperado = ganchos_eventos.token_hooks(criar=False)
    enviado = request.headers.get(ganchos_eventos.CABECALHO, "")
    if not esperado or not enviado or not _iguais(enviado, esperado):
        return web.Response(status=401, text="não autorizado")
    if (request.content_length or 0) > ganchos_eventos.LIMITE_CORPO:
        return web.Response(status=413, text="corpo grande demais")
    return await handler(request)


async def api_evento(request):
    corpo = await request.content.read(ganchos_eventos.LIMITE_CORPO + 1)
    if len(corpo) > ganchos_eventos.LIMITE_CORPO:
        return web.Response(status=413, text="corpo grande demais")
    bruto = ganchos_eventos.ler_corpo(corpo)
    if bruto is None:
        return _json({})
    try:
        ev, resposta = await asyncio.wait_for(asyncio.to_thread(ganchos_eventos.receber, bruto), timeout=3)
    except Exception as e:                        # o Claude Code nunca recebe erro nosso
        print(f"Receptor de ganchos: {type(e).__name__}: {e}", flush=True)
        return _json({})
    if ev is not None:
        ganchos_eventos.acordar()
    return _json(resposta)


# ---------------------------------------------------------------------------------------------------------------
# Página: Configurações › "Agentes ao vivo instantâneo"
# ---------------------------------------------------------------------------------------------------------------
def _opcoes(c):
    hooks = c.get("hooks", True)
    modo = c.get("modo", "comando")
    st = c.get("statusline") or None
    if not isinstance(hooks, bool) or modo not in ganchos_claude.MODOS or (st is not None and st not in ganchos_claude.MODOS_STATUS):
        raise ValueError("opções inválidas")
    return hooks, modo, st


async def api_ganchos_estado(request):
    est = await asyncio.to_thread(ganchos_claude.estado)
    est["porta_em_uso"] = request.app[K_PORTA]
    est["eventos_recebidos"] = ganchos_eventos.info()
    est["recentes"] = ganchos_eventos.recentes(15)
    return _json(est)


async def api_ganchos_previa(request):
    c = await _corpo(request)
    try:
        hooks, modo, st = _opcoes(c)
        return _json(await asyncio.to_thread(ganchos_claude.previa, hooks, modo, st))
    except ValueError as e:
        return _erro(str(e))


async def api_ganchos_instalar(request):
    c = await _corpo(request)
    if c.get("confirmar") is not True:
        return _erro("confirme depois de ver o que muda")
    try:
        hooks, modo, st = _opcoes(c)
        r = await asyncio.to_thread(ganchos_claude.instalar, True, hooks, modo, st)
    except ganchos_claude.PrecisaDecidir as e:
        return _erro(str(e), 409)
    except ValueError as e:
        return _erro(str(e))
    except OSError as e:
        return _erro(f"não consegui gravar: {e}", 500)
    return _json(r)


async def api_ganchos_remover(request):
    c = await _corpo(request)
    if c.get("confirmar") is not True:
        return _erro("confirme antes de desligar")
    hooks, st = c.get("hooks", True), c.get("statusline", False)
    if not isinstance(hooks, bool) or not isinstance(st, bool):
        return _erro("opções inválidas")
    try:
        return _json(await asyncio.to_thread(ganchos_claude.remover, True, hooks, st))
    except ValueError as e:
        return _erro(str(e))
    except OSError as e:
        return _erro(f"não consegui gravar: {e}", 500)


# ---------------------------------------------------------------------------------------------------------------
# Página: Configurações › "Avisos no Windows"
# ---------------------------------------------------------------------------------------------------------------
async def api_avisos(request):
    return _json({"preferencias": avisos.preferencias(), "tipos": avisos.TIPOS, "historico": avisos.historico()[:20],
                  "windows": os.name == "nt"})


async def api_avisos_salvar(request):
    c = await _corpo(request)
    try:
        p = await asyncio.to_thread(avisos.salvar_preferencias, c)
    except ValueError as e:
        return _erro(str(e))
    return _json({"ok": True, "preferencias": p})


async def api_avisos_testar(request):
    r = await asyncio.to_thread(avisos.avisar, "Cérebro do Projeto", "Aviso de teste: se você está lendo isto, os avisos funcionam.",
                                f"teste:{time.time()}", "geral")
    return _json({"resultado": r})


def registrar(app):
    """Liga as rotas e os gatilhos dos avisos. Chamado por servidor.criar_app."""
    avisos.ligar_gatilhos()
    from . import ligacoes
    ligacoes.ligar()                                 # tarefas → gestora, PreCompact → passa-bastão
    r = app.router
    r.add_post(ganchos_eventos.ROTA, api_evento)
    r.add_get("/api/ganchos/estado", api_ganchos_estado)
    r.add_post("/api/ganchos/previa", api_ganchos_previa)
    r.add_post("/api/ganchos/instalar", api_ganchos_instalar)
    r.add_post("/api/ganchos/remover", api_ganchos_remover)
    r.add_get("/api/avisos", api_avisos)
    r.add_post("/api/avisos", api_avisos_salvar)
    r.add_post("/api/avisos/testar", api_avisos_testar)

