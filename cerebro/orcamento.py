"""Orçamento de gasto por projeto (e geral), com alerta de 80% e de 100%.

É sempre ESTIMATIVA pelo preço de lista (custos.py): quem usa plano por assinatura não paga por token, então o valor em
dólar serve de régua de uso, e os tokens aparecem ao lado. Limites opcionais por dia, por semana (começa na segunda) e por mês
do calendário, no fuso do PC. O que vale fica em ~/.cerebro/orcamento.json:

    {"v": 1, "geral": {"dia": 5.0, "semana": null, "mes": 100.0, "aviso_pct": 80},
     "projetos": {"<slug>": {"dia": null, "semana": null, "mes": 30.0, "aviso_pct": 80}}}

Nada aqui avisa o Windows: `alertas()` só devolve a lista (titulo, texto, chave, nivel) para outro módulo notificar.
"""
import calendar
import datetime
import re
import time

from . import armazem, config, custos, projetos

PERIODOS = ("dia", "semana", "mes")
ROTULO_PERIODO = {"dia": "hoje", "semana": "esta semana", "mes": "este mês"}
AVISO_PADRAO = 80
LIMITE_MAXIMO = 1_000_000.0
DIAS_MINIMOS_PROJECAO = 3                   # antes disso o ritmo do mês ainda não diz nada
AVISO_ESTIMATIVA = ("É uma ESTIMATIVA pelo preço de lista: quem usa plano por assinatura não paga por token, "
                    "então use o valor como régua de uso. Os tokens aparecem ao lado.")
_PADRAO = {"v": 1, "geral": {}, "projetos": {}}


def _arq():
    return config.CASA / "orcamento.json"


# ---------------------------------------------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------------------------------------------
def _numero(v, nome):
    """None/0/'' = sem limite. Senão um número maior que zero (US$)."""
    if v is None or v == "" or v == 0:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"limite {nome} precisa ser um número em US$")
    if v != v or v < 0 or v > LIMITE_MAXIMO:
        raise ValueError(f"limite {nome} fora do aceito (de 0,01 a {int(LIMITE_MAXIMO)} US$)")
    return round(float(v), 2) or None


def _aviso(v):
    if v is None:
        return AVISO_PADRAO
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 99:
        raise ValueError("o aviso precisa ser um percentual de 1 a 99")
    return int(v)


def _entrada(e):
    """Entrada do arquivo, tolerante: o que não presta vira 'sem limite'."""
    e = e if isinstance(e, dict) else {}
    saida = {}
    for p in PERIODOS:
        try:
            saida[p] = _numero(e.get(p), p)
        except ValueError:
            saida[p] = None
    try:
        saida["aviso_pct"] = _aviso(e.get("aviso_pct"))
    except ValueError:
        saida["aviso_pct"] = AVISO_PADRAO
    return saida


def ler():
    """{'geral': {...}, 'projetos': {slug: {...}}} sempre completo (arquivo ausente ou quebrado = tudo sem limite)."""
    d = armazem.ler_json(_arq(), _PADRAO)
    d = d if isinstance(d, dict) else {}
    projs = d.get("projetos") if isinstance(d.get("projetos"), dict) else {}
    return {"geral": _entrada(d.get("geral")), "projetos": {s: _entrada(e) for s, e in projs.items() if isinstance(s, str)}}


def definir(escopo, dia=..., semana=..., mes=..., aviso_pct=...):
    """Muda o orçamento de 'geral' ou de um slug. O que não for passado fica como está; None ou 0 tira o limite.
    Levanta ValueError (sem gravar nada) se algum valor não servir."""
    novos = {}
    for nome, v in (("dia", dia), ("semana", semana), ("mes", mes)):
        if v is not ...:
            novos[nome] = _numero(v, nome)
    if aviso_pct is not ...:
        novos["aviso_pct"] = _aviso(aviso_pct)
    if escopo != "geral" and not re.fullmatch(r"[A-Za-z0-9_\-]{1,200}", escopo or ""):
        raise ValueError("projeto inválido")

    def mudar(d):
        d["v"] = 1
        d.setdefault("geral", {})
        if not isinstance(d.get("projetos"), dict):
            d["projetos"] = {}
        alvo = d["geral"] if escopo == "geral" else d["projetos"].setdefault(escopo, {})
        atual = _entrada(alvo)
        atual.update(novos)
        alvo.clear()
        alvo.update(atual)
        if escopo != "geral" and not any(atual[p] for p in PERIODOS) and atual["aviso_pct"] == AVISO_PADRAO:
            del d["projetos"][escopo]                # nada configurado: não guarda entrada vazia
        return d

    armazem.atualizar_json(_arq(), _PADRAO, mudar)
    return ler()


# ---------------------------------------------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------------------------------------------
def hoje_local(agora=None):
    return datetime.date.fromtimestamp(agora if agora is not None else time.time())


def inicio_do_periodo(periodo, hoje):
    if periodo == "dia":
        return hoje
    if periodo == "semana":
        return hoje - datetime.timedelta(days=hoje.weekday())        # segunda-feira
    return hoje.replace(day=1)


