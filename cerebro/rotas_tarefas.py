"""Rotas das tarefas para o gestor (criadas na página) e do orçamento de gasto.
A segurança é a de todas as rotas (servidor.seguranca): cookie/token em tudo, e Origin + JSON em todo POST."""
import asyncio

from . import config, orcamento, projetos, tarefas_gestor
from .web_util import K_CACHE, _corpo, _erro, _json, _projeto_ou_404


# ---------------------------------------------------------------------------------------------------------------
# Tarefas
# ---------------------------------------------------------------------------------------------------------------
async def api_tarefas_lista(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    estado, prioridade = request.query.get("estado") or None, request.query.get("prioridade") or None
    if estado and estado not in tarefas_gestor.ESTADOS:
        return _erro("estado inválido")
    if prioridade and prioridade not in tarefas_gestor.PRIORIDADES:
        return _erro("prioridade inválida")
    itens = await asyncio.to_thread(tarefas_gestor.listar, p["slug"], cfg, estado, prioridade, request.query.get("q", "")[:100])
    return _json({"itens": itens, "contagem": tarefas_gestor.contagem(p["slug"]), "opcoes": tarefas_gestor.opcoes(cfg)})


async def api_tarefas_pontos(request):
    p = _projeto_ou_404(request)
    return _json(await asyncio.to_thread(tarefas_gestor.pontos_do_mapa, p["slug"], request.query.get("q", "")[:100]))


async def api_tarefa_criar(request):
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    try:
        item = await asyncio.to_thread(tarefas_gestor.criar, p["slug"], c.get("titulo"), c.get("descricao"), c.get("prioridade") or "normal",
                                       c.get("pontos"), str(c.get("agente_tipo") or ""), "dono")
    except ValueError as e:
        return _erro(str(e))
    request.app[K_CACHE].clear()
    return _json({"ok": True, "item": item, "contagem": tarefas_gestor.contagem(p["slug"])})


async def api_tarefa_mudar(request):
    """O dono mexe numa tarefa: troca o estado (ex.: conferir -> feita, recusar, reabrir) ou edita os dados dela."""
    p = _projeto_ou_404(request)
    tid = request.match_info["tid"]
    if not tarefas_gestor.id_valido(tid):
        return _erro("tarefa inválida")
    c = await _corpo(request)
    acao = str(c.get("acao", "estado"))
    try:
        if acao == "estado":
            item = await asyncio.to_thread(tarefas_gestor.mudar_estado, p["slug"], tid, str(c.get("estado", "")), "dono", str(c.get("agente") or ""),
                                           str(c.get("nota") or ""))
        elif acao == "editar":
            campos = {k: c[k] for k in ("titulo", "descricao", "prioridade", "pontos", "agente_tipo") if k in c}
            item = await asyncio.to_thread(tarefas_gestor.editar, p["slug"], tid, campos, "dono")
        else:
            return _erro("ação precisa ser estado ou editar")
    except ValueError as e:
        return _erro(str(e), 404 if "não encontrada" in str(e) else 400)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "item": item, "contagem": tarefas_gestor.contagem(p["slug"])})


# ---------------------------------------------------------------------------------------------------------------
# Orçamento
# ---------------------------------------------------------------------------------------------------------------
async def api_orcamento(request):
    return _json(await asyncio.to_thread(orcamento.estado))


async def api_orcamento_projeto(request):
    """Só o que a aba Custos precisa: o bloco do projeto e o geral."""
    p = _projeto_ou_404(request)
    est = await asyncio.to_thread(orcamento.estado, None, None, p["slug"])
    return _json({"hoje": est["hoje"], "estimativa": est["estimativa"], "geral": est["geral"], "projeto": est["projetos"][0] if est["projetos"] else None})


async def api_orcamento_salvar(request):
    c = await _corpo(request)
    escopo = c.get("escopo")
    if not isinstance(escopo, str) or not escopo:
        return _erro("informe o escopo: geral ou o slug do projeto")
    if escopo != "geral" and not any(p["slug"] == escopo for p in projetos.descobrir()):
        return _erro("projeto não encontrado", 404)
    campos = {k: c[k] for k in ("dia", "semana", "mes", "aviso_pct") if k in c}
    try:
        await asyncio.to_thread(orcamento.definir, escopo, **campos)
    except ValueError as e:
        return _erro(str(e))
    request.app[K_CACHE].clear()
    return _json({"ok": True, **await asyncio.to_thread(orcamento.estado)})


def registrar(r):
    """Liga as rotas no roteador do aplicativo (chamado por servidor.criar_app)."""
    r.add_get("/api/p/{slug}/tarefas-gestor", api_tarefas_lista)
    r.add_post("/api/p/{slug}/tarefas-gestor", api_tarefa_criar)
    r.add_get("/api/p/{slug}/tarefas-gestor/pontos", api_tarefas_pontos)
    r.add_post("/api/p/{slug}/tarefas-gestor/{tid}", api_tarefa_mudar)
    r.add_get("/api/orcamento", api_orcamento)
    r.add_post("/api/orcamento", api_orcamento_salvar)
    r.add_get("/api/p/{slug}/orcamento", api_orcamento_projeto)
