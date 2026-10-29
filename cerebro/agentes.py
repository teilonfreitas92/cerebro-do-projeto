"""Agentes ao vivo: árvore sessão -> subagentes com estado, modelo, descrição, ferramentas e tokens.

Fontes (todas SOMENTE LEITURA):
  * transcrições JSONL e .meta.json dos subagentes (ver indice.py);
  * `claude agents --json` (visão oficial das sessões abertas; "research preview": se falhar ou mudar, é ignorado);
  * eventos dos ganchos (hooks) do Claude Code, se instalados (ganchos_eventos.aplicar): instantâneos e mais precisos que a
    data do arquivo. Cada nó diz de onde veio o estado: fonte = "hooks" ou "arquivos" (a leitura dos arquivos é a reserva).
Estado:  trabalhando = escreveu há pouco (ou a sessão está "busy" no claude agents)
         parado      = aberta/não terminou, mas sem escrever há um tempo
         terminou    = o subagente marcou finished, ou a sessão não está mais aberta e ficou parada há tempo
"""
import json
import os
import shutil
import subprocess
import threading
import time

from . import custos, ganchos_eventos, indice, regras_agentes, revisoes

JANELA_TRABALHANDO = 60          # segundos sem escrever para deixar de ser "trabalhando"
JANELA_SESSAO_ABERTA = 15 * 60   # sessão sem escrever há mais que isto e fora do claude agents: terminou
_cache_ca = {"t": 0.0, "v": None}
_trava_ca = threading.Lock()


def claude_agents():
    """Saída de `claude agents --json` (lista) ou None se não existir/falhar. Cache de 6 s."""
    with _trava_ca:
        if time.time() - _cache_ca["t"] < 6:
            return _cache_ca["v"]
        v = None
        exe = shutil.which("claude")
        if exe:
            try:
                r = subprocess.run([exe, "agents", "--json"], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=10, creationflags=0x08000000 if os.name == "nt" else 0)
                if r.returncode == 0:
                    d = json.loads(r.stdout)
                    if isinstance(d, list):
                        v = d
            except (OSError, subprocess.SubprocessError, ValueError):
                v = None
        _cache_ca.update(t=time.time(), v=v)
        return v


def _estado_sessao(mtime, ca):
    """ca = item do claude agents para esta sessão (ou None)."""
    agora = time.time()
    if ca:
        return "trabalhando" if str(ca.get("status")) == "busy" else "parado"
    return "trabalhando" if agora - mtime < JANELA_TRABALHANDO else ("parado" if agora - mtime < JANELA_SESSAO_ABERTA else "terminou")


def _estado_sub(mtime, meta):
    return indice.estado_subagente(mtime, meta)


def _modelo_principal(ind):
    m = ind.get("modelos") or {}
    return max(m, key=m.get) if m else ""


def _resumo_arquivo(slug, arq, ind, precos, tokens):
    """Pedaço comum de sessão e subagente."""
    ferr = sorted((ind.get("tools") or {}).items(), key=lambda kv: -kv[1])
    return {
        "rel": arq["rel"], "id": arq["id"], "tipo": arq["tipo"], "sessao": arq["sessao"],
        "mtime": arq["mtime"], "tam": arq["tam"], "inicio": ind.get("inicio"), "fim": ind.get("fim"),
        "modelo": _modelo_principal(ind), "ferramentas_total": sum(ind.get("tools", {}).values()),
        "ferramentas": ferr[:6], "tokens": tokens.get("tokens") if tokens else 0,
        "custo": tokens.get("custo") if tokens else None, "mensagens": tokens.get("mensagens") if tokens else 0,
        "indexado": True,
    }


