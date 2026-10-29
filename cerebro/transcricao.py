"""Leitura SÓ LEITURA das transcrições (JSONL) do Claude Code.

O formato das linhas NÃO é um contrato estável do Claude Code: este módulo lê de forma tolerante (campo que falta ou
linha desconhecida é ignorado, linha quebrada não derruba nada) e só avança além de linhas COMPLETAS (o arquivo é
escrito de forma assíncrona; a última linha pode estar pela metade).

Duas leituras, as duas incrementais (guardam a posição em bytes e nunca releem o arquivo inteiro):
  * atualizar_indice(): resumo da sessão (título, tokens por mensagem, ferramentas usadas) para custos e listas;
  * passos_da_linha(): o "passo a passo" de um agente (texto, ferramenta com alvo, resultado encurtado) para a tela ao vivo.
Tudo que vai para a tela passa por segredos.mascarar().
"""
import datetime
import json
import os
import re
from collections import Counter

from .segredos import encurtar

_LEMBRETE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_TAGS_INTERNAS = re.compile(r"<(command-[a-z-]+|local-command-[a-z-]+|ide_[a-z_]+)>.*?</\1>", re.S)
MAX_TENTATIVAS_PRIMEIRA = 40       # quantas mensagens de usuário olhar até achar a primeira "de verdade"


def para_epoch(ts):
    """'2026-10-22T22:50:22.189Z' -> segundos desde 1970 (UTC). None se não der para ler."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def extrair_usage(usage):
    """(entrada, saída, leitura de cache, escrita de cache 5 min, escrita de cache 1 h). Tolerante a campos que faltam."""
    if not isinstance(usage, dict):
        return None

    def n(k):
        v = usage.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    entrada, saida = n("input_tokens"), n("output_tokens")
    leitura, escrita = n("cache_read_input_tokens"), n("cache_creation_input_tokens")
    w5 = w1 = 0
    cc = usage.get("cache_creation")
    if isinstance(cc, dict):
        w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
        w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
    if w5 + w1 != escrita:                 # detalhamento ausente ou incoerente: tudo conta como 5 min
        w5, w1 = max(escrita - w1, 0), min(w1, escrita)
    if not (entrada or saida or leitura or escrita):
        return None
    return (entrada, saida, leitura, w5, w1)


# ---------------------------------------------------------------------------------------------------------------
# Índice incremental de um arquivo de sessão ou de subagente
# ---------------------------------------------------------------------------------------------------------------
def novo_indice():
    return {"tam": 0, "mtime": 0.0, "msgs": {}, "titulo": "", "nome_agente": "", "primeira": "", "tentativas": 0,
            "inicio": None, "fim": None, "tools": {}, "cwd": "", "branch": "", "versao": "", "modelos": {}, "custo_estado": None,
            "resumo": "", "titulo_ia": ""}


def _texto_do_conteudo(c):
    """Texto de message.content (string ou lista de blocos), sem blocos que não são texto."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def texto_limpo_do_usuario(obj):
    """Texto digitado de verdade numa mensagem de usuário (sem lembretes do sistema); '' se não houver."""
    m = obj.get("message")
    if not isinstance(m, dict):
        return ""
    c = m.get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return ""
    t = _texto_do_conteudo(c)
    t = _TAGS_INTERNAS.sub("", _LEMBRETE.sub("", t)).strip()
    return t


def _tipo_no_inicio(linha, tipo):
    """A linha começa com {"type":"<tipo>" (com ou sem espaço depois dos dois-pontos)?"""
    return linha.startswith(b'{"type":"' + tipo) or linha.startswith(b'{"type": "' + tipo)


def _tem_tipo(linha, tipo):
    """O JSON da linha contém "type":"<tipo>" em algum lugar (compacto ou com espaço)? Barato: nenhum parse."""
    return (b'"type":"' + tipo + b'"') in linha or (b'"type": "' + tipo + b'"') in linha


