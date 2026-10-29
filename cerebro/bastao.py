"""Passa-bastão de conversa longa (SEM IA): avisa quando o contexto de uma sessão passou do limite e monta um resumo pronto
para colar numa conversa nova.

Tamanho do contexto = entrada + leitura de cache + escrita de cache do ÚLTIMO turno do assistente (é o que o modelo leu
naquele momento). Limite padrão: 60% de 200 mil tokens (config.json > "bastao": janela_tokens, limite_pct, recentes_horas).
"Automático" = o aviso aparece sozinho na sessão e em "Precisa de você"; nada é enviado a lugar nenhum.

O resumo junta, do transcrito e do Cérebro: objetivo inicial (primeira mensagem do usuário), últimos pedidos do usuário,
arquivos mais editados, últimas decisões registradas, tarefas abertas do Cérebro e memórias criadas na sessão. Passa por
segredos.mascarar() e fica em ~/.cerebro/projetos/<slug>/bastao/<sessao>.md. Função pública: resumo(slug, sessao_id) -> str.
"""
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from . import config, decisoes, indice, memoria, propostas, transcricao
from .segredos import encurtar, mascarar

PADRAO = {"janela_tokens": 200_000, "limite_pct": 60, "recentes_horas": 72}
ID_SESSAO = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
FERRAMENTAS_EDICAO = ("Edit", "Write", "MultiEdit", "NotebookEdit")
ULTIMOS_PEDIDOS = 6


def parametros(cfg=None):
    b = dict(PADRAO)
    extra = (cfg or {}).get("bastao")
    if isinstance(extra, dict):
        for k in PADRAO:
            v = extra.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                b[k] = v
    b["limite_tokens"] = int(b["janela_tokens"] * min(b["limite_pct"], 100) / 100)
    return b


def contexto_do_indice(ind):
    """Tokens de contexto do último turno do assistente (entrada + cache lido + cache escrito). 0 se não houver."""
    msgs = (ind or {}).get("msgs") or {}
    if not msgs:
        return 0
    ultima = None
    for v in msgs.values():                        # empate de horário: vale a gravada por último (ordem do arquivo)
        if ultima is None or (v[0] or 0) >= (ultima[0] or 0):
            ultima = v
    try:
        return int(ultima[2] + ultima[4] + ultima[5] + ultima[6])
    except (IndexError, TypeError):
        return 0


JANELA_GRANDE = 1_000_000          # modelos com janela de 1 milhão de tokens (ex.: Opus/Sonnet com contexto longo)


def janela_efetiva(ctx, janela):
    """A janela real da conversa: se o contexto já passou da janela configurada, o modelo tem a janela grande (1 milhão)."""
    return JANELA_GRANDE if janela and ctx > janela else janela


def estado_sessao(ind, cfg=None):
    b = parametros(cfg)
    ctx = contexto_do_indice(ind)
    jan = janela_efetiva(ctx, b["janela_tokens"])
    limite = int(jan * min(b["limite_pct"], 100) / 100)
    return {"contexto": ctx, "pct": round(100 * ctx / jan, 1) if jan else 0, "janela": jan,
            "longa": ctx >= limite, "limite_tokens": limite}


def sessoes_longas(slug, cfg=None, agora=None):
    """Sessões principais (não subagentes) mexidas nas últimas 'recentes_horas' com o contexto acima do limite (sem ler arquivos)."""
    b = parametros(cfg)
    agora = agora or time.time()
    saida = []
    for a in indice.listar_arquivos(slug):
        if a["tipo"] != "sessao" or agora - a["mtime"] > b["recentes_horas"] * 3600:
            continue
        ind = indice.indice_se_existe(slug, a["rel"])
        e = estado_sessao(ind, cfg)
        if e["longa"]:
            tit = transcricao.titulo_do_indice(ind or {}, a["id"][:8])
            saida.append({"sessao": a["id"], "titulo": encurtar(tit, 120), "mtime": a["mtime"], **e,
                          "resumo_pronto": (_pasta(slug) / f"{a['id']}.md").is_file()})
    saida.sort(key=lambda s: -s["contexto"])
    return saida


