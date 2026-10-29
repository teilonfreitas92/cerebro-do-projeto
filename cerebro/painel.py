"""Peças menores do painel: limites do plano, ferramentas do projeto e a fila "precisa de você"."""
import json
import os
from pathlib import Path

from . import bastao, config, custos, indice, mapa_auto, memoria, memoria_avisos, projetos, propostas, revisoes
from . import gestora_troca, orcamento, tarefas_gestor

# Onde a sua statusLine grava os limites do plano (opcional; pode faltar: tudo é opcional). Procura, nesta ordem: a variável
# CEREBRO_STATUS, config.json > "arquivo_status", ~/.cerebro/claude_status.json e ~/.claude/claude_status.json.
def _candidatos_status():
    c = []
    extra = os.environ.get("CEREBRO_STATUS")
    if extra:
        c.append(Path(extra))
    try:
        escolhido = str(config.ler_config().get("arquivo_status") or "").strip()
    except Exception:
        escolhido = ""
    if escolhido:
        c.append(Path(escolhido))
    c += [config.CASA / "claude_status.json", config.CLAUDE / "claude_status.json"]
    return c


def _achar(d, nome, profundidade=0):
    """Procura uma chave em qualquer nível do JSON (o formato da statusLine pode mudar)."""
    if profundidade > 5 or not isinstance(d, (dict, list)):
        return None
    if isinstance(d, dict):
        if nome in d:
            return d[nome]
        for v in d.values():
            r = _achar(v, nome, profundidade + 1)
            if r is not None:
                return r
    else:
        for v in d[:20]:
            r = _achar(v, nome, profundidade + 1)
            if r is not None:
                return r
    return None


def limites():
    """Anéis de limite do plano (5 horas / 7 dias / janela de contexto) lidos do arquivo da statusLine, se houver."""
    for c in _candidatos_status():
        try:
            d = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        def pct(chave, d=d):
            v = _achar(d, chave)
            if isinstance(v, dict):
                p = v.get("used_percentage")
                return {"percentual": p if isinstance(p, (int, float)) else None, "renova_em": v.get("resets_at")}
            return None
        r = {"disponivel": True, "arquivo": str(c), "atualizado": c.stat().st_mtime,
             "cinco_horas": pct("five_hour"), "sete_dias": pct("seven_day")}
        ctx = _achar(d, "context_window")
        if isinstance(ctx, dict) and isinstance(ctx.get("used_percentage"), (int, float)):
            r["contexto"] = {"percentual": ctx["used_percentage"]}
        return r
    return {"disponivel": False}


