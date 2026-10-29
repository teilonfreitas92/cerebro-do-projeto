"""Capítulos da sessão GESTORA: renovação automática pelos ganchos oficiais do Claude Code (sem IA, sem trocar de sessão).

  * PreCompact (o Claude Code vai compactar a conversa): se a sessão é a GESTORA do projeto no config, grava um capítulo datado
    em ~/.cerebro/projetos/<slug>/capitulos/<AAAA-MM-DD_HHMMSS>_<sessao8>.md: resumo curto no topo, em ordem de prioridade (última
    mensagem da sessão com a pergunta pendente, pasta de trabalho/ramo/commit da sessão — que pode ser uma worktree —, pendências,
    últimos pedidos do DONO, commits da sessão) e, abaixo, detalhes (worktrees, memória editada, arquivos, decisões) e o
    passa-bastão completo. Outras sessões: nada. Git só leitura (projetos._git: sem shell, com tempo limite).
  * `gestora limpar` (antes do clear_session na mesma sessão) grava um capítulo da mesma forma e confere que ele está completo.
  * SessionStart com source "clear" ou "compact": o cerebro_hook.py --sincrono devolve ao Claude Code, como additionalContext,
    uma linha apontando o ~/.cerebro/GESTOR.md + o RESUMO do último capítulo (até ~1.500 tokens; ver gestora_troca.ao_iniciar_sessao).
    Esse caminho lê só arquivos de ~/.cerebro (funciona com o painel fechado) e nunca demora: ver texto_contexto().
Capítulos ficam para sempre. Retenção opcional: config.json > "capitulos" > "manter_dias" (0 = nunca apagar, o padrão); quando
ligada, só remove capítulos desta pasta, pela trava única config.remover().
"""
import re
import time
from pathlib import Path

from . import config, decisoes, indice, memoria
from .segredos import encurtar, mascarar

FIM_RESUMO = "<!-- cerebro:fim-do-resumo -->"
NOME = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{6})_([A-Za-z0-9_\-]{1,8})\.md$")
LIMITE_CONTEXTO_CHARS = 6000          # ≈ 1.500 tokens (caracteres/4)
RAMO_VALIDO = re.compile(r"^(?!-)[A-Za-z0-9._/\-]{1,200}$")


def pasta(slug):
    p = config.pasta_projeto(slug) / "capitulos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def eh_gestora(slug, sessao_id, cfg=None):
    cfg = cfg if cfg is not None else config.ler_config()
    return bool(sessao_id) and ((cfg.get("gestoras") or {}).get(slug) or {}).get("conversa") == sessao_id


# ---------------------------------------------------------------------------------------------------------------
# Git da sessão (só leitura; sem shell, com tempo limite: ver projetos._git)
# ---------------------------------------------------------------------------------------------------------------
def _git(pasta, *args):
    """Ponto único das chamadas ao git deste módulo (os testes trocam por um falso)."""
    from . import projetos
    return projetos._git(pasta, *args)


def _norm(c):
    return str(c or "").replace("\\", "/").rstrip("/").lower()


def _worktrees(porcelana):
    """`git worktree list --porcelain` -> [{caminho, ramo, head}]."""
    lista, atual = [], None
    for linha in (porcelana or "").splitlines():
        if linha.startswith("worktree "):
            atual = {"caminho": linha[9:].strip(), "ramo": "", "head": ""}
            lista.append(atual)
        elif atual is not None and linha.startswith("HEAD "):
            atual["head"] = linha[5:12]
        elif atual is not None and linha.startswith("branch "):
            atual["ramo"] = linha[7:].strip().removeprefix("refs/heads/")
        elif atual is not None and linha.strip() == "detached":
            atual["ramo"] = "(sem ramo)"
    return lista[:20]


def _commits(saida):
    itens = []
    for linha in (saida or "").splitlines():
        partes = linha.split("\x1f")
        if len(partes) >= 2 and partes[0].strip():
            itens.append({"hash": partes[0].strip(), "assunto": partes[1].strip()})
    return itens