def itens_fila(p, cfg=None):
    itens = []
    gestora = (((cfg or {}).get("gestoras") or {}).get(p["slug"]) or {}).get("conversa")
    for s in sessoes_longas(p["slug"], cfg):
        if s["sessao"] == gestora:                 # a gestora tem aviso próprio, com a troca assistida (gestora_troca.py)
            continue
        itens.append({"nivel": "acao", "projeto": p["slug"], "titulo": f"{p['nome']}: conversa longa — passar o bastão",
                      "texto": f"A sessão \"{s['titulo']}\" está com ≈ {s['contexto'] // 1000} mil tokens de contexto ({s['pct']}% da janela). "
                               "Gere o resumo de passa-bastão (aba Sessões) e continue numa conversa nova: cada mensagem nela fica mais cara.",
                      "aba": "sessoes"})
    return itens


# ---------------------------------------------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------------------------------------------
def _pasta(slug):
    return config.pasta_projeto(slug) / "bastao"


# Texto que NÃO foi digitado pelo dono: avisos do sistema, recados entre sessões e agentes, notificações de tarefa,
# ganchos, comandos locais. Saem dos "últimos pedidos" (o capítulo da gestora chegou a mostrar esses textos como pedido).
_BLOCOS_MAQUINA = re.compile(r"<(system-reminder|side-sessions-event|cross-session-message|task-notification|agent-message|"
                             r"user-prompt-submit-hook|command-[a-z-]+|local-command-[a-z-]+|bash-[a-z]+|ide_[a-z_]+)\b[^>]*>.*?</\1>",
                             re.S | re.I)
_INICIO_MAQUINA = re.compile(r"\s*(?:<[a-z][a-z0-9]*[-_][a-z0-9_-]*[\s>/]|\[SYSTEM NOTIFICATION|\[Request interrupted|Caveat: |"
                             r"This session is being continued|\S+ hook (?:feedback|error|blocked|additional context|success)\b)", re.I)
# Mensagem que o dono mandou no meio do turno, como o Claude Code mostra ao modelo. Só vale no começo do bloco ou dentro de um
# aviso do sistema (assim um arquivo lido que cite a frase não vira pedido).
_MEIO_TURNO = re.compile(r"(?:^|<system-reminder[^>]*>)\s*The user sent a new message while you were working:[ \t]*\n(.*?)"
                         r"(?=\n[ \t]*\n[ \t]*This is how Claude Code surfaces|</system-reminder>|\Z)", re.S)
_RESPOSTAS = "Your questions have been answered:"
_PAR_RESPOSTA = re.compile(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)
_TOKEN_CAMINHO = r"(\"[^\"\n]+\"|'[^'\n]+'|[^\s\"'|;&<>()]+)"
_REDIRECIONA = re.compile(r"(?:\d?>>?|\btee\b(?:\s+-{1,2}[a-z]+)*)\s*" + _TOKEN_CAMINHO, re.I)
_PS_ESCRITA = re.compile(r"\b(?:Add-Content|Set-Content|Out-File)\b([^|;\n]*)", re.I)
_ARQ_MEMORIA = re.compile(r"(?:^|/)memory/+([A-Za-z0-9_.\-]+\.md)$", re.I)
_PROJETO_NO_CAMINHO = re.compile(r"/projects/([^/]+)/memory/", re.I)


def _texto_do_resultado(b):
    c = b.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x["text"] for x in c if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str))
    return ""


def _limpar_digitado(t):
    """Texto puro digitado: tira blocos de máquina; '' se o que sobra começa com marca de sistema, gancho ou comando."""
    t = _BLOCOS_MAQUINA.sub("", t or "").strip()
    return "" if not t or _INICIO_MAQUINA.match(t) else t


def respostas_formulario(t):
    """'Your questions have been answered: "P"="R", ...' -> 'Respostas do formulário: P → R; ...' ('' se não for isso)."""
    t = (t or "").lstrip()
    if not t.startswith(_RESPOSTAS):
        return ""
    corpo = t[len(_RESPOSTAS):].split("You can now continue", 1)[0]
    pares = _PAR_RESPOSTA.findall(corpo)
    if pares:
        return "Respostas do formulário: " + "; ".join(f"{p.strip()} → {r.strip()}" for p, r in pares)
    corpo = corpo.strip().rstrip(".").strip()
    return "Respostas do formulário: " + corpo if corpo else ""


def _origem_humana(d):
    """Sem o campo origin (transcrições antigas) vale só o filtro de texto; com ele, só 'human'."""
    ori = d.get("origin")
    return not isinstance(ori, dict) or not ori.get("kind") or ori.get("kind") == "human"


