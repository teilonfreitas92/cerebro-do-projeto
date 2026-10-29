"""Rotas do gestor: ferramentas, fila "a conferir", decisões, análise e propostas, novidades, inventário, agentes por tipo e departamentos.
(Separadas do servidor.py só para ele não crescer sem fim; a segurança — token, cookie, Host e Origin — vale para todas, ver servidor.seguranca.)"""
import asyncio
import re
from pathlib import Path

from . import (analise, config, decisoes, departamentos, ferramentas, instalador, inventario, mapa_auto, memoria, novidades, propostas,
               regras_agentes, revisoes, sugestoes)
from .web_util import K_CACHE, _corpo, _erro, _escopo_ou_404, _json, _projeto_ou_404


async def api_ferramentas(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    dados = await asyncio.to_thread(ferramentas.montar, p["slug"], p["caminho"], cfg, request.query.get("forcar") == "1")
    dados["sugestoes"] = await asyncio.to_thread(sugestoes.listar, p["slug"], p["caminho"], cfg)       # só sugestão: nada roda sem aprovação
    dados["instalacao"] = await asyncio.to_thread(instalador.disponiveis)        # botão Instalar só onde o instalador existe
    return _json(dados)


async def api_comandos_sugeridos(request):
    p = _projeto_ou_404(request)
    return _json({"sugestoes": await asyncio.to_thread(sugestoes.listar, p["slug"], p["caminho"])})


async def api_comando_aprovar(request):
    """A pessoa aprovou uma sugestão: entra na lista fechada. A página manda só o id; o comando vem da detecção do servidor."""
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    cid = corpo.get("id")
    if not isinstance(cid, str):
        return _erro("informe o id da sugestão")
    try:
        await asyncio.to_thread(sugestoes.aprovar, p["slug"], p["caminho"], cid)
    except ValueError as e:
        return _erro(str(e), 404)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "sugestoes": await asyncio.to_thread(sugestoes.listar, p["slug"], p["caminho"])})


async def api_comando_remover(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    cid = corpo.get("id")
    if not isinstance(cid, str):
        return _erro("informe o id do comando")
    try:
        await asyncio.to_thread(sugestoes.remover, p["slug"], cid)
    except ValueError as e:
        return _erro(str(e), 404)
    request.app[K_CACHE].clear()
    return _json({"ok": True})



async def api_ferramenta_rodar(request):
    """Roda um comando da lista fechada do projeto (só o id vem da página). Só quando a pessoa clica."""
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    cid = corpo.get("id")
    if not isinstance(cid, str):
        return _erro("informe o id do comando")
    try:
        reg = await asyncio.to_thread(ferramentas.rodar, p["slug"], p["caminho"], config.ler_config(), cid)
    except ValueError as e:
        return _erro(str(e), 409)
    return _json({"ok": True, "execucao": reg})


async def api_ferramenta_execucoes(request):
    p = _projeto_ou_404(request)
    return _json(ferramentas.estado_execucoes(p["slug"]))


async def api_ferramenta_saida(request):
    p = _projeto_ou_404(request)
    txt = ferramentas.saida_da_execucao(p["slug"], request.query.get("id", ""))
    if txt is None:
        return _erro("saída não encontrada", 404)
    return _json({"texto": txt})


# ---------------------------------------------------------------------------------------------------------------
# A conferir, decisões, análise, novidades, inventário, agentes por tipo, departamentos
# ---------------------------------------------------------------------------------------------------------------
async def api_conferir(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    return _json(await asyncio.to_thread(revisoes.fila, p["slug"], cfg))


async def api_conferir_marcar(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    cfg = config.ler_config()
    try:
        if corpo.get("dispensar_antigos"):
            n = await asyncio.to_thread(revisoes.dispensar_antigos, p["slug"], cfg)
            request.app[K_CACHE].clear()
            return _json({"ok": True, "dispensados": n})
        item = await asyncio.to_thread(revisoes.conferir, p["slug"], cfg, str(corpo.get("ref", "")), str(corpo.get("resultado", "")),
                                       str(corpo.get("nota", "")), "dono")
    except ValueError as e:
        return _erro(str(e))
    request.app[K_CACHE].clear()
    return _json({"ok": True, "item": item})


async def api_decisoes(request):
    p = _projeto_ou_404(request)
    mem = await asyncio.to_thread(memoria.listar, p["slug"], p["caminho"])
    achadas = [{"id": i["id"], "titulo": i["titulo"], "descricao": i["descricao"], "regra": i["regra"], "decisao": i["decisao"], "plano": i["plano"],
                "origem": i["origem"], "modificado": i["modificado"]} for i in mem["itens"]
              if (i["regra"] or i["decisao"]) and i["origem"] == "memoria" and i["titulo"] != "MEMORY.md"]       # o índice só aponta para os arquivos
    return _json({"registradas": decisoes.listar(p["slug"]), "dos_arquivos": achadas})


async def api_decisao_nova(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    try:
        item = decisoes.registrar(p["slug"], str(corpo.get("texto", "")), str(corpo.get("tipo", "decisao")), str(corpo.get("origem", "dono")))
    except ValueError as e:
        return _erro(str(e))
    return _json({"ok": True, "item": item})



async def api_analise(request):
    slug = _escopo_ou_404(request)
    return _json(await asyncio.to_thread(analise.ler, slug, config.ler_config()))


async def api_analise_rodar(request):
    slug = _escopo_ou_404(request)
    try:
        d = await asyncio.to_thread(analise.executar, slug, config.ler_config())
    except ValueError as e:
        return _erro(str(e), 404)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "resumo": d["resumo"], **analise.ler(slug, config.ler_config())})


async def api_proposta(request):
    slug = _escopo_ou_404(request)
    corpo = await _corpo(request)
    acao, pid = str(corpo.get("acao", "")), request.match_info["pid"]
    try:
        if acao in ("aprovar", "descartar"):
            propostas.decidir(slug, pid, acao == "aprovar", str(corpo.get("nota", "")), "dono")
        elif acao == "reabrir":
            propostas.reabrir(slug, pid)
        else:
            return _erro("ação precisa ser aprovar, descartar ou reabrir")
    except ValueError as e:
        return _erro(str(e), 404)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "propostas": propostas.listar(slug), "tarefas": propostas.tarefas(slug)})