def _linha_do_indice(linha, ind):
    if linha.startswith(b'{"type":"') or linha.startswith(b'{"type": "'):
        # registros pequenos de metadados: o tipo vem primeiro
        if _tipo_no_inicio(linha, b"custom-title"):
            o = json.loads(linha)
            ind["titulo"] = encurtar(str(o.get("customTitle") or ind["titulo"]), 200)
            return
        if _tipo_no_inicio(linha, b"agent-name"):
            o = json.loads(linha)
            ind["nome_agente"] = encurtar(str(o.get("agentName") or ind["nome_agente"]), 200)
            return
        if _tipo_no_inicio(linha, b"summary") or _tipo_no_inicio(linha, b"ai-title"):
            o = json.loads(linha)
            if o.get("summary"):
                ind["resumo"] = encurtar(str(o["summary"]), 400)
            if o.get("aiTitle"):
                ind["titulo_ia"] = encurtar(str(o["aiTitle"]), 200)
            return
        if _tipo_no_inicio(linha, b"cost-state"):
            o = json.loads(linha)
            ind["custo_estado"] = {"total_usd": o.get("totalCostUSD"), "modelos": o.get("modelUsage")}
            return
    if _tem_tipo(linha, b"assistant"):
        o = json.loads(linha)
        m = o.get("message") if isinstance(o.get("message"), dict) else {}
        ts = para_epoch(o.get("timestamp"))
        if ts:
            ind["inicio"] = ts if ind["inicio"] is None else min(ind["inicio"], ts)
            ind["fim"] = ts if ind["fim"] is None else max(ind["fim"], ts)
        for campo, chave in (("cwd", "cwd"), ("gitBranch", "branch"), ("version", "versao")):
            if o.get(campo):
                ind[chave] = str(o[campo])
        conteudo = m.get("content")
        if isinstance(conteudo, list):
            for b in conteudo:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name"):
                    ind["tools"][b["name"]] = ind["tools"].get(b["name"], 0) + 1
        modelo = m.get("model")
        u = extrair_usage(m.get("usage"))
        if u and isinstance(modelo, str) and modelo != "<synthetic>":
            mid = m.get("id") or o.get("uuid") or o.get("requestId")
            if not mid:
                return
            ant = ind["msgs"].get(mid)
            if ant is None:
                ind["msgs"][mid] = [ts or 0, modelo, *u]
            else:                           # a mesma mensagem aparece em várias linhas (um bloco por linha): vale o maior
                for i, v in enumerate(u):
                    if v > ant[2 + i]:
                        ant[2 + i] = v
        return
    if _tem_tipo(linha, b"user") and not ind["primeira"] and ind["tentativas"] < MAX_TENTATIVAS_PRIMEIRA:
        ind["tentativas"] += 1
        if len(linha) < 400_000:
            t = texto_limpo_do_usuario(json.loads(linha))
            if t:
                ind["primeira"] = encurtar(t, 240)


def atualizar_indice(caminho, ind=None):
    """Lê só o que foi escrito depois da última leitura. Devolve (índice, mudou)."""
    st = os.stat(caminho)
    if ind is None or st.st_size < ind.get("tam", 0):      # arquivo novo ou reescrito: começa do zero
        ind = novo_indice()
    ind["mtime"] = st.st_mtime
    if st.st_size == ind["tam"]:
        return ind, False
    pos = ind["tam"]
    with open(caminho, "rb") as f:
        f.seek(pos)
        for linha in f:
            if not linha.endswith(b"\n"):                  # linha incompleta: fica para a próxima leitura
                break
            pos += len(linha)
            try:
                _linha_do_indice(linha, ind)
            except (ValueError, TypeError, AttributeError, KeyError):
                continue
    ind["tam"] = pos
    # os modelos usados, por quantidade de mensagens
    c = Counter(v[1] for v in ind["msgs"].values())
    ind["modelos"] = dict(c)
    return ind, True


def titulo_do_indice(ind, padrao=""):
    return ind.get("titulo") or ind.get("nome_agente") or ind.get("primeira") or padrao


# ---------------------------------------------------------------------------------------------------------------
# Passo a passo ao vivo
# ---------------------------------------------------------------------------------------------------------------
_ORDEM_ALVO = ("file_path", "notebook_path", "path", "pattern", "command", "url", "query", "description", "prompt", "skill",
               "title", "name", "subject", "taskId", "id")


