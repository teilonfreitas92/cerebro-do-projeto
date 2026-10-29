"""Rotas das explicações por IA do mapa (ver explicar_ia.py). Mesma segurança de todas as outras: cookie, Host, Origin e JSON.
Nada roda sozinho: a estimativa é só leitura; gastar tokens exige o POST de "rodar", que a página só manda quando a pessoa clica."""
import asyncio
from pathlib import Path

from . import explicar_ia, mapa_auto
from .web_util import K_CACHE, _corpo, _erro, _json, _projeto_ou_404


def _tem_mapa(p):
    return (Path(p["caminho"]) / "graphify-out" / "graph.json").is_file()


def _numero(v, padrao):
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        return padrao
    try:
        return int(v)
    except ValueError:
        return padrao


async def api_explicar(request):
    """Estimativa (sem gastar nada) + estado da rodada. ?limite=N&via=claude|api."""
    p = _projeto_ou_404(request)
    if not _tem_mapa(p):
        return _erro("este projeto ainda não tem o mapa do Graphify", 409)
    via = request.query.get("via", "claude")
    if via not in ("claude", "api"):
        return _erro("via inválida (claude ou api)")
    limite = _numero(request.query.get("limite"), explicar_ia.LIMITE_PADRAO)
    est = await asyncio.to_thread(explicar_ia.estimar, p["slug"], p["caminho"], limite, via)
    return _json({"estimativa": est, "rodada": explicar_ia.estado(p["slug"])})


async def api_explicar_estado(request):
    """Só o andamento da rodada (barato: a página pergunta a cada segundo enquanto roda)."""
    p = _projeto_ou_404(request)
    return _json({"rodada": explicar_ia.estado(p["slug"])})


async def api_explicar_rodar(request):
    p = _projeto_ou_404(request)
    if not _tem_mapa(p):
        return _erro("este projeto ainda não tem o mapa do Graphify", 409)
    corpo = await _corpo(request)
    via = corpo.get("via", "claude")
    if via not in ("claude", "api"):
        return _erro("via inválida (claude ou api)")
    limite = max(1, min(_numero(corpo.get("limite"), explicar_ia.LIMITE_PADRAO), explicar_ia.LIMITE_MAXIMO))
    try:
        est = await asyncio.to_thread(explicar_ia.iniciar, p["slug"], p["caminho"], limite, via, None, mapa_auto.gerar_agora)
    except ValueError as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "rodada": est})


async def api_explicar_parar(request):
    p = _projeto_ou_404(request)
    return _json({"ok": explicar_ia.parar(p["slug"]), "rodada": explicar_ia.estado(p["slug"])})
