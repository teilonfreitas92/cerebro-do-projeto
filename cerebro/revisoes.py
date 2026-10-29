"""Fila "a conferir": a revisão que o gestor faz de CADA subagente que terminou.

Regra do dono (qualidade acima de economia): delegar nunca dispensa a verificação do gestor. Todo subagente da sessão
gestora que TERMINOU vira um item "a conferir" até o gestor marcar o resultado:
    aprovado   o trabalho serviu como veio (conta como "aprovado de primeira")
    corrigido  o gestor precisou corrigir ou refazer parte
    recusado   o trabalho não serviu
    dispensado só para limpar itens antigos (não entra nas contas)
Os dados ficam em ~/.cerebro/projetos/<slug>/revisoes.json. Marca-se pela página ou por `python cerebro_cli.py conferir`.
A taxa de "aprovado de primeira" por modelo (Haiku/Sonnet/Opus) é a base para escolher o modelo de cada tipo de tarefa.
"""
import time

from . import armazem, config, custos, indice, regras_agentes

RESULTADOS = ("aprovado", "corrigido", "recusado", "dispensado")
PARADO_APOS = 24 * 3600          # item a conferir há mais de 24 h é destacado como "parado"


def _arquivo(slug):
    return config.pasta_projeto(slug) / "revisoes.json"


def _dados(slug):
    d = armazem.ler_json(_arquivo(slug), {"v": 1, "itens": {}})
    if not isinstance(d, dict) or not isinstance(d.get("itens"), dict):
        return {"v": 1, "itens": {}}
    return d


def resultados(slug):
    """id do subagente -> resultado já marcado."""
    return {k: v.get("resultado") for k, v in _dados(slug)["itens"].items()}


def _gestora(cfg, slug):
    return ((cfg.get("gestoras") or {}).get(slug) or {}).get("conversa", "")


def _terminados(slug, gestora_id, desde=0.0, ler_modelo=False):
    """Subagentes da sessão gestora que terminaram (pelo estado do Claude Code ou por ficarem parados), mais novos que 'desde'."""
    saida = []
    for a in indice.listar_arquivos(slug):
        if a["tipo"] != "subagente" or a["sessao"] != gestora_id or a["mtime"] < desde:
            continue
        meta = indice.ler_meta(slug, a)
        if indice.estado_subagente(a["mtime"], meta) != "terminou":
            continue
        item = {"id": a["id"], "rel": a["rel"], "descricao": str(meta.get("description") or "(sem descrição)"),
                "tipo_agente": str(meta.get("agentType") or ""), "terminou_em": a["mtime"], "tam": a["tam"], "modelo": ""}
        if ler_modelo:
            ind = indice.indice_se_existe(slug, a["rel"])
            if ind is None:
                try:
                    ind = indice.indice_do_arquivo(slug, a)
                except OSError:
                    ind = {}
            m = ind.get("modelos") or {}
            item["modelo"] = max(m, key=m.get) if m else str(meta.get("model") or "")
        saida.append(item)
    return saida


def _estatisticas(itens):
    """Por família de modelo: quantos conferidos e % aprovado de primeira (dispensados não contam)."""
    por = {}
    for it in itens:
        r = it.get("resultado")
        if r not in ("aprovado", "corrigido", "recusado"):
            continue
        f = it.get("familia") or regras_agentes.familia(it.get("modelo")) or "outro"
        b = por.setdefault(f, {"modelo": f, "total": 0, "aprovado": 0, "corrigido": 0, "recusado": 0})
        b["total"] += 1
        b[r] += 1
    saida = []
    for f, b in por.items():
        b["pct_primeira"] = round(100 * b["aprovado"] / b["total"]) if b["total"] else None
        saida.append(b)
    saida.sort(key=lambda b: -b["total"])
    return saida