def alvo_da_ferramenta(nome, entrada):
    """Resumo curto e mascarado do que a ferramenta fez ('Read' -> caminho, 'Bash' -> comando...)."""
    if not isinstance(entrada, dict):
        return ""
    if nome in ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        return encurtar(entrada.get("file_path") or entrada.get("notebook_path") or "", 200)
    if nome in ("Bash", "PowerShell"):
        return encurtar(entrada.get("command") or "", 220)
    if nome in ("Grep", "Glob"):
        alvo = entrada.get("pattern") or ""
        onde = entrada.get("path") or ""
        return encurtar(alvo + (f"  em {onde}" if onde else ""), 200)
    if nome in ("Agent", "Task"):
        return encurtar(entrada.get("description") or entrada.get("subagent_type") or "", 200)
    for k in _ORDEM_ALVO:
        v = entrada.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return encurtar(str(v), 200)
    return encurtar(", ".join(list(entrada)[:6]), 120)


def passos_da_linha(obj, ferramentas):
    """Converte uma linha do transcrito em 0..n passos para mostrar. 'ferramentas' (id -> nome) é o dicionário que o
    chamador mantém entre linhas, para dar nome ao resultado de cada chamada."""
    if not isinstance(obj, dict) or obj.get("type") not in ("assistant", "user"):
        return []
    m = obj.get("message")
    if not isinstance(m, dict):
        return []
    ts = para_epoch(obj.get("timestamp"))
    c = m.get("content")
    passos = []
    if obj["type"] == "assistant":
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
        for b in c if isinstance(c, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and (b.get("text") or "").strip():
                passos.append({"t": ts, "tipo": "texto", "texto": encurtar(b["text"], 700)})
            elif b.get("type") == "tool_use":
                nome = str(b.get("name") or "ferramenta")
                if b.get("id"):
                    ferramentas[b["id"]] = nome
                passos.append({"t": ts, "tipo": "ferramenta", "nome": nome, "alvo": alvo_da_ferramenta(nome, b.get("input"))})
        return passos
    # usuário: ou o pedido digitado, ou o resultado de uma ferramenta
    if isinstance(c, str):
        c = [{"type": "text", "text": c}]
    for b in c if isinstance(c, list) else []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_result":
            conteudo = b.get("content")
            texto = conteudo if isinstance(conteudo, str) else _texto_do_conteudo(conteudo)
            nome = ferramentas.get(b.get("tool_use_id"), "")
            tam = len(texto)
            if nome in ("Read", "NotebookRead") or tam > 4000:
                # arquivo lido (ou saída enorme): só o tamanho, nunca o conteúdo
                resumo = f"({tam:,} caracteres)".replace(",", ".")
            else:
                resumo = encurtar(texto, 240)
            passos.append({"t": ts, "tipo": "resultado", "nome": nome, "texto": resumo, "tam": tam,
                           "erro": bool(b.get("is_error"))})
        elif b.get("type") == "text" and (b.get("text") or "").strip():
            bruto = b["text"]
            limpo = _TAGS_INTERNAS.sub("", _LEMBRETE.sub("", bruto)).strip()
            if limpo:
                passos.append({"t": ts, "tipo": "usuario", "texto": encurtar(limpo, 500)})
            elif "<system-reminder>" in bruto:
                passos.append({"t": ts, "tipo": "sistema", "texto": "(lembrete do sistema)"})
    return passos


def ler_passos(caminho, desde, ferramentas, limite_bytes=None):
    """Passos escritos depois da posição 'desde'. Devolve (passos, nova_posição). Só avança em linhas completas."""
    passos = []
    pos = desde
    try:
        with open(caminho, "rb") as f:
            f.seek(desde)
            lido = 0
            for linha in f:
                if not linha.endswith(b"\n"):
                    break
                pos += len(linha)
                lido += len(linha)
                if len(linha) > 3_000_000:                 # linha monstruosa (anexo/imagem): ignora
                    continue
                if not _tem_tipo(linha, b"assistant") and not _tem_tipo(linha, b"user"):
                    continue
                try:
                    passos.extend(passos_da_linha(json.loads(linha), ferramentas))
                except (ValueError, TypeError, AttributeError):
                    continue
                if limite_bytes and lido >= limite_bytes:
                    break
    except OSError:
        pass
    return passos, pos


def posicao_inicial_da_cauda(caminho, bytes_cauda=300_000):
    """Posição (alinhada ao início de uma linha) para mostrar só o final do arquivo na primeira abertura."""
    tam = os.path.getsize(caminho)
    if tam <= bytes_cauda:
        return 0
    with open(caminho, "rb") as f:
        f.seek(tam - bytes_cauda)
        f.readline()                                        # descarta a linha cortada ao meio
        return f.tell()