def id_do_periodo(periodo, hoje):
    """Texto que muda quando o período vira (usado na chave do alerta: um aviso por dia, semana ou mês)."""
    ini = inicio_do_periodo(periodo, hoje)
    return ini.strftime("%Y-%m") if periodo == "mes" else ini.isoformat()


def _soma_dias(por_dia, desde, ate):
    """Soma custo, tokens e mensagens sem preço dos dias (texto AAAA-MM-DD) entre 'desde' e 'ate', inclusive."""
    custo, tokens, sem_preco = 0.0, 0, 0
    for dia, acc in por_dia.items():
        if desde.isoformat() <= dia <= ate.isoformat():
            custo += acc.get("custo") or 0.0
            tokens += custos.total_tokens(acc)
            sem_preco += acc.get("sem_preco") or 0
    return custo, tokens, sem_preco


def _por_dia_do_projeto(slug, precos):
    return custos.agregar(slug, precos)["por_dia"]


def nivel_de(gasto, limite, aviso_pct):
    if not limite:
        return "sem_limite"
    pct = 100.0 * gasto / limite
    return "estourou" if pct >= 100 else "atencao" if pct >= aviso_pct else "ok"


_GRAVIDADE = {"sem_limite": 0, "ok": 1, "atencao": 2, "estourou": 3}


def bloco(por_dia, conf, hoje):
    """Uso e situação de um escopo (um projeto ou o geral): por período, projeção do mês e o pior nível."""
    conf = _entrada(conf)
    periodos, pior = {}, "sem_limite"
    for p in PERIODOS:
        custo, tokens, sem_preco = _soma_dias(por_dia, inicio_do_periodo(p, hoje), hoje)
        lim = conf[p]
        nivel = nivel_de(custo, lim, conf["aviso_pct"])
        periodos[p] = {"gasto": round(custo, 4), "tokens": tokens, "sem_preco": sem_preco, "limite": lim, "nivel": nivel,
                       "pct": round(100.0 * custo / lim, 1) if lim else None, "falta": round(max(0.0, lim - custo), 4) if lim else None}
        if _GRAVIDADE[nivel] > _GRAVIDADE[pior]:
            pior = nivel if nivel != "sem_limite" else pior
    decorridos = hoje.day
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    mes = periodos["mes"]
    projecao = round(mes["gasto"] / decorridos * dias_mes, 4)
    lim_mes = conf["mes"]
    vai_passar = bool(lim_mes) and mes["gasto"] < lim_mes and projecao >= lim_mes and decorridos >= DIAS_MINIMOS_PROJECAO
    return {"limites": {p: conf[p] for p in PERIODOS}, "aviso_pct": conf["aviso_pct"], "periodos": periodos, "nivel": pior,
            "tem_limite": any(conf[p] for p in PERIODOS),
            "projecao_mes": {"valor": projecao, "dias_decorridos": decorridos, "dias_no_mes": dias_mes, "vai_passar": vai_passar,
                             "pct": round(100.0 * projecao / lim_mes, 1) if lim_mes else None}}


def _soma_por_dia(lista):
    total = {}
    for pd in lista:
        for dia, acc in pd.items():
            t = total.setdefault(dia, {"custo": 0.0, "entrada": 0, "saida": 0, "cache_leitura": 0, "cache_escrita": 0, "sem_preco": 0})
            t["custo"] += acc.get("custo") or 0.0
            t["sem_preco"] += acc.get("sem_preco") or 0
            for k in ("entrada", "saida", "cache_leitura", "cache_escrita"):
                t[k] += acc.get(k) or 0
    return total


def estado(cfg=None, agora=None, so_slug=None):
    """Tudo que a tela e a CLI mostram: geral + um bloco por projeto (todos, mesmo sem limite). 'so_slug' calcula só esse projeto
    (e o geral)."""
    cfg = cfg if cfg is not None else config.ler_config()
    hoje = hoje_local(agora)
    conf = ler()
    lista = projetos.descobrir()
    por_dia = {}
    for p in lista:
        try:
            por_dia[p["slug"]] = _por_dia_do_projeto(p["slug"], cfg["precos"])
        except Exception:
            por_dia[p["slug"]] = {}
    saida_projetos = []
    for p in lista:
        if so_slug and p["slug"] != so_slug:
            continue
        saida_projetos.append({"slug": p["slug"], "nome": p["nome"], "oculto": p["oculto"],
                               **bloco(por_dia[p["slug"]], conf["projetos"].get(p["slug"]), hoje)})
    return {"hoje": hoje.isoformat(), "aviso_padrao": AVISO_PADRAO, "estimativa": AVISO_ESTIMATIVA,
            "geral": bloco(_soma_por_dia(por_dia.values()), conf["geral"], hoje), "projetos": saida_projetos}


# ---------------------------------------------------------------------------------------------------------------
# Alertas (para o painel e para quem for avisar o Windows)
# ---------------------------------------------------------------------------------------------------------------
def usd(n):
    """US$ 1.234,50 (pt-BR)."""
    t = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "US$ " + t