def fila(slug, cfg, agora=None):
    """Tudo que a aba 'A conferir' mostra."""
    agora = agora or time.time()
    gid = _gestora(cfg, slug)
    dias = int(cfg.get("revisao_dias") or 7)
    dados = _dados(slug)
    itens = dados["itens"]
    conferidos = sorted(itens.values(), key=lambda x: -(x.get("conferido_em") or 0))
    base = {"gestora": bool(gid), "janela_dias": dias, "conferidos": conferidos[:200], "por_modelo": _estatisticas(conferidos)}
    contadores = {"a_conferir": 0, "parados": 0, "aprovados": 0, "corrigidos": 0, "recusados": 0,
                  "conferidos": sum(1 for x in conferidos if x.get("resultado") in ("aprovado", "corrigido", "recusado"))}
    for x in conferidos:
        chave = {"aprovado": "aprovados", "corrigido": "corrigidos", "recusado": "recusados"}.get(x.get("resultado"))
        if chave:
            contadores[chave] += 1
    if not gid:
        return {**base, "pendentes": [], "contadores": contadores, "antigos": 0}
    corte = agora - dias * 86400
    pendentes, antigos = [], 0
    precos = cfg.get("precos") or {}
    agreg = custos.agregar(slug, precos)["por_arquivo"] if indice.estado(slug).arquivos else {}
    for it in _terminados(slug, gid, 0.0, ler_modelo=False):
        if it["id"] in itens:
            continue
        if it["terminou_em"] < corte:
            antigos += 1
            continue
        ind = indice.indice_se_existe(slug, it["rel"])
        if ind is None:
            try:
                ind = indice.indice_do_arquivo(slug, {"rel": it["rel"]})
            except OSError:
                ind = {}
        m = ind.get("modelos") or {}
        it["modelo"] = max(m, key=m.get) if m else ""
        it["familia"] = regras_agentes.familia(it["modelo"])
        acc = agreg.get(it["rel"])
        it["tokens"] = custos.total_tokens(acc) if acc else 0
        it["custo"] = acc["custo"] if acc and not acc["sem_preco"] else None
        it["regra"] = regras_agentes.aplicar(it["descricao"], it["tipo_agente"], it["modelo"], cfg.get("agentes_regras"))
        it["parado"] = agora - it["terminou_em"] > PARADO_APOS
        pendentes.append(it)
    pendentes.sort(key=lambda x: x["terminou_em"])             # o mais antigo primeiro: é o que está esperando há mais tempo
    contadores["a_conferir"] = len(pendentes)
    contadores["parados"] = sum(1 for x in pendentes if x["parado"])
    return {**base, "pendentes": pendentes, "contadores": contadores, "antigos": antigos}


def contagem(slug, cfg, agora=None):
    """Só os números (para o painel geral e para a caixa 'Precisa de você'). Não lê índice nem conversas."""
    agora = agora or time.time()
    gid = _gestora(cfg, slug)
    if not gid:
        return {"a_conferir": 0, "parados": 0}
    corte = agora - int(cfg.get("revisao_dias") or 7) * 86400
    itens = _dados(slug)["itens"]
    n = parados = 0
    for it in _terminados(slug, gid, corte):
        if it["id"] in itens:
            continue
        n += 1
        if agora - it["terminou_em"] > PARADO_APOS:
            parados += 1
    return {"a_conferir": n, "parados": parados}


