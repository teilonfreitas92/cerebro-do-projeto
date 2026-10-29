"""Registro de decisões do projeto (decisoes.jsonl): o que ficou decidido, em que dia, por quem.

Complementa a memória do Claude Code (que o Cérebro só lê): aqui o gestor ou o dono registram decisões, regras e ideias
no momento em que acontecem, pela página ou por `python cerebro_cli.py decisao <projeto> "texto"`. Cada linha é um JSON.
Texto passa pelo mascaramento de segredos antes de ser gravado.

NUNCA se apaga nem se reescreve uma linha: editar ou arquivar ACRESCENTA uma linha de evento
({"evento": "arquivar"|"substituir", "alvo": id, ...}). Editar = registrar a decisão nova (com "substitui": id) + marcar a
antiga como substituída. listar() aplica os eventos e devolve cada decisão com "estado" (ativa / substituida / arquivada).
"""
import re
import secrets
import time

from . import armazem, config
from .segredos import mascarar

TIPOS = ("decisao", "regra", "ideia")
LIMITE_TEXTO = 2000
_ORIGEM = re.compile(r"^[A-Za-zÀ-ÿ0-9 _.\-]{1,40}$")


def _arquivo(slug):
    return config.pasta_projeto(slug) / "decisoes.jsonl"


def registrar(slug, texto, tipo="decisao", origem="gestor", substitui=None):
    texto = mascarar((texto or "").strip())
    if len(texto) < 3:
        raise ValueError("escreva a decisão (pelo menos 3 caracteres)")
    if len(texto) > LIMITE_TEXTO:
        raise ValueError(f"texto grande demais (máximo {LIMITE_TEXTO} caracteres)")
    if tipo not in TIPOS:
        raise ValueError("tipo precisa ser: " + ", ".join(TIPOS))
    origem = (origem or "gestor").strip()
    if not _ORIGEM.match(origem):
        raise ValueError("origem inválida (até 40 letras, números, espaço, ponto, hífen)")
    agora = time.time()
    item = {"id": f"d{int(agora * 1000):x}{secrets.token_hex(2)}", "em": agora, "tipo": tipo, "texto": texto, "origem": origem}
    if substitui:
        item["substitui"] = str(substitui)[:40]
    armazem.anexar_jsonl(_arquivo(slug), item)
    return item


def listar(slug, limite=300, so_ativas=False):
    """Mais novas primeiro, cada uma com "estado" (ativa / substituida / arquivada) e, se houver, "substituida_por"."""
    brutos = armazem.ler_jsonl(_arquivo(slug))
    eventos = {}
    for o in brutos:
        if o.get("evento") in EVENTOS and o.get("alvo"):
            eventos[o["alvo"]] = o                     # vale o último evento de cada decisão
    itens = [i for i in brutos if i.get("texto") and not i.get("evento")]
    for i in itens:
        ev = eventos.get(i.get("id"))
        i["estado"] = "ativa" if ev is None else ("arquivada" if ev["evento"] == "arquivar" else "substituida")
        if ev is not None:
            i["mudou_em"] = ev.get("em")
            if ev.get("por_id"):
                i["substituida_por"] = ev["por_id"]
            if ev.get("motivo"):
                i["motivo"] = ev["motivo"]
    if so_ativas:
        itens = [i for i in itens if i["estado"] == "ativa"]
    itens.reverse()                                   # empate de horário (relógio do Windows é grosso): vale a ordem de gravação
    itens.sort(key=lambda i: -(i.get("em") or 0))
    return itens[:limite]


EVENTOS = ("arquivar", "substituir")


def achar(slug, did):
    for i in listar(slug, limite=100_000):
        if i.get("id") == did:
            return i
    raise ValueError("decisão não encontrada")


def _copia(slug):
    """Cópia de segurança do decisoes.jsonl antes de acrescentar o evento (em ~/.cerebro/copias/decisoes/<slug>/)."""
    from . import memoria_edicao
    return str(memoria_edicao.copia_seguranca("decisoes", slug, [_arquivo(slug)]))


def arquivar(slug, did, motivo="", por="dono", confirmar=False):
    """Marca a decisão como arquivada (acrescenta um evento; a linha original fica). Sem confirmar: só a prévia."""
    atual = achar(slug, did)
    if atual["estado"] != "ativa":
        raise ValueError(f"esta decisão já está {atual['estado']}")
    motivo = mascarar((motivo or "").strip())[:300]
    previa = {"antes": atual["texto"], "depois": "(arquivada: sai da linha do tempo, a linha continua guardada)", "estado": "arquivada"}
    if not confirmar:
        return {"previa": True, **previa}
    copia = _copia(slug)
    armazem.anexar_jsonl(_arquivo(slug), {"evento": "arquivar", "alvo": did, "em": time.time(), "motivo": motivo, "por": por})
    return {"previa": False, "copia": copia, **previa}


def substituir(slug, did, texto, por="dono", confirmar=False):
    """Editar: grava a decisão nova (mesmo tipo, com "substitui") e marca a antiga como substituída. Nada é apagado."""
    atual = achar(slug, did)
    if atual["estado"] != "ativa":
        raise ValueError(f"esta decisão já está {atual['estado']}")
    novo = mascarar((texto or "").strip())
    if novo == atual["texto"]:
        raise ValueError("o texto não mudou")
    if len(novo) < 3 or len(novo) > LIMITE_TEXTO:
        raise ValueError(f"escreva a decisão (de 3 a {LIMITE_TEXTO} caracteres)")
    previa = {"antes": atual["texto"], "depois": novo, "estado": "substituida"}
    if not confirmar:
        return {"previa": True, **previa}
    copia = _copia(slug)
    item = registrar(slug, novo, atual.get("tipo", "decisao"), por if _ORIGEM.match(por or "") else "dono", substitui=did)
    armazem.anexar_jsonl(_arquivo(slug), {"evento": "substituir", "alvo": did, "por_id": item["id"], "em": time.time(), "por": por})
    return {"previa": False, "copia": copia, "nova": item, **previa}