def estado_git(pasta, ramo_sessao="", inicio=None):
    """Pasta de TRABALHO da sessão (pode ser uma worktree), ramo e commit atual dela, worktrees do projeto e os commits feitos
    desde o início da sessão no ramo da sessão (sem início conhecido: os últimos 10). Tudo só leitura."""
    g = {"pasta": str(pasta or ""), "ramo": "", "ramo_sessao": ramo_sessao or "", "commit": "", "worktrees": [], "commits": [],
         "desde": inicio}
    if not pasta or not Path(pasta).is_dir():
        return g
    g["ramo"] = _git(pasta, "rev-parse", "--abbrev-ref", "HEAD")
    if not g["ramo"]:
        return g                                            # sem git (ou git indisponível)
    ultimo = _commits(_git(pasta, "log", "-1", "--format=%h%x1f%s"))
    g["commit"] = f"{ultimo[0]['hash']} {ultimo[0]['assunto']}" if ultimo else ""
    g["worktrees"] = _worktrees(_git(pasta, "worktree", "list", "--porcelain"))
    base = ["log", "--format=%h%x1f%s"]
    base += ([f"--since={time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(inicio))} +0000", "-n", "30"] if inicio else ["-n", "10"])
    ref = ramo_sessao if RAMO_VALIDO.match(ramo_sessao or "") else "HEAD"
    saida = _git(pasta, *base, ref, "--")
    if not saida and ref != "HEAD":                         # o ramo da transcrição sumiu: vale o ramo atual da pasta
        saida = _git(pasta, *base, "HEAD", "--")
    g["commits"] = _commits(saida)
    return g


# ---------------------------------------------------------------------------------------------------------------
# Pendências e memória
# ---------------------------------------------------------------------------------------------------------------
def _a_conferir(slug, cfg, agora):
    """Subagentes da gestora que terminaram e ainda não foram conferidos (mesma conta de revisoes.contagem)."""
    from . import revisoes
    gid = revisoes._gestora(cfg, slug)
    if not gid:
        return []
    corte = agora - int(cfg.get("revisao_dias") or 7) * 86400
    feitos = revisoes._dados(slug)["itens"]
    return [it for it in revisoes._terminados(slug, gid, corte) if it["id"] not in feitos]


def pendencias(slug, cfg, perguntas, agora):
    """Linhas '- ...': perguntas de formulário sem resposta, tarefas abertas do Cérebro e subagentes a conferir."""
    from . import tarefas_gestor
    L = [f"- Pergunta ao dono ainda sem resposta: {encurtar(q, 300)}" for q in perguntas[-3:]]
    try:
        tarefas = tarefas_gestor.listar(slug, cfg, incluir_finais=False)
    except (OSError, ValueError):
        tarefas = []
    L += [f"- Tarefa {t.get('id', '')} [{t.get('estado_rotulo') or t.get('estado', '')}]: {encurtar(t.get('titulo', ''), 140)}"
          for t in tarefas[:6]]
    if len(tarefas) > 6:
        L.append(f"- (+{len(tarefas) - 6} tarefa(s) aberta(s) na aba Tarefas)")
    try:
        conferir = _a_conferir(slug, cfg, agora)
    except (OSError, ValueError):
        conferir = []
    L += [f"- A conferir: subagente {x.get('tipo_agente') or ''} \"{encurtar(x['descricao'], 120)}\"".replace("  ", " ") for x in conferir[:5]]
    if len(conferir) > 5:
        L.append(f"- (+{len(conferir) - 5} subagente(s) a conferir na aba A conferir)")
    return L


def _memoria_mexida(slug, mexidas):
    """Para cada memória mexida na sessão: as linhas que as edições acrescentaram (Edit) ou, sem isso (Write, Bash,
    PowerShell), as últimas ~5 linhas do arquivo como está agora."""
    pm = memoria.pasta_memoria(slug)
    L = []
    for nome, e in list(mexidas.items())[:10]:
        if e["novas"]:
            linhas, rotulo = e["novas"][-5:], "linhas acrescentadas"
        else:
            try:
                texto = (pm / nome).read_text(encoding="utf-8", errors="replace")
            except OSError:
                texto = ""
            linhas, rotulo = [x for x in texto.splitlines() if x.strip()][-5:], "fim do arquivo agora"
        L.append(f"- {nome} (por {', '.join(e['como'])}; {rotulo}):")
        L += [f"    {encurtar(x, 200)}" for x in linhas] or ["    (arquivo não está mais na pasta de memória)"]
    return L


# ---------------------------------------------------------------------------------------------------------------
# Capítulo
# ---------------------------------------------------------------------------------------------------------------
LIMITE_ULTIMA = 3000            # a última mensagem da sessão entra INTEIRA até este tamanho
FOLGA_CONTEXTO = 450            # o cabeçalho que texto_contexto() põe na frente do resumo


