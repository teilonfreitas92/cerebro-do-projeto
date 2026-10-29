"""Soma de tokens e custo estimado a partir do campo `usage` das mensagens dos transcritos.

Custo = tokens x preço da tabela editável (config.json > precos, US$ por milhão de tokens). É uma ESTIMATIVA pelo preço
de lista: pode diferir da fatura. Modelo sem preço na tabela fica "a conferir": entram só os tokens, o custo fica vazio.
"""
import datetime
import json
import threading
import time

from . import indice

CAMPOS = ("entrada", "saida", "cache_leitura", "cache_escrita_5m", "cache_escrita_1h")


def preco_do_modelo(modelo, precos):
    """Preço do modelo: nome exato ou o maior prefixo da tabela (claude-opus-5-5-20261001 -> claude-opus-5-5)."""
    if not modelo:
        return None
    if modelo in precos:
        return precos[modelo]
    melhores = [k for k in precos if modelo.startswith(k)]
    return precos[max(melhores, key=len)] if melhores else None


def custo_usd(tokens, preco):
    """tokens = (entrada, saída, leitura, escrita 5m, escrita 1h). None se não houver preço."""
    if not preco:
        return None
    total = 0.0
    for t, campo in zip(tokens, CAMPOS):
        total += t * float(preco.get(campo) or 0)
    return total / 1_000_000


def dia_local(epoch):
    return datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d")


def _vazio():
    return {"entrada": 0, "saida": 0, "cache_leitura": 0, "cache_escrita": 0, "mensagens": 0, "custo": 0.0, "sem_preco": 0}


def _somar(acc, tokens, custo):
    acc["entrada"] += tokens[0]
    acc["saida"] += tokens[1]
    acc["cache_leitura"] += tokens[2]
    acc["cache_escrita"] += tokens[3] + tokens[4]
    acc["mensagens"] += 1
    if custo is None:
        acc["sem_preco"] += 1
    else:
        acc["custo"] += custo


def total_tokens(acc):
    return acc["entrada"] + acc["saida"] + acc["cache_leitura"] + acc["cache_escrita"]


_cache = {}
_trava_cache = threading.Lock()


def agregar(slug, precos, desde_epoch=0.0):
    """Com cache: só recalcula quando o índice do projeto, os preços ou o minuto do corte mudam."""
    est = indice.estado(slug)
    chave = (slug, est.versao, int(desde_epoch // 60), json.dumps(precos, sort_keys=True))
    with _trava_cache:
        if chave in _cache:
            return _cache[chave]
    r = _agregar(slug, precos, desde_epoch)
    with _trava_cache:
        if len(_cache) > 40:
            _cache.clear()
        for k in [k for k in _cache if k[0] == slug and k[1] != est.versao]:
            del _cache[k]
        _cache[chave] = r
    return r


def _agregar(slug, precos, desde_epoch=0.0):
    """Soma tudo que está no índice do projeto. Devolve totais por sessão, subagente, modelo e dia.

    A chave `por_arquivo[rel]` traz os totais de cada arquivo (sessão ou subagente) para as telas de sessões e agentes.
    """
    est = indice.estado(slug)
    arquivos = indice.listar_arquivos(slug)
    por_rel = {a["rel"]: a for a in arquivos}
    total = _vazio()
    por_modelo, por_dia, por_arquivo = {}, {}, {}
    modelos_sem_preco = set()
    with est.trava:
        itens = list(est.arquivos.items())
    for rel, ind in itens:
        arq = por_rel.get(rel)
        if arq is None:
            continue                                    # arquivo apagado pelo Claude Code (limpeza dos 30 dias)
        acc = _vazio()
        for ts, modelo, *tok in ind["msgs"].values():
            if ts and ts < desde_epoch:
                continue
            preco = preco_do_modelo(modelo, precos)
            if preco is None:
                modelos_sem_preco.add(modelo)
            c = custo_usd(tok, preco)
            _somar(acc, tok, c)
            _somar(total, tok, c)
            _somar(por_modelo.setdefault(modelo, _vazio()), tok, c)
            if ts:
                _somar(por_dia.setdefault(dia_local(ts), _vazio()), tok, c)
        if acc["mensagens"]:
            por_arquivo[rel] = acc
    return {"total": total, "por_modelo": por_modelo, "por_dia": por_dia, "por_arquivo": por_arquivo,
            "modelos_sem_preco": sorted(m for m in modelos_sem_preco if m)}


def hoje_e_semana(slug, precos):
    """Custo/tokens de hoje e dos últimos 7 dias (para o cartão do painel geral)."""
    agora = time.time()
    d = agregar(slug, precos, desde_epoch=agora - 7 * 86400)
    hoje = dia_local(agora)
    h = d["por_dia"].get(hoje) or _vazio()
    return {"hoje": h, "semana": d["total"]}
