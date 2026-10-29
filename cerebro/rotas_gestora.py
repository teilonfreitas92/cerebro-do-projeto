"""Rotas da troca da sessão gestora, dos capítulos e do manual do gestor. A segurança de sempre vale (token/cookie, Host,
Origin + JSON nos POST: ver servidor.seguranca). Escrever no projeto (CLAUDE.local.md) exige {"confirmar": true} e a assinatura
da prévia. Nenhuma rota apaga: "autorizar" só liga a rotina da retencao_gestora (que tem as próprias conferências)."""
import asyncio

from aiohttp import web

from . import capitulos, config, gestora_troca, manual_gestor, manual_projeto, retencao_gestora
from .web_util import K_CACHE, _corpo, _erro, _json, _projeto_ou_404


async def api_corrente(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    d = await asyncio.to_thread(gestora_troca.resumo_para_tela, p["slug"], cfg)
    d["capitulos"] = await asyncio.to_thread(capitulos.listar, p["slug"], 60)
    return _json(d)


async def api_autorizar(request):
    """Liga (com {"confirmar": true}, o clique do dono) ou desliga a remoção das transcrições antigas da gestora deste projeto."""
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    ligar = c.get("ligar") is not False
    try:
        r = await asyncio.to_thread(retencao_gestora.autorizar, p["slug"], c.get("confirmar") is True, ligar)
    except ValueError as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "autorizado": r})


def _ler_texto(caminho):
    try:
        return caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


async def api_bastao(request):
    p = _projeto_ou_404(request)
    try:
        arq = gestora_troca.caminho_bastao(p["slug"], request.query.get("nome", ""))
    except ValueError as e:
        return _erro(str(e))
    texto = await asyncio.to_thread(_ler_texto, arq)
    return _erro("bastão não encontrado", 404) if texto is None else _json({"nome": arq.name, "texto": texto})


async def api_capitulo(request):
    p = _projeto_ou_404(request)
    try:
        arq = capitulos.caminho(p["slug"], request.query.get("nome", ""))
    except ValueError as e:
        return _erro(str(e))
    texto = await asyncio.to_thread(_ler_texto, arq)
    return _erro("capítulo não encontrado", 404) if texto is None else _json({"nome": arq.name, "texto": texto})


async def api_manual_projeto(request):
    p = _projeto_ou_404(request)
    acao = request.query.get("acao") or ("remover" if manual_projeto.instalado(p) else "instalar")
    try:
        return _json(await asyncio.to_thread(manual_projeto.previa, p, acao, config.ler_config()))
    except (ValueError, OSError) as e:
        return _json({"acao": acao, "aplicavel": False, "motivo": str(e), "instalado": manual_projeto.instalado(p), "arquivos": []})


async def api_manual_projeto_aplicar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    acao, assinatura = c.get("acao"), c.get("assinatura")
    if acao not in manual_projeto.ACOES or not isinstance(assinatura, str):
        return _erro("informe a ação (instalar ou remover) e a assinatura da prévia")
    try:
        r = await asyncio.to_thread(manual_projeto.aplicar, p, acao, c.get("confirmar") is True, assinatura, config.ler_config())
    except (ValueError, OSError) as e:
        return _erro(str(e), 409)
    request.app[K_CACHE].clear()
    return _json(r)


async def api_manual(request):
    return _json(await asyncio.to_thread(manual_gestor.estado))


async def api_manual_visto(request):
    return _json(await asyncio.to_thread(manual_gestor.marcar_visto))


async def _ao_subir(app):
    """Regera o GESTOR.md quando a versão ou o conteúdo mudou (nunca derruba o servidor)."""
    try:
        r = await asyncio.to_thread(manual_gestor.gerar)
        if r["mudou"]:
            print(f"Manual do gestor atualizado: {r['caminho']} ({r['versao']}, cerca de {r['tokens']} tokens)", flush=True)
    except Exception as e:
        print(f"Manual do gestor: {type(e).__name__}: {e}", flush=True)


def registrar(app: web.Application):
    r = app.router
    r.add_get("/api/p/{slug}/gestora/corrente", api_corrente)
    r.add_post("/api/p/{slug}/gestora/autorizar", api_autorizar)
    r.add_get("/api/p/{slug}/gestora/bastao", api_bastao)
    r.add_get("/api/p/{slug}/gestora/capitulo", api_capitulo)
    r.add_get("/api/p/{slug}/manual", api_manual_projeto)
    r.add_post("/api/p/{slug}/manual", api_manual_projeto_aplicar)
    r.add_get("/api/gestor/manual", api_manual)
    r.add_post("/api/gestor/manual/visto", api_manual_visto)
    app.on_startup.append(_ao_subir)