def _sem_o_meio(texto, limite):
    """Corta o MEIO (a pergunta pendente costuma estar no fim da mensagem): ~1/3 do começo + o fim."""
    if len(texto) <= limite:
        return texto
    marca = "\n[… trecho do meio no capítulo completo …]\n"
    cabeca = max(0, (limite - len(marca)) // 3)
    return texto[:cabeca].rstrip() + marca + texto[len(texto) - (limite - len(marca) - cabeca):].lstrip()


def _citar(texto):
    return "\n".join("> " + x if x.strip() else ">" for x in texto.splitlines()) or "> (vazia)"


def montar(slug, sessao_id, cfg=None, agora=None):
    """Texto do capítulo (mascarado). Em cima, o RESUMO que volta na conversa depois de compactar/limpar (cabe em
    LIMITE_CONTEXTO_CHARS), em ordem de prioridade: última mensagem (pergunta pendente), pasta/ramo/commit da sessão,
    pendências, últimos pedidos do dono, commits da sessão. Embaixo do separador: detalhes e o passa-bastão completo."""
    from . import bastao, projetos
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    caminho = indice.pasta_claude(slug) / f"{sessao_id}.jsonl"
    s = bastao.ler_sessao(caminho, memoria.pasta_memoria(slug), slug)
    p = projetos.achar(slug) or {}
    principal = p.get("caminho") or ""
    pasta_trab = s["cwd"] if s["cwd"] and Path(s["cwd"]).is_dir() else (principal or s["cwd"])
    g = estado_git(pasta_trab, s["ramo"], s["inicio"])
    eh_worktree = bool(principal) and _norm(pasta_trab) != _norm(principal)
    data = time.strftime("%d/%m/%Y %H:%M", time.localtime(agora))

    # --- peças do resumo (menos a última mensagem, que fica com o espaço que sobrar)
    G = ["## Pasta de trabalho e git da sessão (só leitura)", "",
         f"- Pasta de trabalho: {pasta_trab or '(desconhecida)'}" + (" (worktree, não é a pasta principal)" if eh_worktree else "")]
    if g["ramo"]:
        G.append(f"- Ramo do git: {g['ramo']} · commit atual: {encurtar(g['commit'], 140) or '?'}")
        if g["ramo_sessao"] and g["ramo_sessao"] != g["ramo"]:
            G.append(f"- A transcrição registrava o ramo {g['ramo_sessao']} nas últimas mensagens.")
    else:
        G.append(f"- Ramo do git: {g['ramo_sessao'] or '(sem git)'} (lido da transcrição; git indisponível nesta pasta)")
    if eh_worktree:
        G.append(f"- Pasta principal do projeto: {principal}")
    P = ["## Pendências abertas", ""] + (pendencias(slug, cfg, s["perguntas_abertas"], agora) or ["(nenhuma registrada no Cérebro)"])
    U = ["## Últimos pedidos do dono", ""] + ([f"- {encurtar(t, 200).replace(chr(10), ' ')}" for t in s["pedidos"][-3:]] or ["(nenhum)"])
    desde = time.strftime("%d/%m %H:%M", time.localtime(s["inicio"])) if s["inicio"] else ""
    C = [f"## Commits desta sessão ({'desde ' + desde if desde else 'últimos 10'}, ramo {g['ramo_sessao'] or g['ramo'] or '?'})", ""]
    C += [f"- {c['hash']} {encurtar(c['assunto'], 90)}" for c in g["commits"][:5]] or ["(nenhum)"]
    if len(g["commits"]) > 5:
        C.append(f"- (+{len(g['commits']) - 5} no capítulo completo, abaixo)")
    topo = [f"# Capítulo da gestora — {data}", "",
            f"Gravado pelo Cérebro (sem IA) antes de a conversa {sessao_id} ser compactada ou limpa.", ""]
    resto = ["", *G, "", *P, "", *U, "", *C, ""]
    titulo_ultima = "## Onde parou — última mensagem da sessão (pode ter pergunta pendente ao dono)"
    ocupado = len(mascarar("\n".join(topo[2:] + resto))) + len(titulo_ultima) + FOLGA_CONTEXTO
    ultima = mascarar(s["ultima_resposta"].strip())
    cabe = min(LIMITE_ULTIMA, max(600, LIMITE_CONTEXTO_CHARS - ocupado))
    cortada = len(ultima) > cabe
    L = topo + [titulo_ultima, "", _citar(_sem_o_meio(ultima, cabe)) if ultima else "(sem respostas de texto)"] + resto

    # --- detalhes (só no arquivo)
    try:
        decs = decisoes.listar(slug, 5, so_ativas=True)
    except ValueError:
        decs = []
    L += [FIM_RESUMO, "", "## Detalhes do capítulo", ""]
    if cortada:
        L += ["### Última mensagem da sessão (completa)", "", _citar(_sem_o_meio(ultima, LIMITE_ULTIMA)), ""]
    L += ["### Worktrees do projeto", ""]
    L += [f"- {w['caminho']} — {w['ramo'] or '?'} {w['head']}" + (" ← esta sessão" if _norm(w["caminho"]) == _norm(pasta_trab) else "")
          for w in g["worktrees"]] or ["(nenhuma além da pasta principal, ou sem git)"]
    if len(g["commits"]) > 5:
        L += ["", "### Todos os commits desta sessão", ""] + [f"- {c['hash']} {encurtar(c['assunto'], 140)}" for c in g["commits"]]
    L += ["", "## Memória editada nesta sessão", ""] + (_memoria_mexida(slug, s["mem_mexidas"]) or ["(nenhuma)"])
    L += ["", "## Arquivos mais mexidos", ""]
    L += [f"- {bastao._relativo(a, s['cwd'])} ({n})" for a, n in s["edicoes"].most_common(8)] or ["(nenhum)"]
    L += ["", "## Decisões recentes", ""]
    L += [f"- [{d['tipo'].upper()}] {encurtar(d['texto'], 200)}" for d in decs] or ["(nenhuma)"]
    L += ["", "---", "", bastao.montar(slug, sessao_id, cfg)]
    return mascarar("\n".join(L))


def gravar(slug, sessao_id, cfg=None, agora=None, forcar=False):
    """Grava o capítulo SÓ se a sessão é a gestora do projeto (forcar=True: transcrição que acabou de deixar de ser a gestora,
    num /clear manual). Devolve o caminho (ou None)."""
    from . import gestora_troca
    cfg = cfg if cfg is not None else config.ler_config()
    if not (forcar or eh_gestora(slug, sessao_id, cfg)) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,80}", sessao_id or ""):
        return None
    if not (indice.pasta_claude(slug) / f"{sessao_id}.jsonl").is_file():
        return None
    agora = agora or time.time()
    nome = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(agora)) + f"_{sessao_id[:8]}.md"
    destino = pasta(slug) / nome
    gestora_troca.gravar_texto(destino, montar(slug, sessao_id, cfg, agora))
    girar(slug, cfg, agora)
    return destino


