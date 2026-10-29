"""Ajudantes das rotas do servidor: resposta JSON, erro, projeto da URL, cache curto e as chaves do aplicativo (AppKey)."""
import asyncio
import json
import re
import time

from aiohttp import web

from . import projetos, propostas

K_PORTA, K_TOKEN, K_COOKIE = web.AppKey("porta", int), web.AppKey("token", str), web.AppKey("cookie", str)
K_CACHE, K_ESTADO, K_PARAR = web.AppKey("cache", dict), web.AppKey("estado", dict), web.AppKey("parar", asyncio.Event)
SLUG = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")


def _json(dados, status=200):
    return web.Response(text=json.dumps(dados, ensure_ascii=False, separators=(",", ":")), status=status,
                        content_type="application/json", charset="utf-8", headers={"Cache-Control": "no-store"})


def _erro(msg, status=400):
    return _json({"erro": msg}, status)


def _projeto_ou_404(request):
    slug = request.match_info["slug"]
    if not SLUG.match(slug):
        raise web.HTTPBadRequest(text="slug inválido")
    p = projetos.achar(slug)
    if p is None:
        raise web.HTTPNotFound(text="projeto não encontrado")
    return p


def _cache_curto(app, chave, segundos, calcular):
    c = app[K_CACHE].get(chave)
    agora = time.time()
    if c and agora - c[0] < segundos:
        return c[1]
    v = calcular()
    app[K_CACHE][chave] = (agora, v)
    return v


async def _corpo(request):
    try:
        c = await request.json()
    except ValueError:
        c = None
    return c if isinstance(c, dict) else {}


def _escopo_ou_404(request):
    """Slug de um projeto OU '_cerebro' (propostas do próprio Cérebro e novidades)."""
    slug = request.match_info["slug"]
    if slug == propostas.ESCOPO_CEREBRO:
        return slug
    return _projeto_ou_404(request)["slug"]