def _alertas_do_bloco(nome_escopo, escopo_id, b, hoje):
    lista = []
    for p in PERIODOS:
        d = b["periodos"][p]
        if d["nivel"] not in ("atencao", "estourou"):
            continue
        rot = ROTULO_PERIODO[p]
        base = f"{usd(d['gasto'])} de {usd(d['limite'])} ({d['pct']:.0f}%) {rot}"
        if d["nivel"] == "estourou":
            titulo, texto = f"Orçamento estourou: {nome_escopo} ({rot})", f"Gasto estimado {base}. Passou do limite que você definiu."
        else:
            titulo, texto = f"Orçamento quase no fim: {nome_escopo} ({rot})", f"Gasto estimado {base}. Faltam {usd(d['falta'])} para o limite."
        lista.append({"titulo": titulo, "texto": texto + " Estimativa pelo preço de lista.", "nivel": d["nivel"], "escopo": escopo_id, "periodo": p,
                      "chave": f"orcamento:{escopo_id}:{p}:{id_do_periodo(p, hoje)}:{d['nivel']}"})
    pj = b["projecao_mes"]
    if pj["vai_passar"] and b["periodos"]["mes"]["nivel"] == "ok":
        lista.append({"titulo": f"No ritmo atual, {nome_escopo} passa do limite do mês",
                      "texto": f"Já gastou {usd(b['periodos']['mes']['gasto'])} em {pj['dias_decorridos']} dia(s); no mesmo ritmo o mês fecha em "
                               f"{usd(pj['valor'])}, e o limite é {usd(b['limites']['mes'])}. Estimativa pelo preço de lista.",
                      "nivel": "projecao", "escopo": escopo_id, "periodo": "mes",
                      "chave": f"orcamento:{escopo_id}:mes:{id_do_periodo('mes', hoje)}:projecao"})
    return lista


def alertas(cfg=None, agora=None):
    """Lista de avisos de orçamento: [{titulo, texto, chave, nivel, escopo, periodo}]. nivel = 'atencao' (passou do % de aviso),
    'estourou' (100%) ou 'projecao' (o ritmo do mês vai passar do limite). A 'chave' é estável dentro do período (dia, semana ou mês)
    e muda quando o período vira ou o nível piora: serve para não avisar duas vezes a mesma coisa. Vazia se ninguém definiu limite."""
    conf = ler()
    if not any(e[p] for e in [conf["geral"], *conf["projetos"].values()] for p in PERIODOS):
        return []
    est = estado(cfg, agora)
    hoje = datetime.date.fromisoformat(est["hoje"])
    saida = []
    if est["geral"]["tem_limite"]:
        saida += _alertas_do_bloco("todos os projetos", "geral", est["geral"], hoje)
    for p in est["projetos"]:
        if p["tem_limite"]:
            saida += _alertas_do_bloco(p["nome"], p["slug"], p, hoje)
    ordem = {"estourou": 0, "atencao": 1, "projecao": 2}
    saida.sort(key=lambda a: ordem[a["nivel"]])
    return saida


def itens_fila(cfg=None):
    """Alertas no formato de 'Precisa de você' (painel.fila)."""
    saida = []
    for a in alertas(cfg):
        slug = "" if a["escopo"] == "geral" else a["escopo"]
        saida.append({"nivel": {"estourou": "acao", "atencao": "aviso", "projecao": "info"}[a["nivel"]], "projeto": slug,
                      "titulo": a["titulo"], "texto": a["texto"], "aba": "custos" if slug else ""})
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Texto para a linha de comando
# ---------------------------------------------------------------------------------------------------------------
def _linha_bloco(rotulo, b):
    partes = []
    for p in PERIODOS:
        d = b["periodos"][p]
        t = f"{p}: {usd(d['gasto'])}"
        if d["limite"]:
            t += f" de {usd(d['limite'])} ({d['pct']:.0f}%, {d['nivel']})"
        partes.append(t)
    pj = b["projecao_mes"]
    return f"{rotulo:<28} " + " | ".join(partes) + f" | projeção do mês: {usd(pj['valor'])}" + (" (VAI PASSAR)" if pj["vai_passar"] else "")


def texto_estado(est, so_slug=None):
    linhas = [f"Orçamento em {est['hoje']} (aviso a partir de {est['aviso_padrao']}% por padrão). " + est["estimativa"], ""]
    if not so_slug:
        linhas.append(_linha_bloco("GERAL (todos os projetos)", est["geral"]))
    for p in est["projetos"]:
        if so_slug and p["slug"] != so_slug:
            continue
        if so_slug or p["tem_limite"]:
            linhas.append(_linha_bloco(p["nome"][:28], p))
    if len(linhas) == 2:
        linhas.append("Nenhum limite definido ainda. Defina com: python cerebro_cli.py orcamento [<projeto>] --dia N --semana N --mes N")
    return "\n".join(linhas)