def girar(slug, cfg=None, agora=None):
    """Retenção opcional (padrão: nunca apaga). Remove só capítulos com nome no padrão, pela trava config.remover."""
    cfg = cfg if cfg is not None else config.ler_config()
    dias = (cfg.get("capitulos") or {}).get("manter_dias") or 0
    if not isinstance(dias, (int, float)) or isinstance(dias, bool) or dias <= 0:
        return []
    agora = agora or time.time()
    saida = []
    for c in listar(slug):
        if agora - c["em"] > dias * 86400:
            config.remover(pasta(slug) / c["nome"])
            saida.append(c["nome"])
    return saida


def _data(nome):
    m = NOME.match(nome)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y-%m-%d_%H%M%S"))
    except ValueError:
        return None


def resumo_de(texto):
    """A parte de cima do capítulo (até o separador), sem o título."""
    topo = texto.split(FIM_RESUMO, 1)[0].strip()
    return "\n".join(topo.splitlines()[1:]).strip()


def listar(slug, limite=100):
    """Capítulos do mais novo ao mais antigo: nome, data, sessão e a primeira linha de "Onde parou"."""
    saida = []
    for f in sorted(pasta(slug).glob("*.md"), key=lambda x: x.name, reverse=True)[:limite]:
        em = _data(f.name)
        if em is None:
            continue
        try:
            texto = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        topo = resumo_de(texto).splitlines()          # 1ª linha da última mensagem (citação); capítulo antigo: 1º item
        linhas = [x[2:] for x in topo if x.startswith("> ") and x[2:].strip()] or [x[2:] for x in topo if x.startswith("- ")]
        saida.append({"nome": f.name, "em": em, "sessao": NOME.match(f.name).group(2), "resumo": encurtar(linhas[0] if linhas else "", 240)})
    return saida


def caminho(slug, nome):
    if not NOME.match(nome or ""):
        raise ValueError("nome de capítulo inválido")
    return pasta(slug) / nome


def texto_contexto(casa, slug, limite=LIMITE_CONTEXTO_CHARS):
    """additionalContext do SessionStart(compact): uma linha do GESTOR.md + resumo do último capítulo. Só lê arquivos.
    'casa' = pasta ~/.cerebro (o cerebro_hook.py chama sem servidor). '' se não houver capítulo."""
    p = Path(casa) / "projetos" / slug / "capitulos"
    try:
        arqs = sorted((f for f in p.iterdir() if NOME.match(f.name)), key=lambda x: x.name, reverse=True)
    except OSError:
        return ""
    if not arqs:
        return ""
    try:
        texto = arqs[0].read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    cab = (f"Cérebro: esta é a sessão gestora; o manual está em {Path(casa) / 'GESTOR.md'} (leia se ainda não leu). "
           f"Resumo do último capítulo ({arqs[0].name[:17].replace('_', ' ')}), gravado antes da compactação ou limpeza:\n\n")
    corpo = resumo_de(texto)
    if len(cab) + len(corpo) > limite:
        corpo = corpo[: max(0, limite - len(cab) - 3)] + "..."
    return cab + corpo
