"""Tarefas para o gestor: o dono cria na página, o gestor recebe, trabalha, entrega e o dono confere.

Convive com as tarefas que nascem de propostas aprovadas (propostas.py): é o MESMO arquivo, ~/.cerebro/projetos/<slug>/tarefas.json.
Formato antigo preservado: {"v": 1, "itens": {id: tarefa}}; a tarefa de proposta tem id "t-<proposta>" e estado "aberta"/"feita".
Aqui o ciclo é: nova -> recebida (o gestor leu) -> andamento (com qual agente/sessão) -> conferir -> feita ou recusada, com o histórico
de quem mudou e quando. "aberta" (formato antigo) vale como "nova". Nada é migrado à força: o que falta numa tarefa antiga é
preenchido na leitura (normalizar), e o arquivo só muda quando alguém mexe naquela tarefa.

A tarefa guarda os "pontos do mapa" (grupo, arquivo ou função escolhidos na página ou no painel do mapa) e o tipo de agente
(regras_agentes: modelo e quem revisa). Tudo fica só em ~/.cerebro; nada é escrito no projeto.
"""
import json
import re
import secrets
import time

from . import armazem, config, projetos, propostas, regras_agentes
from .segredos import mascarar

ESTADOS = ("nova", "recebida", "andamento", "conferir", "feita", "recusada")
ABERTOS = ("nova", "recebida", "andamento", "conferir")
FINAIS = ("feita", "recusada")
ROTULOS = {"nova": "nova", "recebida": "recebida pelo gestor", "andamento": "em andamento", "conferir": "a conferir",
           "feita": "feita", "recusada": "recusada"}
PRIORIDADES = ("baixa", "normal", "alta", "urgente")
MAX_TITULO, MAX_DESCRICAO, MAX_NOTA, MAX_PONTOS = 160, 4000, 500, 20
_PADRAO = {"v": 1, "itens": {}}


def _arq(slug):
    return propostas._arq_tarefas(slug)


# ---------------------------------------------------------------------------------------------------------------
# Leitura tolerante (tarefas antigas ganham os campos novos só na memória)
# ---------------------------------------------------------------------------------------------------------------
def estado_de(t):
    """Estado dentro da lista nova. 'aberta' (formato antigo) é 'nova'; o que não se reconhece também."""
    e = t.get("estado")
    return e if e in ESTADOS else "nova"


def normalizar(t):
    """Cópia da tarefa com todos os campos preenchidos (tarefa antiga, de proposta, não tinha prioridade, pontos nem histórico)."""
    n = dict(t)
    n["estado"] = estado_de(t)
    n.setdefault("descricao", t.get("motivo") or "")
    n.setdefault("prioridade", "normal")
    n.setdefault("pontos", [])
    n.setdefault("agente_tipo", "")
    n.setdefault("agente_atual", "")
    n.setdefault("criada_por", "dono" if t.get("origem") == "dono" else "proposta aprovada")
    n["da_proposta"] = bool(t.get("proposta_id"))
    hist = t.get("historico")
    if not isinstance(hist, list):
        hist = [{"em": t.get("criada_em"), "por": n["criada_por"], "de": None, "para": "nova", "agente": "", "nota": t.get("nota") or ""}]
        if n["estado"] == "feita" or t.get("feita_em"):
            hist.append({"em": t.get("feita_em"), "por": "gestor", "de": "nova", "para": "feita", "agente": "", "nota": t.get("nota_final") or ""})
    n["historico"] = hist
    n.setdefault("atualizada_em", hist[-1].get("em") if hist else t.get("criada_em"))
    return n


def info_agente(cfg, agente_tipo):
    """{id, nome, modelo, revisor} da regra de agentes atual (config.json > agentes_regras), ou None."""
    for r in (cfg or {}).get("agentes_regras") or []:
        if r.get("id") == agente_tipo:
            return {"id": r["id"], "nome": r.get("nome", ""), "modelo": r.get("modelo", ""), "revisor": r.get("revisor", "")}
    return None


def _enriquecer(t, cfg):
    n = normalizar(t)
    n["agente"] = info_agente(cfg, n.get("agente_tipo"))
    n["estado_rotulo"] = ROTULOS[n["estado"]]
    return n


