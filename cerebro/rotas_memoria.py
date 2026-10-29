"""Rotas da memória mais forte: editar/criar/arquivar memória, compactar o MEMORY.md, avisos, decisões e passa-bastão.

A segurança de sempre vale para todas (token/cookie, Host, Origin + JSON nos POST: ver servidor.seguranca). Toda gravação na
memória do Claude Code passa por memoria_edicao (prévia → confirmar → cópia → versão conferida → escrita atômica). Sem
"confirmar": true no corpo, as rotas POST só devolvem a prévia (a diferença) e não gravam nada.
"""
import asyncio

from . import bastao, config, decisoes, memoria_avisos, memoria_compactar, memoria_edicao
from .web_util import K_CACHE, _corpo, _erro, _json, _projeto_ou_404


def _texto(v, limite=50_000):
    return v if isinstance(v, str) and len(v) <= limite else None


async def _executar(request, funcao, *args, **kw):
    """Roda a função numa thread e traduz as recusas: conflito de versão = 409, recusa = 400."""
    try:
        r = await asyncio.to_thread(funcao, *args, **kw)
    except memoria_edicao.Conflito as e:
        return _erro(str(e), 409)
    except ValueError as e:                        # Recusado é um ValueError
        return _erro(str(e), 400)
    if isinstance(r, dict) and r.get("gravado"):
        request.app[K_CACHE].clear()
    return _json(r)


async def api_memoria_abrir(request):
    p = _projeto_ou_404(request)
    return await _executar(request, memoria_edicao.abrir, p["slug"], request.query.get("nome", ""))


async def api_memoria_editar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    return await _executar(request, memoria_edicao.editar, p["slug"], str(c.get("nome", "")), _texto(c.get("versao"), 200),
                           descricao=_texto(c.get("descricao"), 2000), corpo=_texto(c.get("corpo")), confirmar=c.get("confirmar") is True)


async def api_memoria_criar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    g = lambda k, lim=5000: _texto(c.get(k), lim) or ""  # noqa: E731
    return await _executar(request, memoria_edicao.criar, p["slug"], g("titulo", 300), g("descricao", 1000), g("tipo", 20), g("corpo", 50_000),
                           porque=g("porque"), como_aplicar=g("como_aplicar"), gancho=g("gancho", 1000),
                           versao_indice=_texto(c.get("versao_indice"), 200), confirmar=c.get("confirmar") is True)


async def api_memoria_arquivar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    return await _executar(request, memoria_edicao.arquivar, p["slug"], str(c.get("nome", "")), _texto(c.get("versao"), 200),
                           versao_indice=_texto(c.get("versao_indice"), 200), confirmar=c.get("confirmar") is True)


async def api_memoria_compactar(request):
    p = _projeto_ou_404(request)
    return await _executar(request, memoria_compactar.propor, p["slug"])


async def api_memoria_compactar_aplicar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    return await _executar(request, memoria_compactar.aplicar, p["slug"], _texto(c.get("versao"), 200), confirmar=c.get("confirmar") is True)


async def api_memoria_avisos(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    dias = int((cfg.get("memoria_avisos") or {}).get("dias_velha") or memoria_avisos.DIAS_VELHA)
    return _json(await asyncio.to_thread(memoria_avisos.avisos, p["slug"], p["caminho"], dias, False, request.query.get("forcar") != "1"))


async def api_decisao_mudar(request):
    """Arquivar ou editar (substituir) uma decisão registrada. Acrescenta linha; nunca apaga."""
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    did = request.match_info["did"]
    acao = c.get("acao")
    confirmar = c.get("confirmar") is True
    if acao == "arquivar":
        return await _executar(request, decisoes.arquivar, p["slug"], did, _texto(c.get("motivo"), 300) or "", "dono", confirmar)
    if acao == "editar":
        return await _executar(request, decisoes.substituir, p["slug"], did, _texto(c.get("texto"), 4000) or "", "dono", confirmar)
    return _erro("acao precisa ser arquivar ou editar")


async def api_bastao(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    return _json({"longas": await asyncio.to_thread(bastao.sessoes_longas, p["slug"], cfg), "parametros": bastao.parametros(cfg)})


async def api_bastao_gerar(request):
    """Gera o resumo de passa-bastão (grava só em ~/.cerebro) e devolve o texto mascarado."""
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    sessao = str(c.get("sessao", ""))
    try:
        texto = await asyncio.to_thread(bastao.resumo, p["slug"], sessao)
    except ValueError as e:
        return _erro(str(e), 400)
    return _json({"texto": texto, "arquivo": str(bastao.caminho_resumo(p["slug"], sessao))})


def registrar(r):
    """Chamado por servidor.criar_app."""
    r.add_get("/api/p/{slug}/memoria/editar", api_memoria_abrir)
    r.add_post("/api/p/{slug}/memoria/editar", api_memoria_editar)
    r.add_post("/api/p/{slug}/memoria/criar", api_memoria_criar)
    r.add_post("/api/p/{slug}/memoria/arquivar", api_memoria_arquivar)
    r.add_get("/api/p/{slug}/memoria/compactar", api_memoria_compactar)
    r.add_post("/api/p/{slug}/memoria/compactar", api_memoria_compactar_aplicar)
    r.add_get("/api/p/{slug}/memoria/avisos", api_memoria_avisos)
    r.add_post("/api/p/{slug}/decisoes/{did}", api_decisao_mudar)
    r.add_get("/api/p/{slug}/bastao", api_bastao)
    r.add_post("/api/p/{slug}/bastao", api_bastao_gerar)