async def api_tarefa(request):
    slug = _escopo_ou_404(request)
    corpo = await _corpo(request)
    try:
        propostas.concluir_tarefa(slug, request.match_info["tid"], str(corpo.get("nota", "")))
    except ValueError as e:
        return _erro(str(e), 404)
    request.app[K_CACHE].clear()
    return _json({"ok": True, "tarefas": propostas.tarefas(slug)})


async def api_novidades(request):
    return _json(await asyncio.to_thread(novidades.montar, config.ler_config()))


async def api_novidades_procurar(request):
    """Consulta páginas públicas de releases (só quando a pessoa clica). Não manda nada do projeto."""
    try:
        d = await asyncio.to_thread(novidades.procurar, config.ler_config())
    except Exception as e:
        return _json({"ok": False, "erro": f"não consegui consultar agora ({type(e).__name__})"})
    request.app[K_CACHE].clear()
    return _json({"ok": True, **d})


async def api_novidades_visto(request):
    corpo = await _corpo(request)
    fid = corpo.get("id")
    novidades.marcar_visto(fid if isinstance(fid, str) and re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,40}", fid) else None)
    return _json({"ok": True, **novidades.montar(config.ler_config())})


async def api_inventario(request):
    p = _projeto_ou_404(request)
    return _json(await asyncio.to_thread(inventario.montar, p["slug"], p["caminho"], config.ler_config()))


async def api_agentes_previa(request):
    p = _projeto_ou_404(request)
    return _json({"previa": regras_agentes.previa_existente(p["slug"])})


async def api_agentes_previa_gerar(request):
    """Grava a PRÉVIA dos agentes por tipo em ~/.cerebro/projetos/<slug>/previa_agentes (nunca dentro do projeto)."""
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    try:
        d = await asyncio.to_thread(regras_agentes.gerar_previa, p["slug"], p["nome"], cfg["agentes_regras"])
    except ValueError as e:
        return _erro(str(e))
    return _json({"ok": True, "previa": d})


async def api_departamentos(request):
    p = _projeto_ou_404(request)
    cfg = config.ler_config()
    return _json({"atual": departamentos.do_projeto(cfg, p["slug"]), "cores": departamentos.deptos.CORES})


async def api_departamentos_salvar(request):
    p = _projeto_ou_404(request)
    corpo = await _corpo(request)
    try:
        limpa = await asyncio.to_thread(departamentos.salvar, p["slug"], corpo.get("conf"))
    except ValueError as e:
        return _erro(str(e))
    # a página do mapa muda com os departamentos: refaz agora, em segundo plano
    if (Path(p["caminho"]) / "graphify-out" / "graph.json").is_file():
        asyncio.get_running_loop().run_in_executor(None, mapa_auto.gerar_agora, p["slug"], p["caminho"])
    request.app[K_CACHE].clear()
    return _json({"ok": True, "atual": limpa or departamentos.do_projeto(config.ler_config(), p["slug"])})
