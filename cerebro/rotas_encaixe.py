"""Rotas que ESCREVEM num projeto ou instalam programas: plano de encaixe (prévia, aplicar, desfazer), cópia dos agentes e
instalação de ferramentas. A segurança de sempre vale (token, cookie, Host, Origin, JSON: ver servidor.seguranca) e, além
dela, todo POST daqui exige {"confirmar": true}, que a página só manda do botão da tela de confirmação."""
import asyncio

from aiohttp import web

from . import config, encaixe, escrita_projeto, instalador
from .web_util import K_CACHE, _corpo, _erro, _json, _projeto_ou_404


def _opcoes(corpo):
    o = corpo.get("opcoes")
    if not isinstance(o, dict):
        return {}
    limpo = {}
    if o.get("conflito") in ("pular", "cerebro_md"):
        limpo["conflito"] = o["conflito"]
    if o.get("modo") in ("config", "encadear", "novo"):
        limpo["modo"] = o["modo"]
    return limpo


async def api_encaixe(request):
    p = _projeto_ou_404(request)
    return _json(await asyncio.to_thread(encaixe.previa_tudo, p, config.ler_config()))


async def api_encaixe_previa(request):
    p = _projeto_ou_404(request)
    acao = request.query.get("acao", "")
    opcoes = {k: v for k, v in (("conflito", request.query.get("conflito")), ("modo", request.query.get("modo"))) if v}
    try:
        return _json(await asyncio.to_thread(encaixe.previa, p, acao, _opcoes({"opcoes": opcoes}), config.ler_config()))
    except (ValueError, OSError) as e:
        return _erro(str(e), 409)


async def api_encaixe_aplicar(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    acao, assinatura = corpo.get("acao"), corpo.get("assinatura")
    if not isinstance(acao, str) or not isinstance(assinatura, str):
        return _erro("informe a ação e a assinatura da prévia")
    try:
        r = await asyncio.to_thread(encaixe.aplicar, p, acao, corpo.get("confirmar") is True, _opcoes(corpo), assinatura, config.ler_config())
    except (ValueError, OSError) as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json(r)


async def api_encaixe_desfazer_previa(request):
    p = _projeto_ou_404(request)
    try:
        return _json(await asyncio.to_thread(encaixe.previa_desfazer, p, config.ler_config()))
    except (ValueError, OSError) as e:
        return _erro(str(e), 409)


async def api_encaixe_desfazer(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    aceite = corpo.get("aceitar_mexidos")
    aceite = aceite[:100] if isinstance(aceite, str) else None
    try:
        r = await asyncio.to_thread(encaixe.desfazer, p, corpo.get("confirmar") is True, config.ler_config(), aceite)
    except escrita_projeto.DesfazerComMudancas as e:          # o dono mexeu depois: devolve a diferença para a tela mostrar
        return _json({"erro": str(e), "mexidos": e.mexidos, "assinatura_mexidos": e.assinatura}, 409)
    except (ValueError, OSError) as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json({"ok": True, **r})


async def api_instalar_previa(request):
    _projeto_ou_404(request)
    try:
        return _json(instalador.previa(request.query.get("id", "")))
    except ValueError as e:
        return _erro(str(e), 404)


async def api_instalar(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    fid = corpo.get("id")
    if not isinstance(fid, str):
        return _erro("informe a ferramenta")
    try:
        reg = await asyncio.to_thread(instalador.instalar, p["slug"], p["caminho"], fid, corpo.get("confirmar") is True,
                                      corpo.get("aceitar_termos") is True)
    except ValueError as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "execucao": reg})


def registrar(app: web.Application):
    r = app.router
    r.add_get("/api/p/{slug}/encaixe", api_encaixe)
    r.add_get("/api/p/{slug}/encaixe/previa", api_encaixe_previa)
    r.add_post("/api/p/{slug}/encaixe/aplicar", api_encaixe_aplicar)
    r.add_get("/api/p/{slug}/encaixe/desfazer", api_encaixe_desfazer_previa)
    r.add_post("/api/p/{slug}/encaixe/desfazer", api_encaixe_desfazer)
    r.add_get("/api/p/{slug}/ferramentas/instalar", api_instalar_previa)
    r.add_post("/api/p/{slug}/ferramentas/instalar", api_instalar)