def listar(slug, cfg=None, estado=None, prioridade=None, busca=None, incluir_finais=True):
    """Tarefas do projeto, prontas para a tela: abertas primeiro (mais urgentes e mais antigas na frente), depois as finais."""
    cfg = cfg if cfg is not None else config.ler_config()
    d = armazem.ler_json(_arq(slug), _PADRAO)
    brutas = list((d.get("itens") or {}).values()) if isinstance(d, dict) else []
    itens = [_enriquecer(t, cfg) for t in brutas if isinstance(t, dict)]
    if estado:
        itens = [t for t in itens if t["estado"] == estado]
    elif not incluir_finais:
        itens = [t for t in itens if t["estado"] in ABERTOS]
    if prioridade:
        itens = [t for t in itens if t["prioridade"] == prioridade]
    if busca:
        q = busca.strip().lower()
        itens = [t for t in itens if q in (t.get("titulo", "") + " " + t.get("descricao", "") + " " + t.get("id", "")
                                          + " " + " ".join(p.get("nome", "") + " " + p.get("arquivo", "") for p in t["pontos"])).lower()]
    peso = {p: i for i, p in enumerate(reversed(PRIORIDADES))}          # urgente primeiro

    def chave(t):
        if t["estado"] in FINAIS:
            return (1, 0, -(t.get("atualizada_em") or 0))
        return (0, peso.get(t["prioridade"], 9), t.get("criada_em") or 0)

    itens.sort(key=chave)
    return itens


def achar(slug, tid, cfg=None):
    for t in listar(slug, cfg):
        if t["id"] == tid:
            return t
    return None


def contagem(slug):
    """Números para o painel: por estado (tarefas antigas 'aberta' contam como nova) e as abertas que o dono criou."""
    d = armazem.ler_json(_arq(slug), _PADRAO)
    brutas = [t for t in (d.get("itens") or {}).values() if isinstance(t, dict)] if isinstance(d, dict) else []
    c = {e: 0 for e in ESTADOS}
    do_dono = 0
    for t in brutas:
        e = estado_de(t)
        c[e] += 1
        if e in ABERTOS and not t.get("proposta_id"):
            do_dono += 1
    c["abertas"] = sum(c[e] for e in ABERTOS)
    c["do_dono_abertas"] = do_dono
    return c


