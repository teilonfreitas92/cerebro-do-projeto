"""Rotas das outras IAs (ver ias_externas.py) para Configurações › Outras IAs. Mesma segurança das outras: cookie, Host,
Origin e JSON. A chave entra por POST e nunca sai: a resposta só diz se existe e os 4 últimos caracteres."""
import asyncio
import re

from . import config, ias_externas
from .web_util import _corpo, _erro, _json

MODELO_VALIDO = re.compile(r"^[A-Za-z0-9._:/\-]{1,80}$")


async def api_ias(request):
    return _json(await asyncio.to_thread(ias_externas.situacao))


async def api_ias_chave(request):
    c = await _corpo(request)
    ia = c.get("ia")
    if ia not in ias_externas.PROVEDORES:
        return _erro("IA desconhecida")
    try:
        if c.get("remover") is True:
            await asyncio.to_thread(ias_externas.remover_chave, ia)
        else:
            await asyncio.to_thread(ias_externas.guardar_chave, ia, c.get("chave") if isinstance(c.get("chave"), str) else "")
    except ias_externas.ErroIA as e:
        return _erro(str(e))
    return _json(await asyncio.to_thread(ias_externas.situacao))


async def api_ias_modelo(request):
    """Troca o modelo de uma IA (vazio volta ao padrão)."""
    c = await _corpo(request)
    ia, modelo = c.get("ia"), (c.get("modelo") or "").strip() if isinstance(c.get("modelo"), str) else ""
    if ia not in ias_externas.PROVEDORES:
        return _erro("IA desconhecida")
    if modelo and not MODELO_VALIDO.match(modelo):
        return _erro("nome de modelo inválido")

    def mudar(cfg):
        if not isinstance(cfg.get("ias"), dict):
            cfg["ias"] = {}
        modelos = cfg["ias"].setdefault("modelos", {})
        if modelo:
            modelos[ia] = modelo
        else:
            modelos.pop(ia, None)
    await asyncio.to_thread(config.atualizar_config, mudar)
    return _json(await asyncio.to_thread(ias_externas.situacao))


def registrar(r):
    r.add_get("/api/ias", api_ias)
    r.add_post("/api/ias/chave", api_ias_chave)
    r.add_post("/api/ias/modelo", api_ias_modelo)
