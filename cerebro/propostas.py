"""Propostas de melhoria e as tarefas que nascem da aprovação.

A análise (analise.py) e o vigia de novidades (novidades.py) só PROPÕEM. Nada é aplicado sozinho: o dono ou o gestor
aprova ou descarta cada proposta na página (ou pela linha de comando). Aprovada vira uma "tarefa para o gestor"
(tarefas.json), que o gestor vê no Cérebro e marca como feita. Descartada não volta na próxima análise.

Cada proposta: id estável (mesma causa = mesmo id), título, motivo (com números), esforço P/M/G, risco baixo/médio/alto,
origem (projeto, cerebro, novidade) e estado (nova, aprovada, descartada, obsoleta).
O escopo "_cerebro" guarda as propostas do próprio Cérebro e as novidades (valem para todos os projetos).
"""
import hashlib
import time

from . import armazem, config

ESFORCOS = ("P", "M", "G")
RISCOS = ("baixo", "médio", "alto")
ESCOPO_CEREBRO = "_cerebro"


def id_estavel(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:10]


def proposta(origem, chave, titulo, motivo, esforco="M", risco="baixo", area=""):
    if esforco not in ESFORCOS or risco not in RISCOS:
        raise ValueError("esforço ou risco inválido")
    return {"id": id_estavel(origem, chave), "origem": origem, "area": area, "titulo": titulo[:160], "motivo": motivo[:700],
            "esforco": esforco, "risco": risco}


def _arq(slug):
    return config.pasta_projeto(slug) / "propostas.json"


def _arq_tarefas(slug):
    return config.pasta_projeto(slug) / "tarefas.json"


def sincronizar(slug, lista, agora=None, obsoletar=True):
    """Junta as propostas de uma análise: as novas entram como 'nova'; as que continuam mantêm o estado; as 'nova' que a análise
    não repete mais (o problema sumiu) viram 'obsoleta'. Devolve as que acabaram de entrar. 'origem' só toca nas do mesmo grupo."""
    agora = agora or time.time()
    novas = []
    ids = {p["id"] for p in lista}
    origens = {p["origem"] for p in lista}

    def mudar(d):
        for p in lista:
            ant = d["itens"].get(p["id"])
            if ant is None:
                d["itens"][p["id"]] = {**p, "estado": "nova", "criada_em": agora, "vista_em": agora}
                novas.append(d["itens"][p["id"]])
            else:
                ant.update({k: p[k] for k in ("titulo", "motivo", "esforco", "risco", "area")})
                ant["vista_em"] = agora
                if ant["estado"] == "obsoleta":
                    ant["estado"] = "nova"
        for pid, it in d["itens"].items():
            if obsoletar and it["estado"] == "nova" and it["origem"] in origens and pid not in ids:
                it["estado"] = "obsoleta"
        return d

    armazem.atualizar_json(_arq(slug), {"v": 1, "itens": {}}, mudar)
    return novas


def listar(slug, incluir_obsoletas=False):
    d = armazem.ler_json(_arq(slug), {"v": 1, "itens": {}})
    itens = list((d.get("itens") or {}).values()) if isinstance(d, dict) else []
    if not incluir_obsoletas:
        itens = [i for i in itens if i.get("estado") != "obsoleta"]
    ordem = {"nova": 0, "aprovada": 1, "descartada": 2, "obsoleta": 3}
    itens.sort(key=lambda i: (ordem.get(i.get("estado"), 9), -(i.get("criada_em") or 0)))
    return itens


def decidir(slug, proposta_id, aprovar, nota="", por="dono"):
    """Aprova (vira tarefa) ou descarta. Levanta ValueError se não existir."""
    nota = (nota or "").strip()[:500]
    agora = time.time()
    achou = {}

    def mudar(d):
        it = d["itens"].get(proposta_id)
        if it is None:
            raise ValueError("proposta não encontrada")
        it.update(estado="aprovada" if aprovar else "descartada", decidida_em=agora, nota=nota, por=por)
        achou.update(it)
        return d

    armazem.atualizar_json(_arq(slug), {"v": 1, "itens": {}}, mudar)
    if aprovar:
        def tarefa(d):
            tid = "t-" + proposta_id
            if tid not in d["itens"]:
                d["itens"][tid] = {"id": tid, "proposta_id": proposta_id, "titulo": achou["titulo"], "motivo": achou["motivo"],
                                   "esforco": achou["esforco"], "risco": achou["risco"], "criada_em": agora, "estado": "aberta",
                                   "nota": nota, "origem": achou["origem"]}
            return d

        armazem.atualizar_json(_arq_tarefas(slug), {"v": 1, "itens": {}}, tarefa)
    return achou


def reabrir(slug, proposta_id):
    def mudar(d):
        it = d["itens"].get(proposta_id)
        if it is None:
            raise ValueError("proposta não encontrada")
        if it["estado"] == "descartada":
            it["estado"] = "nova"
        return d

    armazem.atualizar_json(_arq(slug), {"v": 1, "itens": {}}, mudar)


ESTADOS_FINAIS = ("feita", "recusada")      # os demais estados de tarefa (ver tarefas_gestor.py) contam como "abertas"


def tarefas(slug):
    """Tarefas que NASCERAM de proposta aprovada, na visão antiga (a aba Análise e a CLI): estado 'aberta' enquanto o trabalho não
    termina, mesmo que o gestor já tenha marcado 'recebida', 'em andamento' ou 'a conferir' (ver tarefas_gestor.py). As tarefas que
    o dono criou na página ficam no mesmo arquivo, mas aparecem só na aba Tarefas."""
    d = armazem.ler_json(_arq_tarefas(slug), {"v": 1, "itens": {}})
    itens = list((d.get("itens") or {}).values()) if isinstance(d, dict) else []
    itens = [dict(t, estado="aberta" if t.get("estado") not in ESTADOS_FINAIS else t.get("estado")) for t in itens if t.get("proposta_id")]
    itens.sort(key=lambda t: (t.get("estado") != "aberta", -(t.get("criada_em") or 0)))
    return itens


def concluir_tarefa(slug, tarefa_id, nota=""):
    def mudar(d):
        t = d["itens"].get(tarefa_id)
        if t is None:
            raise ValueError("tarefa não encontrada")
        agora = time.time()
        nota_limpa = (nota or "").strip()[:500]
        t.setdefault("historico", []).append({"em": agora, "por": "gestor", "de": t.get("estado"), "para": "feita", "agente": "", "nota": nota_limpa})
        t.update(estado="feita", feita_em=agora, nota_final=nota_limpa, atualizada_em=agora)
        return d

    armazem.atualizar_json(_arq_tarefas(slug), {"v": 1, "itens": {}}, mudar)


def contagem(slug):
    novas = sum(1 for i in listar(slug) if i.get("estado") == "nova")
    abertas = sum(1 for t in tarefas(slug) if t.get("estado") == "aberta")
    return {"novas": novas, "tarefas_abertas": abertas}