# ---------------------------------------------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------------------------------------------
def _texto(v, limite, nome, obrigatorio=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ValueError(f"{nome} precisa ser texto")
    v = mascarar(v.strip())[:limite]            # senha colada por engano não fica gravada
    if obrigatorio and not v:
        raise ValueError(f"{nome} é obrigatório")
    return v


def limpar_pontos(pontos):
    """Valida os pontos do mapa vindos da página: {tipo, nome, arquivo, linha, grupo, arquivos}. Devolve lista limpa."""
    if pontos is None:
        return []
    if not isinstance(pontos, list) or len(pontos) > MAX_PONTOS:
        raise ValueError(f"os pontos do mapa precisam ser uma lista de até {MAX_PONTOS}")
    limpos, vistos = [], set()
    for p in pontos:
        if not isinstance(p, dict):
            raise ValueError("ponto do mapa inválido")
        nome = _texto(p.get("nome"), 200, "nome do ponto", True)
        tipo = _texto(p.get("tipo") or "arquivo", 30, "tipo do ponto")
        arquivo = _texto(p.get("arquivo"), 300, "arquivo do ponto")
        linha = p.get("linha")
        linha = linha if isinstance(linha, int) and not isinstance(linha, bool) and 0 < linha < 10_000_000 else None
        arquivos = p.get("arquivos") or []
        if not isinstance(arquivos, list):
            raise ValueError("arquivos do ponto inválidos")
        item = {"tipo": tipo, "nome": nome, "arquivo": arquivo, "linha": linha, "grupo": _texto(p.get("grupo"), 200, "grupo do ponto"),
                "arquivos": [_texto(a, 300, "arquivo do ponto") for a in arquivos[:12] if isinstance(a, str) and a.strip()]}
        chave = (item["tipo"], item["nome"], item["arquivo"])
        if chave in vistos:
            continue
        vistos.add(chave)
        limpos.append(item)
    return limpos


def completar_pontos(slug, pontos):
    """Um ponto de grupo sem lista de arquivos ganha os arquivos principais dele, lidos do mapa gerado (se existir)."""
    for p in pontos:
        if p["tipo"] == "grupo" and not p["arquivos"]:
            p["arquivos"] = arquivos_do_grupo(slug, p["nome"])
    return pontos


def criar(slug, titulo, descricao="", prioridade="normal", pontos=None, agente_tipo="", por="dono", cfg=None, agora=None):
    """Cria a tarefa (estado 'nova'). agente_tipo vazio = o Cérebro sugere pelas palavras do título e da descrição."""
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    titulo = _texto(titulo, MAX_TITULO, "o título", True)
    descricao = _texto(descricao, MAX_DESCRICAO, "a descrição")
    if prioridade not in PRIORIDADES:
        raise ValueError("prioridade precisa ser " + ", ".join(PRIORIDADES))
    pontos = completar_pontos(slug, limpar_pontos(pontos))
    sugerido = False
    agente_tipo = (agente_tipo or "").strip().lower()
    if agente_tipo:
        if info_agente(cfg, agente_tipo) is None:
            raise ValueError("tipo de agente desconhecido (veja a tabela em Configurações)")
    else:
        r = regras_agentes.classificar(titulo + " " + descricao, "", cfg.get("agentes_regras"))
        agente_tipo, sugerido = (r["id"] if r else ""), bool(r)
    por = _texto(por, 40, "quem criou", True)
    tid = "n-" + secrets.token_hex(4)
    tarefa = {"id": tid, "titulo": titulo, "descricao": descricao, "prioridade": prioridade, "pontos": pontos, "agente_tipo": agente_tipo,
              "agente_sugerido": sugerido, "agente_atual": "", "estado": "nova", "origem": "dono", "criada_por": por, "criada_em": agora,
              "atualizada_em": agora, "historico": [{"em": agora, "por": por, "de": None, "para": "nova", "agente": "", "nota": ""}]}

    def mudar(d):
        d.setdefault("itens", {})[tid] = tarefa
        return d

    armazem.atualizar_json(_arq(slug), _PADRAO, mudar)
    return _enriquecer(tarefa, cfg)


def mudar_estado(slug, tid, estado, por="gestor", agente="", nota="", cfg=None, agora=None):
    """Passa a tarefa para outro estado e registra no histórico (quem, quando, com qual agente, nota). Levanta ValueError."""
    if estado not in ESTADOS:
        raise ValueError("estado precisa ser " + ", ".join(ESTADOS))
    agora = agora or time.time()
    por = _texto(por, 40, "quem mudou", True)
    agente = _texto(agente, 80, "o agente")
    nota = _texto(nota, MAX_NOTA, "a nota")

    def mudar(d):
        t = (d.get("itens") or {}).get(tid)
        if not isinstance(t, dict):
            raise ValueError("tarefa não encontrada")
        antes = estado_de(t)
        hist = t.get("historico")
        if not isinstance(hist, list):
            hist = normalizar(t)["historico"]
        hist.append({"em": agora, "por": por, "de": antes, "para": estado, "agente": agente, "nota": nota})
        t["historico"] = hist[-200:]
        t["estado"] = estado
        t["atualizada_em"] = agora
        if agente:
            t["agente_atual"] = agente
        if estado == "feita":
            t.update(feita_em=agora, nota_final=nota)              # os mesmos campos que propostas.concluir_tarefa grava
        elif estado == "nova":
            t["agente_atual"] = ""                                 # voltou para a fila: ninguém está com ela
        return d

    d = armazem.atualizar_json(_arq(slug), _PADRAO, mudar)
    return _enriquecer(d["itens"][tid], cfg if cfg is not None else config.ler_config())


def editar(slug, tid, campos, por="dono", cfg=None, agora=None):
    """Muda título, descrição, prioridade, pontos ou tipo de agente de uma tarefa que ainda não terminou."""
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    novos = {}
    if "titulo" in campos:
        novos["titulo"] = _texto(campos["titulo"], MAX_TITULO, "o título", True)
    if "descricao" in campos:
        novos["descricao"] = _texto(campos["descricao"], MAX_DESCRICAO, "a descrição")
    if "prioridade" in campos:
        if campos["prioridade"] not in PRIORIDADES:
            raise ValueError("prioridade precisa ser " + ", ".join(PRIORIDADES))
        novos["prioridade"] = campos["prioridade"]
    if "pontos" in campos:
        novos["pontos"] = completar_pontos(slug, limpar_pontos(campos["pontos"]))
    if "agente_tipo" in campos:
        a = str(campos["agente_tipo"] or "").strip().lower()
        if a and info_agente(cfg, a) is None:
            raise ValueError("tipo de agente desconhecido (veja a tabela em Configurações)")
        novos.update(agente_tipo=a, agente_sugerido=False)
    if not novos:
        raise ValueError("nada para mudar")
    por = _texto(por, 40, "quem mudou", True)

    def mudar(d):
        t = (d.get("itens") or {}).get(tid)
        if not isinstance(t, dict):
            raise ValueError("tarefa não encontrada")
        if estado_de(t) in FINAIS:
            raise ValueError("tarefa já terminada: reabra antes de editar")
        hist = t.get("historico")
        if not isinstance(hist, list):
            hist = normalizar(t)["historico"]
        hist.append({"em": agora, "por": por, "de": estado_de(t), "para": estado_de(t), "agente": "", "nota": "editou: " + ", ".join(sorted(novos))})
        if "agente_tipo" in novos and not novos["agente_tipo"]:           # voltou para "deixar o Cérebro sugerir"
            r = regras_agentes.classificar(novos.get("titulo", t.get("titulo", "")) + " " + novos.get("descricao", t.get("descricao") or t.get("motivo") or ""),
                                           "", cfg.get("agentes_regras"))
            novos["agente_tipo"], novos["agente_sugerido"] = (r["id"] if r else ""), bool(r)
        t.update(novos)
        t["historico"] = hist[-200:]
        t["atualizada_em"] = agora
        return d

    d = armazem.atualizar_json(_arq(slug), _PADRAO, mudar)
    return _enriquecer(d["itens"][tid], cfg)


# ---------------------------------------------------------------------------------------------------------------
# Texto para o gestor (CLI e gancho da sessão gestora)
# ---------------------------------------------------------------------------------------------------------------
def ponto_em_texto(p):
    nome, arq = p.get("nome", ""), p.get("arquivo", "")
    if p.get("tipo") == "grupo":
        base = f'grupo "{nome}"'
        return base + (": " + ", ".join(p["arquivos"][:6]) + (" ..." if len(p["arquivos"]) > 6 else "") if p.get("arquivos") else "")
    if p.get("tipo") == "arquivo":
        return f"arquivo {arq or nome}"
    local = f" ({arq}{':' + str(p['linha']) if p.get('linha') else ''}{', grupo ' + p['grupo'] if p.get('grupo') else ''})" if arq else ""
    return f'{p.get("tipo") or "item"} "{nome}"{local}'


def _agente_em_texto(t):
    a = t.get("agente")
    if not a:
        return "sem tipo definido (você decide o modelo)"
    return f"{a['nome']} · modelo sugerido {a['modelo']} · quem revisa: {a['revisor']}"


def _aspas(nome):
    return '"' + nome.replace('"', "'") + '"'


def _nome_projeto(slug):
    p = projetos.achar(slug)
    return p["nome"] if p else slug


def texto_detalhado(t, projeto):
    """Uma tarefa por extenso, para o gestor ler (cerebro_cli.py tarefas --novas)."""
    linhas = [f"Tarefa {t['id']}  [prioridade {t['prioridade']}]  {t['titulo']}"]
    if t.get("descricao"):
        linhas.append("  Pedido: " + t["descricao"].replace("\n", "\n          "))
    if t["pontos"]:
        linhas.append("  Pontos do mapa:")
        linhas += ["    - " + ponto_em_texto(p) for p in t["pontos"]]
        arqs = []
        for p in t["pontos"]:
            for a in [p.get("arquivo")] + list(p.get("arquivos") or []):
                if a and a not in arqs:
                    arqs.append(a)
        if arqs:
            linhas.append("  Arquivos envolvidos: " + ", ".join(arqs[:15]) + (" ..." if len(arqs) > 15 else ""))
    else:
        linhas.append("  Pontos do mapa: nenhum (o dono não marcou onde mexer)")
    linhas.append("  Agente: " + _agente_em_texto(t))
    origem = "veio de uma proposta aprovada" if t["da_proposta"] else "criada pelo dono"
    linhas.append(f"  {origem[0].upper() + origem[1:]} {_quando(t.get('criada_em'))}.")
    linhas.append(f"  Para pegar: python cerebro_cli.py tarefa {_aspas(projeto)} {t['id']} --estado recebida --agente <seu nome>")
    return "\n".join(linhas)


def _quando(t):
    if not t:
        return ""
    d = time.time() - t
    if d < 3600:
        return f"há {max(1, int(d // 60))} min"
    if d < 86400:
        return f"há {int(d // 3600)} h"
    return f"há {int(d // 86400)} d"


def texto_novas(slug, cfg=None):
    """Texto completo das tarefas novas (CLI --novas). Vazio se não houver."""
    novas = [t for t in listar(slug, cfg, estado="nova")]
    if not novas:
        return ""
    projeto = _nome_projeto(slug)
    return (f"{len(novas)} tarefa(s) nova(s) para o gestor em {projeto}:\n\n" + "\n\n".join(texto_detalhado(t, projeto) for t in novas)
            + "\n\nMarque o andamento com: python cerebro_cli.py tarefa " + _aspas(projeto)
            + " <id> --estado recebida|andamento|conferir|feita --agente <nome> --nota \"...\"")


def texto_para_contexto(slug, maximo=5):
    """Texto CURTO só com as tarefas novas, para o gancho UserPromptSubmit da sessão gestora injetar no contexto.
    Devolve '' quando não há nenhuma (o gancho não deve escrever nada). Nunca levanta erro."""
    try:
        novas = listar(slug, estado="nova")
        if not novas:
            return ""
        projeto = _nome_projeto(slug)
        linhas = [f"[Cérebro] {len(novas)} tarefa(s) nova(s) do dono para {projeto}. Detalhes: python cerebro_cli.py tarefas {_aspas(projeto)} --novas"]
        for t in novas[:maximo]:
            onde = ""
            if t["pontos"]:
                onde = " | mapa: " + ponto_em_texto(t["pontos"][0]).replace("\n", " ")[:90] + (f" (+{len(t['pontos']) - 1})" if len(t["pontos"]) > 1 else "")
            ag = f" | agente: {t['agente']['modelo']}" if t.get("agente") else ""
            linhas.append(f"- {t['id']} [{t['prioridade']}] {t['titulo'][:90]}{onde}{ag}")
        if len(novas) > maximo:
            linhas.append(f"- ... e mais {len(novas) - maximo}")
        linhas.append(f"Ao pegar uma: python cerebro_cli.py tarefa {_aspas(projeto)} <id> --estado recebida --agente <seu nome>")
        return "\n".join(linhas)
    except Exception:
        return ""


def itens_fila(p):
    """Itens para 'Precisa de você' (painel.fila): só as tarefas que o dono criou (as de proposta já têm o aviso delas)."""
    itens, slug = [], p["slug"]
    cfg = config.ler_config()
    abertas = [t for t in listar(slug, cfg, incluir_finais=False) if not t["da_proposta"]]
    conferir = [t for t in abertas if t["estado"] == "conferir"]
    esperando = [t for t in abertas if t["estado"] == "nova"]
    if conferir:
        itens.append({"nivel": "acao", "projeto": slug, "titulo": f"{p['nome']}: {len(conferir)} tarefa(s) a conferir",
                      "texto": "O gestor disse que terminou. Confira e marque como feita ou recusada: " + "; ".join(t["titulo"][:50] for t in conferir[:3]) + ".",
                      "aba": "tarefas"})
    antigas = [t for t in esperando if time.time() - (t.get("criada_em") or 0) > 24 * 3600]
    if antigas:
        itens.append({"nivel": "aviso", "projeto": slug, "titulo": f"{p['nome']}: {len(antigas)} tarefa(s) esperando o gestor há mais de 24 h",
                      "texto": "O gestor ainda não marcou como recebida. Ele só vê as tarefas novas quando abre uma conversa do projeto com o gancho ligado.",
                      "aba": "tarefas"})
    elif esperando:
        itens.append({"nivel": "info", "projeto": slug, "titulo": f"{p['nome']}: {len(esperando)} tarefa(s) nova(s) para o gestor",
                      "texto": "Criadas por você na página; o gestor as recebe na próxima conversa.", "aba": "tarefas"})
    return itens


# ---------------------------------------------------------------------------------------------------------------
# Pontos do mapa (lidos do dados.js que o gerador do mapa grava em ~/.cerebro/projetos/<slug>/mapa)
# ---------------------------------------------------------------------------------------------------------------
_cache_mapa = {}                    # slug -> (assinatura do arquivo, dados enxutos)


def _dados_mapa(slug):
    """Estrutura enxuta do mapa: {grupos: [(nome, tamanho)], arquivos: [...], itens: [(nome, arq, linha, tipo, grupo)], tipos}. None se não houver."""
    arq = config.CASA / "projetos" / slug / "mapa" / "dados.js"
    try:
        st = arq.stat()
        assinatura = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    c = _cache_mapa.get(slug)
    if c and c[0] == assinatura:
        return c[1]
    try:
        bruto = arq.read_text(encoding="utf-8")
        ini, fim = bruto.index("{"), bruto.rindex("}")
        D = json.loads(bruto[ini:fim + 1])
        nos = D["nos"]
        arquivos, tipos = list(D.get("arquivos") or []), list(D.get("tipos") or [])
        n_arq = len(arquivos)
        itens = []
        for i in range(n_arq, len(nos["n"])):
            a = nos["a"][i]
            itens.append((str(nos["n"][i]), a, nos["l"][i], nos["k"][i], nos["g"][i]))
        arq_grupo = {}
        for i in range(len(nos["n"])):
            a, g = nos["a"][i], nos["g"][i]
            if a >= 0 and 0 <= g < len(D["grupos"]):
                arq_grupo.setdefault(g, {}).setdefault(a, 0)
                arq_grupo[g][a] += 1
        dados = {"grupos": [(g.get("n", ""), g.get("t", 0)) for g in D["grupos"]], "arquivos": arquivos, "itens": itens, "tipos": tipos,
                 "arq_grupo": arq_grupo}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    if len(_cache_mapa) > 4:
        _cache_mapa.clear()
    _cache_mapa[slug] = (assinatura, dados)
    return dados


def arquivos_do_grupo(slug, nome, limite=8):
    """Os arquivos com mais itens dentro do grupo (para dizer ao gestor onde mexer)."""
    m = _dados_mapa(slug)
    if not m:
        return []
    for gi, (n, _t) in enumerate(m["grupos"]):
        if n == nome:
            conta = sorted((m["arq_grupo"].get(gi) or {}).items(), key=lambda kv: -kv[1])
            return [m["arquivos"][a] for a, _c in conta[:limite] if 0 <= a < len(m["arquivos"])]
    return []


def pontos_do_mapa(slug, q="", limite=40):
    """Pontos que a pessoa pode escolher: grupos, arquivos e funções do mapa. Sem busca, só os grupos maiores.
    Devolve {mapa: bool, pontos: [{tipo, nome, arquivo, linha, grupo, arquivos}]}."""
    m = _dados_mapa(slug)
    if not m:
        return {"mapa": False, "pontos": []}
    q = (q or "").strip().lower()
    grupos = [{"tipo": "grupo", "nome": n, "arquivo": "", "linha": None, "grupo": n, "arquivos": []} for n, _t in
              sorted(m["grupos"], key=lambda g: -g[1])]
    if not q:
        return {"mapa": True, "pontos": grupos[:limite]}
    saida = [g for g in grupos if q in g["nome"].lower()][:limite]
    for a in m["arquivos"]:
        if len(saida) >= limite:
            break
        if q in a.lower():
            saida.append({"tipo": "arquivo", "nome": a.rsplit("/", 1)[-1], "arquivo": a, "linha": None, "grupo": "", "arquivos": []})
    if len(saida) < limite:
        achados = [it for it in m["itens"] if q in it[0].lower() and it[1] >= 0]
        achados.sort(key=lambda it: (not it[0].lower().startswith(q), len(it[0])))
        for nome, a, lin, k, g in achados[:limite - len(saida)]:
            tipo = m["tipos"][k] if 0 <= k < len(m["tipos"]) else "item"
            saida.append({"tipo": tipo, "nome": nome, "arquivo": m["arquivos"][a] if 0 <= a < len(m["arquivos"]) else "", "linha": lin or None,
                          "grupo": m["grupos"][g][0] if 0 <= g < len(m["grupos"]) else "", "arquivos": []})
    return {"mapa": True, "pontos": saida}


def opcoes(cfg):
    """O que a tela de nova tarefa precisa: tipos de agente (com modelo e quem revisa), prioridades e estados."""
    return {"agentes": [{"id": r["id"], "nome": r.get("nome", ""), "modelo": r.get("modelo", ""), "revisor": r.get("revisor", "")}
                        for r in cfg.get("agentes_regras") or []],
            "prioridades": list(PRIORIDADES), "estados": [{"id": e, "rotulo": ROTULOS[e]} for e in ESTADOS]}


_ID_TAREFA = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def id_valido(tid):
    return bool(_ID_TAREFA.match(tid or ""))