def montar(slug, precos, gestora_id, horas=24, todas=False, cfg=None):
    """Árvore para a tela 'Agentes ao vivo'. Por padrão só sessões ativas nas últimas 'horas' (e a gestora, sempre).
    Com 'cfg', cada subagente mostra a regra de tarefa que valeu (tipo -> modelo -> revisor) e se já foi conferido."""
    cfg = cfg or {"gestoras": {}, "agentes_regras": []}
    regras = cfg.get("agentes_regras") or []
    conferencias = revisoes.resultados(slug)
    arquivos = indice.listar_arquivos(slug)
    sessoes = [a for a in arquivos if a["tipo"] == "sessao"]
    subs = {}
    for a in arquivos:
        if a["tipo"] == "subagente":
            subs.setdefault(a["sessao"], []).append(a)
    ca_lista = claude_agents()
    ca_por_id = {c.get("sessionId"): c for c in (ca_lista or []) if isinstance(c, dict)}
    corte = time.time() - horas * 3600
    agreg = custos.agregar(slug, precos)["por_arquivo"]
    saida = []
    for s in sessoes:
        ultimo = max([s["mtime"]] + [x["mtime"] for x in subs.get(s["id"], [])])
        eh_gestora = s["id"] == gestora_id
        if not (todas or eh_gestora or ultimo >= corte or s["id"] in ca_por_id):
            continue
        ind = indice.indice_se_existe(slug, s["rel"]) or {}
        acc = agreg.get(s["rel"])
        tok = {"tokens": custos.total_tokens(acc) if acc else 0, "custo": acc["custo"] if acc and not acc["sem_preco"] else None,
               "mensagens": acc["mensagens"] if acc else 0}
        no = _resumo_arquivo(slug, s, ind, precos, tok)
        ca = ca_por_id.get(s["id"])
        tit = indice.titulo_sessao(slug, s["id"], cfg, ind)
        no.update(
            titulo=tit["titulo"], titulo_fonte=tit["fonte"], titulo_original=tit["original"], resumo=tit["resumo"],
            primeira=ind.get("primeira") or "", ramo=ind.get("branch") or "", gestora=eh_gestora,
            estado=_estado_sessao(s["mtime"], ca), aberta=bool(ca), pid=ca.get("pid") if ca else None,
            mtime=max(s["mtime"], 0), ultimo=ultimo, subagentes=[],
        )
        for a in sorted(subs.get(s["id"], []), key=lambda x: -x["mtime"]):
            if not (todas or eh_gestora or a["mtime"] >= corte):
                continue
            meta = indice.ler_meta(slug, a)
            sind = indice.indice_se_existe(slug, a["rel"]) or {}
            sacc = agreg.get(a["rel"])
            stok = {"tokens": custos.total_tokens(sacc) if sacc else 0,
                    "custo": sacc["custo"] if sacc and not sacc["sem_preco"] else None, "mensagens": sacc["mensagens"] if sacc else 0}
            sub = _resumo_arquivo(slug, a, sind, precos, stok)
            sub.update(descricao=str(meta.get("description") or sind.get("primeira") or "(sem descrição)"),
                       tipo_agente=str(meta.get("agentType") or ""), nivel=meta.get("spawnDepth"),
                       modelo=sub["modelo"] or str(meta.get("model") or ""), estado=_estado_sub(a["mtime"], meta),
                       delegado_pelo_gestor=eh_gestora)
            sub["regra"] = regras_agentes.aplicar(sub["descricao"], sub["tipo_agente"], sub["modelo"], regras)
            if eh_gestora:
                sub["conferencia"] = conferencias.get(a["id"]) or ("a_conferir" if sub["estado"] == "terminou" else "")
            no["subagentes"].append(sub)
        # a sessão está trabalhando se algum subagente dela está
        if no["estado"] != "trabalhando" and any(x["estado"] == "trabalhando" for x in no["subagentes"]):
            no["tem_filho_trabalhando"] = True
        saida.append(no)
    dados = {"sessoes": saida, "claude_agents": ca_lista is not None,
             "trabalhando": sum(1 for n in saida for x in [n] + n["subagentes"] if x["estado"] == "trabalhando"),
             "indexando": indice.estado(slug).progresso["rodando"]}
    ganchos_eventos.aplicar(slug, dados)       # eventos dos ganchos do Claude Code (se houver) valem mais que a data do arquivo
    ordem = {"trabalhando": 0, "parado": 1, "terminou": 2}
    saida.sort(key=lambda n: (not n["gestora"], ordem.get(n["estado"], 1), -n["ultimo"]))
    return dados


def contar_ativos(slug):
    """Quantos agentes (sessões + subagentes) escreveram na última janela. Só olha datas dos arquivos: barato."""
    corte = time.time() - JANELA_TRABALHANDO
    return sum(1 for a in indice.listar_arquivos(slug) if a["mtime"] >= corte)