def _achar(slug, cfg, ref):
    """Resolve 'id completo', 'começo do id (4+ letras)' ou 'trecho da descrição' para UM item. Levanta ValueError se não achar
    ou se ficar ambíguo (a mensagem lista as opções)."""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("informe o id ou um trecho da descrição do subagente")
    gid = _gestora(cfg, slug)
    todos = {it["id"]: it for it in _terminados(slug, gid, 0.0)} if gid else {}
    for k, v in _dados(slug)["itens"].items():          # os já conferidos (mesmo que o arquivo tenha sido apagado) também valem
        todos.setdefault(k, {"id": k, "rel": v.get("rel", ""), "descricao": v.get("descricao", ""), "tipo_agente": v.get("tipo_agente", ""),
                             "terminou_em": v.get("terminou_em") or 0, "modelo": v.get("modelo", "")})
    baixo = ref.lower()
    if ref in todos:
        return todos[ref]
    por_id = [it for it in todos.values() if len(baixo) >= 4 and it["id"].lower().startswith(baixo)]
    if len(por_id) == 1:
        return por_id[0]
    candidatos = por_id or [it for it in todos.values() if baixo in it["descricao"].lower()]
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        raise ValueError(f"nenhum subagente terminado casa com {ref!r}")
    candidatos.sort(key=lambda x: -x["terminou_em"])
    lista = "; ".join(f"{c['id'][:10]} ({c['descricao'][:50]})" for c in candidatos[:8])
    raise ValueError(f"{len(candidatos)} subagentes casam com {ref!r}; use o id: {lista}")


def conferir(slug, cfg, ref, resultado, nota="", por="gestor"):
    """Marca um subagente como conferido. Marcar de novo atualiza (o anterior fica em 'historico')."""
    if resultado not in RESULTADOS:
        raise ValueError("resultado precisa ser: " + ", ".join(RESULTADOS))
    nota = (nota or "").strip()[:1000]
    por = (por or "gestor").strip()[:40] or "gestor"
    it = _achar(slug, cfg, ref)
    modelo = it.get("modelo") or ""
    if not modelo and it.get("rel"):
        ind = indice.indice_se_existe(slug, it["rel"])
        if ind is None:
            try:
                ind = indice.indice_do_arquivo(slug, {"rel": it["rel"]})
            except OSError:
                ind = {}
        m = ind.get("modelos") or {}
        modelo = max(m, key=m.get) if m else ""
    regra = regras_agentes.aplicar(it.get("descricao"), it.get("tipo_agente"), modelo, cfg.get("agentes_regras")).get("regra", "")

    def mudar(d):
        ant = d["itens"].get(it["id"])
        novo = {"id": it["id"], "rel": it.get("rel", ""), "descricao": it.get("descricao", ""), "tipo_agente": it.get("tipo_agente", ""),
                "modelo": modelo, "familia": regras_agentes.familia(modelo), "regra": regra, "terminou_em": it.get("terminou_em"),
                "resultado": resultado, "nota": nota, "conferido_em": time.time(), "por": por}
        if ant:
            novo["historico"] = (ant.get("historico") or []) + [{k: ant.get(k) for k in ("resultado", "nota", "conferido_em", "por")}]
        d["itens"][it["id"]] = novo
        return d

    armazem.atualizar_json(_arquivo(slug), {"v": 1, "itens": {}}, mudar)
    return _dados(slug)["itens"][it["id"]]


def dispensar_antigos(slug, cfg, agora=None):
    """Limpa de uma vez os terminados mais velhos que a janela (marca 'dispensado'). Devolve quantos."""
    agora = agora or time.time()
    gid = _gestora(cfg, slug)
    if not gid:
        return 0
    corte = agora - int(cfg.get("revisao_dias") or 7) * 86400
    achados = [it for it in _terminados(slug, gid, 0.0) if it["terminou_em"] < corte]

    def mudar(d):
        for it in achados:
            if it["id"] in d["itens"]:
                continue
            d["itens"][it["id"]] = {"id": it["id"], "rel": it["rel"], "descricao": it["descricao"], "tipo_agente": it["tipo_agente"],
                                    "modelo": "", "familia": "", "regra": "", "terminou_em": it["terminou_em"], "resultado": "dispensado",
                                    "nota": "antigo: anterior à janela da fila", "conferido_em": agora, "por": "cerebro"}
        return d

    antes = len(_dados(slug)["itens"])
    armazem.atualizar_json(_arquivo(slug), {"v": 1, "itens": {}}, mudar)
    return len(_dados(slug)["itens"]) - antes