# ---------------------------------------------------------------------------------------------------------------
# Fila "precisa de você"
# ---------------------------------------------------------------------------------------------------------------
def fila(cfg):
    """Itens que pedem uma decisão ou ação do dono (ou do gestor): conferência de subagentes, tarefas aprovadas, mapa, configuração."""
    itens = []
    projs = [p for p in projetos.descobrir() if not p["oculto"]]
    sem_preco = set()
    sem_gestora, sem_mapa = [], []
    for p in projs:
        slug = p["slug"]
        ativo = bool(indice.listar_arquivos(slug))
        if ativo and slug not in (cfg.get("gestoras") or {}):
            sem_gestora.append(p)
        m = projetos.estado_mapa(p["caminho"], slug)
        if not m["graphify"]:
            sem_mapa.append(p)
        elif not m["gerado"]:
            itens.append({"nivel": "acao", "projeto": slug, "titulo": f"{p['nome']}: página do mapa não gerada",
                          "texto": "O Graphify já tem o mapa; o vigia gera sozinho com o servidor aberto (ou use o botão na aba Mapa).", "aba": "mapa"})
        else:
            v = mapa_auto.estado(slug)
            if v.get("ultimo_erro"):
                itens.append({"nivel": "aviso", "projeto": slug, "titulo": f"{p['nome']}: o gerador do mapa está falhando",
                              "texto": v["ultimo_erro"][-160:], "aba": "mapa"})
            elif m.get("defasado"):
                itens.append({"nivel": "aviso", "projeto": slug, "titulo": f"{p['nome']}: mapa mais velho que o último commit",
                              "texto": "O graph.json do Graphify não acompanhou o último commit. Confira os ganchos do git do projeto.", "aba": "mapa"})
        mem = memoria.listar(slug, p["caminho"])
        for a in mem["avisos"]:
            itens.append({"nivel": "aviso", "projeto": slug, "titulo": f"{p['nome']}: memória pesada", "texto": a, "aba": "memoria"})
        for extra in (memoria_avisos.itens_fila, bastao.itens_fila, gestora_troca.itens_fila):   # memória, conversa longa, troca da gestora
            try:
                itens.extend(extra(p, cfg))
            except (OSError, ValueError):
                pass
        conf = revisoes.contagem(slug, cfg)
        if conf["a_conferir"]:
            itens.append({"nivel": "acao", "projeto": slug,
                          "titulo": f"{p['nome']}: {conf['a_conferir']} subagente(s) a conferir",
                          "texto": "O gestor ainda não conferiu o trabalho deles" + (f" ({conf['parados']} esperando há mais de 24 h)" if conf["parados"] else "")
                                   + ". Nada de subagente entra no projeto sem essa conferência.", "aba": "conferir"})
        pc = propostas.contagem(slug)
        if pc["tarefas_abertas"]:
            itens.append({"nivel": "acao", "projeto": slug, "titulo": f"{p['nome']}: {pc['tarefas_abertas']} tarefa(s) aprovada(s) para o gestor",
                          "texto": "Propostas que você aprovou e ainda não foram feitas.", "aba": "analise"})
        elif pc["novas"]:
            itens.append({"nivel": "info", "projeto": slug, "titulo": f"{p['nome']}: {pc['novas']} proposta(s) de melhoria para decidir",
                          "texto": "Vieram da análise sem IA do Cérebro. Aprove ou descarte na aba Análise.", "aba": "analise"})
        itens += tarefas_gestor.itens_fila(p)
        if ativo:
            est = indice.estado(slug)
            for ind in list(est.arquivos.values()):
                for modelo in (ind.get("modelos") or {}):
                    if custos.preco_do_modelo(modelo, cfg["precos"]) is None:
                        sem_preco.add(modelo)
    itens += orcamento.itens_fila(cfg)
    if sem_gestora:
        itens.append({"nivel": "acao", "projeto": sem_gestora[0]["slug"], "titulo": "Escolha a sessão gestora",
                      "texto": "Projetos sem gestora: " + ", ".join(p["nome"] for p in sem_gestora)
                               + ". Sem ela, os agentes não aparecem como 'delegados pelo gestor' e a fila 'a conferir' fica vazia.", "aba": "configuracoes"})
    if sem_preco:
        itens.append({"nivel": "acao", "projeto": "", "titulo": "Preço a conferir",
                      "texto": "Sem preço na tabela para: " + ", ".join(sorted(sem_preco)) + ". Só os tokens são contados até você preencher em Configurações.",
                      "aba": ""})
    pcer = propostas.contagem(propostas.ESCOPO_CEREBRO)
    if pcer["novas"] or pcer["tarefas_abertas"]:
        itens.append({"nivel": "info", "projeto": "", "titulo": "Propostas do próprio Cérebro e novidades",
                      "texto": f"{pcer['novas']} para decidir, {pcer['tarefas_abertas']} tarefa(s) aprovada(s). Abra a aba Novidades de qualquer projeto.", "aba": ""})
    if sem_mapa:
        itens.append({"nivel": "info", "projeto": "", "titulo": "Projetos sem mapa do Graphify",
                      "texto": ", ".join(p["nome"] for p in sem_mapa) + ". Gerar o mapa entra na instalação adaptativa (aba Inventário), com a sua aprovação.",
                      "aba": ""})
    if not limites()["disponivel"]:
        itens.append({"nivel": "info", "projeto": "", "titulo": "Limites do plano indisponíveis",
                      "texto": "Não achei o arquivo claude_status.json da statusLine; os anéis de limite 5 h / 7 dias não aparecem.", "aba": ""})
    try:                                            # backup atrasado, falhou, nunca feito ou encolheu (backup.py)
        from . import backup
        itens += backup.alertas()
    except Exception:
        pass
    ordem = {"acao": 0, "aviso": 1, "info": 2}
    itens.sort(key=lambda i: ordem[i["nivel"]])
    return itens