def pedidos_do_dono(o):
    """Textos do DONO numa linha do transcrito, na ordem: mensagem digitada de verdade, respostas de formulário
    (AskUserQuestion) e mensagens mandadas no meio do turno. Recados entre sessões, notificações, ganchos, comandos e
    resultados de ferramenta não entram."""
    if not isinstance(o, dict) or o.get("isSidechain") or o.get("isCompactSummary"):
        return []
    if o.get("type") == "attachment":                       # mensagem do dono que ficou na fila no meio do turno
        a = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
        if a.get("type") != "queued_command" or a.get("isMeta") or not _origem_humana(a) or a.get("commandMode") not in (None, "prompt"):
            return []
        p = a.get("prompt")
        t = _limpar_digitado(p if isinstance(p, str) else transcricao._texto_do_conteudo(p))
        return [t] if t else []
    if o.get("type") != "user":
        return []
    m = o.get("message") if isinstance(o.get("message"), dict) else {}
    c = m.get("content")
    blocos = [{"type": "text", "text": c}] if isinstance(c, str) else [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []
    saida = []
    for b in blocos:
        if b.get("type") == "tool_result":
            t = _texto_do_resultado(b)
        elif b.get("type") == "text" and isinstance(b.get("text"), str):
            t = b["text"]
        else:
            continue
        meio = [x.strip() for x in _MEIO_TURNO.findall(t) if x.strip()]
        saida += meio
        if b.get("type") == "tool_result":
            r = respostas_formulario(t)
            if r:
                saida.append(r)
            continue
        if o.get("isMeta") or not _origem_humana(o) or (meio and _MEIO_TURNO.match(t)):
            continue
        t = _limpar_digitado(t)
        if t:
            saida.append(t)
    return saida


def _alvos_memoria_no_comando(cmd, mem_base, slug):
    """Arquivos memory/*.md que um comando Bash/PowerShell ESCREVE (>, >>, tee, cat <<EOF >, Add-Content/Set-Content/Out-File)."""
    candidatos = [m.group(1) for m in _REDIRECIONA.finditer(cmd)]
    for m in _PS_ESCRITA.finditer(cmd):
        candidatos += re.findall(_TOKEN_CAMINHO, m.group(1))
    nomes = []
    for c in candidatos:
        c = c.strip("\"'").replace("\\", "/")
        a = _ARQ_MEMORIA.search(c)
        if not a:
            continue
        outro = _PROJETO_NO_CAMINHO.search(c)
        if outro and slug and outro.group(1).lower() != slug.lower():
            continue                                        # memória de OUTRO projeto
        if (outro or c.lower().startswith(mem_base) or (Path(mem_base) / a.group(1)).is_file()) and a.group(1) not in nomes:
            nomes.append(a.group(1))
    return nomes


def _linhas_novas(antes, depois):
    velhas = set(str(antes or "").splitlines())
    return [x for x in str(depois or "").splitlines() if x.strip() and x not in velhas]


def _pergunta_texto(q):
    opcoes = [str(x.get("label", "")) for x in q.get("options") or [] if isinstance(x, dict)]
    return str(q.get("question") or "") + (f" (opções: {', '.join(opcoes)})" if opcoes else "")


def ler_sessao(caminho, pasta_mem, slug=""):
    """Uma passada pelo JSONL. Devolve um dict:
      primeira / pedidos      primeira e últimas mensagens do DONO (ver pedidos_do_dono)
      edicoes / memorias      arquivos editados (Counter) e memórias criadas com Write
      cwd / ramo / inicio     pasta e ramo do git das ÚLTIMAS mensagens (a sessão pode estar numa worktree) e o horário
                              (epoch) da primeira mensagem
      ultima_resposta         o último texto do assistente (costuma ter a pergunta pendente ao dono)
      mem_mexidas             {arquivo: {"como": [ferramentas], "novas": [linhas acrescentadas por Edit]}}, inclusive por
                              Bash/PowerShell (>>, tee, cat <<EOF >, Add-Content...)
      perguntas_abertas       perguntas de formulário (AskUserQuestion) ainda sem resposta"""
    s = {"primeira": "", "pedidos": [], "edicoes": Counter(), "memorias": [], "cwd": "", "cwd_inicio": "", "ramo": "",
         "inicio": None, "ultima_resposta": "", "mem_mexidas": {}, "perguntas_abertas": {}}
    mem_base = str(pasta_mem).replace("\\", "/").lower().rstrip("/") + "/"
    ultima_id = None

    def mexeu(nome, como, novas=()):
        e = s["mem_mexidas"].setdefault(nome, {"como": [], "novas": []})
        if como not in e["como"]:
            e["como"].append(como)
        e["novas"] = (e["novas"] + list(novas))[-20:]

    with open(caminho, "rb") as f:
        for linha in f:
            if not linha.endswith(b"\n") or len(linha) > 3_000_000:
                continue
            if not (transcricao._tem_tipo(linha, b"user") or transcricao._tem_tipo(linha, b"assistant") or b'"queued_command"' in linha):
                continue
            try:
                o = json.loads(linha)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain") or o.get("isCompactSummary"):
                continue
            if s["inicio"] is None and o.get("type") in ("user", "assistant", "attachment"):
                s["inicio"] = transcricao.para_epoch(o.get("timestamp"))
            if o.get("cwd"):
                s["cwd"] = str(o["cwd"])
                s["cwd_inicio"] = s["cwd_inicio"] or s["cwd"]
            if o.get("gitBranch"):
                s["ramo"] = str(o["gitBranch"])
            for t in pedidos_do_dono(o):
                if t in s["pedidos"][-2:]:                   # a mesma mensagem vista duas vezes (fila + aviso)
                    continue
                s["primeira"] = s["primeira"] or t
                s["pedidos"].append(t)
                del s["pedidos"][:-ULTIMOS_PEDIDOS]
            m = o.get("message") if isinstance(o.get("message"), dict) else {}
            blocos = [b for b in m.get("content") if isinstance(b, dict)] if isinstance(m.get("content"), list) else []
            if o.get("type") == "user":
                for b in blocos:
                    if b.get("type") == "tool_result":
                        s["perguntas_abertas"].pop(b.get("tool_use_id"), None)
                continue
            if o.get("type") != "assistant" or o.get("isMeta"):
                continue
            texto = transcricao._texto_do_conteudo(m.get("content")).strip()
            if texto:                                       # a mesma resposta pode vir em várias linhas (mesmo id)
                junta = m.get("id") and m.get("id") == ultima_id
                s["ultima_resposta"] = s["ultima_resposta"] + "\n\n" + texto if junta else texto
                ultima_id = m.get("id")
            for b in blocos:
                if b.get("type") != "tool_use":
                    continue
                ferramenta = b.get("name")
                ent = b.get("input") if isinstance(b.get("input"), dict) else {}
                if ferramenta == "AskUserQuestion":
                    s["perguntas_abertas"][b.get("id")] = [_pergunta_texto(q) for q in ent.get("questions") or [] if isinstance(q, dict)]
                    continue
                if ferramenta in ("Bash", "PowerShell") and isinstance(ent.get("command"), str):
                    for nome in _alvos_memoria_no_comando(ent["command"], mem_base, slug):
                        mexeu(nome, ferramenta)
                    continue
                if ferramenta not in FERRAMENTAS_EDICAO:
                    continue
                alvo = str(ent.get("file_path") or ent.get("notebook_path") or "")
                if not alvo:
                    continue
                s["edicoes"][alvo] += 1
                norm = alvo.replace("\\", "/").lower()
                if not (norm.startswith(mem_base) and norm.endswith(".md")):
                    continue
                if ferramenta == "Write" and not norm.endswith("/memory.md"):
                    s["memorias"].append(Path(alvo).name)
                pares = ent.get("edits") if ferramenta == "MultiEdit" and isinstance(ent.get("edits"), list) else [ent]
                mexeu(Path(alvo).name, ferramenta,
                      [x for e in pares if isinstance(e, dict) for x in _linhas_novas(e.get("old_string"), e.get("new_string"))])
    s["perguntas_abertas"] = [q for lista in s["perguntas_abertas"].values() for q in lista if q]
    return s


def _relativo(caminho, cwd):
    c = caminho.replace("\\", "/")
    base = (cwd or "").replace("\\", "/").rstrip("/") + "/"
    if cwd and c.lower().startswith(base.lower()):
        return c[len(base):]
    return c


def _memorias_da_sessao(slug, sessao_id, escritas):
    """Memórias com originSessionId = esta sessão, mais as que o transcrito mostra sendo escritas (Write)."""
    pm = memoria.pasta_memoria(slug)
    achadas = {}
    if pm.is_dir():
        for f in sorted(pm.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            campos, _ = memoria._cabecalho(memoria._ler(f) or "")
            if campos.get("originSessionId") == sessao_id or f.name in escritas:
                achadas[f.name] = campos.get("description") or campos.get("name") or ""
    for nome in escritas:
        achadas.setdefault(nome, "(arquivo não está mais na pasta de memória)")
    return achadas


def montar(slug, sessao_id, cfg=None):
    """Texto do passa-bastão (já mascarado), sem gravar."""
    if not ID_SESSAO.match(sessao_id or ""):
        raise ValueError("sessão inválida")
    caminho = indice.pasta_claude(slug) / f"{sessao_id}.jsonl"
    if not caminho.is_file():
        raise ValueError("sessão não encontrada neste projeto")
    cfg = cfg if cfg is not None else config.ler_config()
    pm = memoria.pasta_memoria(slug)
    sessao = ler_sessao(caminho, pm, slug)
    primeira, pedidos, edicoes, cwd = sessao["primeira"], sessao["pedidos"], sessao["edicoes"], sessao["cwd"]
    escritas = sessao["memorias"] + [n for n in sessao["mem_mexidas"] if n not in sessao["memorias"] and n != "MEMORY.md"]
    ind = indice.indice_se_existe(slug, f"{sessao_id}.jsonl")
    if ind is None:
        try:
            ind, _ = transcricao.atualizar_indice(caminho)
        except OSError:
            ind = {}
    est = estado_sessao(ind, cfg)
    titulo = transcricao.titulo_do_indice(ind or {}, sessao_id[:8])
    L = [f"# Passa-bastão: {encurtar(titulo, 120)}", "",
         f"Resumo gerado pelo Cérebro do Projeto em {time.strftime('%d/%m/%Y %H:%M')}, sem IA, a partir da conversa {sessao_id}.",
         f"A conversa antiga estava com ≈ {est['contexto']:,} tokens de contexto ({est['pct']}% da janela).".replace(",", "."),
         "Cole este texto no começo de uma conversa nova para continuar de onde parou.", ""]
    L += ["## Objetivo inicial", "", "> " + encurtar(primeira, 900).replace("\n", "\n> ") if primeira else "(não achei a primeira mensagem)", ""]
    L += ["## Últimos pedidos do usuário (do mais antigo ao mais novo)", ""]
    L += [f"{i}. " + encurtar(p, 400).replace("\n", " ") for i, p in enumerate(pedidos, 1)] or ["(nenhum)"]
    L += ["", "## Arquivos mais editados nesta conversa", ""]
    L += [f"- {_relativo(a, cwd)} ({n} {'edição' if n == 1 else 'edições'})" for a, n in edicoes.most_common(12)] or ["(nenhum arquivo editado)"]
    L += ["", "## Últimas decisões registradas no Cérebro", ""]
    try:
        decs = decisoes.listar(slug, 8, so_ativas=True)
    except ValueError:
        decs = []
    L += [f"- [{d['tipo'].upper()}] {encurtar(d['texto'], 300)} ({time.strftime('%d/%m', time.localtime(d['em']))})" for d in decs] or ["(nenhuma)"]
    L += ["", "## Tarefas abertas do Cérebro (aprovadas, esperando o gestor)", ""]
    try:
        tarefas = [t for t in propostas.tarefas(slug) if t.get("estado") == "aberta"]
    except (ValueError, OSError):
        tarefas = []
    L += [f"- {t.get('id', '')}: {encurtar(t.get('titulo', ''), 200)}" for t in tarefas[:10]] or ["(nenhuma)"]
    L += ["", "## Memórias criadas nesta conversa", ""]
    L += [f"- {n}: {encurtar(desc, 200)}" for n, desc in _memorias_da_sessao(slug, sessao_id, escritas).items()] or ["(nenhuma)"]
    L += ["", "## Como continuar", "",
          "- Leia os arquivos acima antes de mexer neles e confira o estado atual (git status, testes).",
          "- Siga as regras do CLAUDE.md e da memória do projeto (já carregadas na conversa nova).",
          "- Se algo deste resumo não bater com o código, vale o código.", ""]
    return mascarar("\n".join(L))


def resumo(slug, sessao_id):
    """PÚBLICA (para um gancho futuro): monta o passa-bastão, grava em ~/.cerebro/projetos/<slug>/bastao/<sessao>.md e devolve o texto."""
    texto = montar(slug, sessao_id)
    destino = _pasta(slug)
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / f"{sessao_id}.md"
    tmp = arq.with_name(arq.name + f".{os.getpid()}.tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(tmp, arq)
    return texto


def caminho_resumo(slug, sessao_id):
    if not ID_SESSAO.match(sessao_id or ""):
        raise ValueError("sessão inválida")
    return _pasta(slug) / f"{sessao_id}.md"
