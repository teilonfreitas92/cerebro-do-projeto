"""Rotina de autoevolução: análise SOB DEMANDA (e, com o servidor aberto, a cada N dias), SEM IA.

Monta um relatório do projeto e do próprio Cérebro só com números que já existem no PC (git, mapa, ferramentas, custos,
memória, fila a conferir) e transforma os achados em PROPOSTAS (motivo, esforço P/M/G, risco). Nada é aplicado: o dono ou o
gestor aprova ou descarta cada uma (propostas.py); aprovada vira "tarefa para o gestor". O histórico das análises fica em
~/.cerebro/projetos/<slug>/analises.json. Coleta barata (sem modelo); quem decide e revisa é o gestor.
"""
import os
import re
import subprocess
import time
from pathlib import Path

from . import armazem, config, custos, ferramentas, mapa_auto, memoria, projetos, propostas, revisoes
from . import __version__

LINHAS_ARQUIVO_GRANDE = 1500        # arquivo de código com mais linhas que isto entra como proposta
CRESCEU_LINHAS = 600                # arquivo que ganhou isto em 30 dias (e já é grande) entra como proposta
CONTEXTO_FIXO_ALTO = 7000           # tokens de contexto fixo acima disto: vale enxugar
MAX_ANALISES = 30
IGNORAR_PASTAS = ("public/vendor/", "node_modules/", "target/", "graphify-out/", "data/", "data_teste/", "logs/", "bin/", "marketing/videos/saida/")
EXT_CODIGO = {".py", ".js", ".mjs", ".ts", ".rs", ".css", ".html", ".bat", ".ps1"}


def _git(raiz, *args, timeout=40):
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(raiz), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0, stdin=subprocess.DEVNULL)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _conta_linhas(caminho, limite=6_000_000):
    try:
        if os.path.getsize(caminho) > limite:
            return None
        with open(caminho, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


def _eh_analisavel(rel):
    r = rel.replace("\\", "/")
    if any(r.startswith(p) or ("/" + p) in r for p in IGNORAR_PASTAS):
        return False
    return Path(r).suffix.lower() in EXT_CODIGO


def arquivos_maiores(raiz, limite=15):
    """Os maiores arquivos de código rastreados pelo git, com número de linhas."""
    saida = _git(raiz, "ls-files", "-z")
    itens = []
    for rel in saida.split("\0"):
        if not rel or not _eh_analisavel(rel):
            continue
        try:
            tam = os.path.getsize(Path(raiz) / rel)
        except OSError:
            continue
        itens.append((tam, rel))
    itens.sort(reverse=True)
    resultado = []
    for tam, rel in itens[:limite * 2]:
        n = _conta_linhas(Path(raiz) / rel)
        resultado.append({"caminho": rel.replace("\\", "/"), "bytes": tam, "linhas": n})
    resultado.sort(key=lambda x: -(x["linhas"] or 0) if x["linhas"] is not None else 0)
    return resultado[:limite]


def arquivos_que_cresceram(raiz, dias=30, limite=10):
    """Arquivos com mais linhas acrescentadas do que removidas nos últimos 'dias' (git log --numstat)."""
    saida = _git(raiz, "log", f"--since={dias}.days", "--numstat", "--format=", timeout=60)
    saldo, add, mexidas = {}, {}, {}
    for linha in saida.splitlines():
        partes = linha.split("\t")
        if len(partes) != 3 or not partes[0].isdigit() or not partes[1].isdigit():
            continue
        a, r, rel = int(partes[0]), int(partes[1]), partes[2]
        if "=>" in rel or not _eh_analisavel(rel):
            continue
        saldo[rel] = saldo.get(rel, 0) + a - r
        add[rel] = add.get(rel, 0) + a
        mexidas[rel] = mexidas.get(rel, 0) + 1
    ordem = sorted(saldo, key=lambda k: -saldo[k])[:limite]
    return [{"caminho": k, "saldo": saldo[k], "acrescentadas": add[k], "commits": mexidas[k]} for k in ordem if saldo[k] > 0]


def mapa_resumo(slug):
    """Grupos/centros do mapa e mudanças da linha do tempo (lê o dados.js e o historico.json do Cérebro)."""
    import json
    pasta = config.CASA / "projetos" / slug / "mapa"
    r = {"disponivel": False}
    dados = pasta / "dados.js"
    if not dados.is_file():
        return r
    try:
        txt = dados.read_text(encoding="utf-8")
        D = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except (OSError, ValueError):
        return r
    nomes = D.get("nos", {}).get("n", [])
    deptos = D.get("deptos", [])
    grupos = sorted(D.get("grupos", []), key=lambda g: -g.get("t", 0))[:6]
    r.update(disponivel=True, totais=D.get("meta", {}).get("totais", {}),
             grupos=[{"nome": g.get("n"), "itens": g.get("t"), "depto": deptos[g["d"]] if 0 <= g.get("d", -1) < len(deptos) else ""} for g in grupos],
             centros=[{"nome": nomes[g["e"]] if 0 <= g.get("e", -1) < len(nomes) else "?", "ligacoes": g.get("g")} for g in D.get("gods", [])[:6]])
    hist = armazem.ler_json(pasta / "historico.json", [])
    mud = []
    for e in (hist if isinstance(hist, list) else [])[:8]:
        m = e.get("mudancas") or {}
        mud.append({"data": e.get("data"), "commit": (e.get("commit") or "")[:8], "itens": e.get("totais", {}).get("itens"),
                    "arquivos_entraram": (m.get("arquivos") or {}).get("nEntrou"), "arquivos_sairam": (m.get("arquivos") or {}).get("nSaiu"),
                    "itens_entraram": (m.get("itens") or {}).get("nEntrou"), "itens_sairam": (m.get("itens") or {}).get("nSaiu"), "inicial": bool(e.get("inicial"))})
    r["mudancas"] = mud
    return r


def custos_resumo(slug, cfg, agora=None):
    """Custo/tokens por dia e modelo, e a tendência (últimos 7 dias contra os 7 anteriores)."""
    agora = agora or time.time()
    d = custos.agregar(slug, cfg["precos"])
    por_dia = d["por_dia"]

    def soma(inicio_dias, fim_dias):
        c = t = 0.0
        sem_preco = False
        for i in range(inicio_dias, fim_dias):
            dia = custos.dia_local(agora - i * 86400)
            v = por_dia.get(dia)
            if v:
                c += v["custo"]
                t += v["entrada"] + v["saida"] + v["cache_leitura"] + v["cache_escrita"]
                sem_preco = sem_preco or bool(v["sem_preco"])
        return c, t, sem_preco

    c7, t7, sp7 = soma(0, 7)
    cant, tant, _ = soma(7, 14)
    por_modelo = []
    total_custo = sum(v["custo"] for v in d["por_modelo"].values()) or 0
    for m, v in sorted(d["por_modelo"].items(), key=lambda kv: -kv[1]["custo"]):
        por_modelo.append({"modelo": m, "custo": round(v["custo"], 2), "mensagens": v["mensagens"],
                           "parte": round(100 * v["custo"] / total_custo) if total_custo else None})
    return {"ultimos7": {"custo": round(c7, 2), "tokens": int(t7)}, "anteriores7": {"custo": round(cant, 2), "tokens": int(tant)},
            "tendencia_pct": round(100 * (c7 - cant) / cant) if cant > 0 else None, "total": round(d["total"]["custo"], 2),
            "por_modelo": por_modelo[:8], "por_dia": sorted(por_dia.items())[-14:]}


def _tamanho_pasta(p, limite_arquivos=20000):
    total = n = 0
    for raiz, _, nomes in os.walk(p):
        for nome in nomes:
            try:
                total += os.path.getsize(os.path.join(raiz, nome))
            except OSError:
                pass
            n += 1
            if n > limite_arquivos:
                return total
    return total


# ---------------------------------------------------------------------------------------------------------------
# Análise de um projeto
# ---------------------------------------------------------------------------------------------------------------
def analisar_projeto(p, cfg, agora=None):
    """p = projeto (slug, nome, caminho). Devolve (relatorio, propostas)."""
    agora = agora or time.time()
    slug, raiz = p["slug"], p["caminho"]
    avisos, props = [], []
    rel = {"projeto": slug, "nome": p["nome"], "quando": agora}

    def tentar(nome, fn, padrao=None):
        try:
            return fn()
        except Exception as e:                       # uma parte quebrada não pode impedir o resto da análise
            avisos.append(f"{nome}: {type(e).__name__}: {str(e)[:120]}")
            return padrao

    rel["git"] = {"info": tentar("git", lambda: projetos.info_git(raiz), {})}
    rel["maiores"] = tentar("arquivos maiores", lambda: arquivos_maiores(raiz), []) or []
    rel["cresceram"] = tentar("crescimento", lambda: arquivos_que_cresceram(raiz), []) or []
    n30 = tentar("commits", lambda: (_git(raiz, "rev-list", "--count", "--since=30.days", "HEAD") or "0").strip(), "0")
    rel["git"]["commits_30d"] = int(n30) if str(n30).isdigit() else None
    rel["mapa"] = tentar("mapa", lambda: mapa_resumo(slug), {"disponivel": False})
    rel["mapa_estado"] = tentar("estado do mapa", lambda: {**projetos.estado_mapa(raiz, slug), "vigia": mapa_auto.estado(slug)}, {})
    rel["memoria"] = tentar("memória", lambda: memoria.listar(slug, raiz), {"contexto_fixo": {"total_tokens": 0, "arquivos": []}, "avisos": []})
    rel["contexto_fixo"] = rel["memoria"]["contexto_fixo"]
    rel["avisos_memoria"] = rel["memoria"]["avisos"]
    rel["memoria"] = {"itens": len(rel["memoria"].get("itens", []))}
    rel["custos"] = tentar("custos", lambda: custos_resumo(slug, cfg, agora), None)
    rel["revisoes"] = tentar("revisões", lambda: revisoes.fila(slug, cfg, agora), None)
    if rel["revisoes"]:
        r = rel["revisoes"]
        rel["revisoes"] = {"contadores": r["contadores"], "por_modelo": r["por_modelo"], "antigos": r["antigos"], "gestora": r["gestora"]}
    ferr = tentar("ferramentas", lambda: ferramentas.montar(slug, raiz, cfg), None)
    if ferr:
        rel["ferramentas"] = {"instaladas": [c["nome"] for c in ferr["cartoes"] if c["instalada"]],
                              "faltam": [c["nome"] for c in ferr["cartoes"] if not c["instalada"] and c["relevante"]],
                              "execucoes": [{"nome": x["nome"], "resultado": x["resultado"], "resumo": x["resumo"], "inicio": x["inicio"]} for x in ferr["historico"][:6]],
                              "baterias": ferr["baterias"]}

    # ------------------------- propostas -------------------------
    P = propostas.proposta
    grandes = [m for m in rel["maiores"] if m["linhas"] and m["linhas"] > LINHAS_ARQUIVO_GRANDE and Path(m["caminho"]).suffix.lower() in EXT_CODIGO]
    if grandes:
        lista = ", ".join(f"{g['caminho']} ({g['linhas']} linhas)" for g in grandes[:4])
        props.append(P("projeto", "arquivos-grandes", f"{len(grandes)} arquivo(s) de código com mais de {LINHAS_ARQUIVO_GRANDE} linhas",
                       f"Arquivo grande é difícil de ler e de testar, e custa tokens toda vez que um agente o abre. Maiores: {lista}. Dividir por responsabilidade, "
                       "com testes antes e depois.", "G", "médio", "código"))
    for c in rel["cresceram"][:3]:
        linhas = next((m["linhas"] for m in rel["maiores"] if m["caminho"] == c["caminho"]), None)
        if c["saldo"] >= CRESCEU_LINHAS and (linhas or 0) >= 800:
            props.append(P("projeto", "cresceu|" + c["caminho"], f"{c['caminho']} cresce rápido (+{c['saldo']} linhas em 30 dias)",
                           f"Ganhou {c['acrescentadas']} linhas em {c['commits']} commits e já tem {linhas} linhas. Melhor dividir antes que vire o próximo arquivo gigante.",
                           "M", "médio", "código"))
    cf = rel["contexto_fixo"]
    if cf.get("total_tokens", 0) > CONTEXTO_FIXO_ALTO or rel["avisos_memoria"]:
        props.append(P("projeto", "contexto-fixo", f"Enxugar o contexto fixo (≈ {cf.get('total_tokens', 0)} tokens por conversa)",
                       (" ".join(rel["avisos_memoria"]) + " " if rel["avisos_memoria"] else "")
                       + "Cada conversa nova paga o MEMORY.md, o CLAUDE.md e o AGENTS.md inteiros. Passar detalhes para documentos que só são lidos quando preciso economiza em todas as conversas.",
                       "M", "baixo", "memória"))
    cu = rel["custos"]
    if cu:
        if cu["tendencia_pct"] is not None and cu["tendencia_pct"] > 50 and cu["ultimos7"]["custo"] > 10:
            props.append(P("projeto", "custo-subindo", f"Custo subiu {cu['tendencia_pct']}% na semana (US$ {cu['ultimos7']['custo']} contra US$ {cu['anteriores7']['custo']})",
                           "Ver na aba Custos quais sessões e subagentes mais gastaram e se algum trabalho mecânico pode ir para um modelo menor (sempre com a conferência do gestor).",
                           "P", "baixo", "custos"))
        opus = sum(m["custo"] for m in cu["por_modelo"] if "opus" in m["modelo"] or "fable" in m["modelo"])
        todo = sum(m["custo"] for m in cu["por_modelo"])
        if todo > 20 and opus / todo > 0.8:
            props.append(P("projeto", "muito-opus", f"{round(100 * opus / todo)}% do custo é do modelo maior",
                           "Tarefas mecânicas (buscas, textos, documentação) podem ir para Haiku e código comum para Sonnet, mantendo o Opus para arquitetura, segurança e revisão. "
                           "A aba Configurações tem a tabela de agentes por tipo de tarefa.", "M", "baixo", "custos"))
    rv = rel["revisoes"]
    if rv:
        if rv["contadores"]["parados"]:
            props.append(P("projeto", "conferir-parados", f"{rv['contadores']['parados']} subagente(s) esperando conferência há mais de 24 h",
                           "Trabalho de subagente só entra no projeto depois que o gestor confere (diff, testes, fotos). Conferir e marcar o resultado na aba A conferir.",
                           "P", "baixo", "revisão"))
        for m in rv["por_modelo"]:
            if m["total"] >= 5 and m["pct_primeira"] is not None and m["pct_primeira"] < 60:
                props.append(P("projeto", "baixa-aprovacao|" + m["modelo"], f"Só {m['pct_primeira']}% do trabalho do {m['modelo']} é aprovado de primeira",
                               f"{m['aprovado']} aprovados, {m['corrigido']} corrigidos e {m['recusado']} recusados em {m['total']} conferidos. Melhorar o briefing "
                               "(objetivo, arquivos, critérios, checks) ou subir o modelo para esse tipo de tarefa.", "M", "baixo", "agentes"))
        if not rv["gestora"]:
            props.append(P("projeto", "sem-gestora", "Escolher a sessão gestora deste projeto",
                           "Sem gestora, a fila 'a conferir' fica vazia e os agentes não aparecem como 'delegados pelo gestor'.", "P", "baixo", "configuração"))
    if ferr:
        faltam = [c for c in ferr["cartoes"] if not c["instalada"] and c["relevante"]]
        ordem = ["gitleaks", "pip-audit", "osv-scanner", "coverage", "cargo-deny", "semgrep", "lighthouse"]
        faltam.sort(key=lambda c: ordem.index(c["id"]) if c["id"] in ordem else 99)
        for c in faltam[:4]:
            props.append(P("projeto", "instalar|" + c["id"], f"Instalar {c['nome']}", f"{c['o_que']} Instalar: {c['instalar']}. Precisa da sua aprovação.", "P",
                           "baixo", "ferramentas"))
        for x in ferr["historico"][:6]:
            if x["resultado"] in ("falha", "tempo", "erro"):
                props.append(P("projeto", "falhou|" + x["comando"], f"Última execução de '{x['nome']}' terminou com {x['resultado']}",
                               f"{x['resumo']}. Abrir a saída na aba Ferramentas e corrigir antes do próximo commit.", "M", "médio", "qualidade"))
                break
        gi = ferr["graphify"]
        if gi.get("mapa") and gi.get("graph_em") and gi.get("pagina_em") and gi["graph_em"] > gi["pagina_em"] + 600:
            props.append(P("projeto", "pagina-mapa-velha", "A página do mapa está mais velha que o mapa do Graphify",
                           "O vigia do Cérebro deveria ter refeito a página sozinho. Conferir o erro na aba Mapa.", "P", "baixo", "mapa"))
    ms = rel["mapa_estado"]
    if ms.get("defasado"):
        props.append(P("projeto", "mapa-defasado", "O mapa do Graphify está mais velho que o último commit",
                       "Os ganchos do git do projeto não refizeram o graph.json. Conferir os ganchos (post-commit) ou rodar o Graphify à mão.", "P", "baixo", "mapa"))
    if ms.get("vigia", {}).get("ultimo_erro"):
        props.append(P("projeto", "mapa-erro", "O gerador da página do mapa está falhando",
                       "Último erro: " + ms["vigia"]["ultimo_erro"][-200:], "M", "baixo", "mapa"))
    rel["avisos"] = avisos
    return rel, props


# ---------------------------------------------------------------------------------------------------------------
# Análise do próprio Cérebro
# ---------------------------------------------------------------------------------------------------------------
def analisar_cerebro(cfg, agora=None):
    agora = agora or time.time()
    raiz = Path(__file__).resolve().parent.parent
    rel = {"projeto": propostas.ESCOPO_CEREBRO, "nome": "Cérebro do Projeto", "quando": agora, "versao": __version__}
    props, avisos = [], []
    P = propostas.proposta
    arquivos = []
    for f in list(raiz.glob("cerebro/*.py")) + list(raiz.glob("web/*.js")) + list(raiz.glob("mapa/*.py")) + list(raiz.glob("mapa/*.js")):
        n = _conta_linhas(f)
        if n:
            arquivos.append({"caminho": str(f.relative_to(raiz)).replace("\\", "/"), "linhas": n, "bytes": f.stat().st_size})
    arquivos.sort(key=lambda x: -x["linhas"])
    rel["maiores"] = arquivos[:10]
    grandes = [a for a in arquivos if a["linhas"] > 1200]
    if grandes:
        props.append(P("cerebro", "cerebro-arquivos-grandes", f"{len(grandes)} arquivo(s) do Cérebro com mais de 1200 linhas",
                       "Maiores: " + ", ".join(f"{g['caminho']} ({g['linhas']})" for g in grandes[:4]) + ". Dividir antes que fiquem difíceis de manter.", "M", "baixo", "cérebro"))
    rel["testes"] = len(list((raiz / "testes").glob("test_*.py")))
    casa = config.CASA
    tam = _tamanho_pasta(casa) if casa.is_dir() else 0
    rel["dados_bytes"] = tam
    if tam > 600 * 1024 * 1024:
        props.append(P("cerebro", "dados-grandes", f"A pasta de dados do Cérebro tem {tam // (1024 * 1024)} MB",
                       "Índices e saídas de ferramentas crescem com o tempo. Conferir o que pode ser apagado (índices se refazem sozinhos).", "P", "baixo", "cérebro"))
    nov = armazem.ler_json(casa / "novidades.json", {})
    ult = (nov or {}).get("ultima_busca")
    rel["novidades_ultima_busca"] = ult
    dias_nov = int((cfg.get("rotinas") or {}).get("vigia_novidades_dias") or 3)
    if not ult or agora - ult > max(14, dias_nov * 3) * 86400:
        props.append(P("cerebro", "rodar-novidades", "Procurar novidades de ferramentas e do Claude Code",
                       "A última busca foi " + ("nunca" if not ult else f"há {int((agora - ult) // 86400)} dias") + ". O botão 'Procurar novidades' consulta só páginas públicas de releases.", "P", "baixo", "novidades"))
    r = cfg.get("rotinas") or {}
    if not r.get("agendamento_ativo"):
        props.append(P("cerebro", "agendamento-windows", "Rodar o Cérebro sozinho no Windows (agendamento)",
                       "Hoje a análise e o vigia do mapa só rodam com o servidor aberto. Para rodar sem ninguém abrir a página seria preciso uma tarefa agendada ou atalho de inicialização: "
                       "mexe no Windows e precisa da sua aprovação.", "M", "médio", "automação"))
    fonte = str(cfg.get("fonte_precos") or "")
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", fonte)
    if m:
        import datetime
        try:
            data = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            idade = (datetime.date.fromtimestamp(agora) - data).days
            rel["precos_idade_dias"] = idade
            if idade > 60:
                props.append(P("cerebro", "precos-velhos", f"A tabela de preços tem {idade} dias",
                               "Conferir os preços de lista atuais dos modelos em Configurações; o custo mostrado é estimativa pela tabela.", "P", "baixo", "custos"))
        except ValueError:
            pass
    rel["avisos"] = avisos
    return rel, props


# ---------------------------------------------------------------------------------------------------------------
# Execução + histórico
# ---------------------------------------------------------------------------------------------------------------
def _arq_historico(slug):
    return config.pasta_projeto(slug) / "analises.json"


def executar(slug, cfg, agora=None):
    """Roda a análise do projeto (ou do Cérebro, slug '_cerebro'), sincroniza as propostas e guarda no histórico."""
    t0 = time.time()
    agora = agora or t0
    if slug == propostas.ESCOPO_CEREBRO:
        rel, props = analisar_cerebro(cfg, agora)
    else:
        p = projetos.achar(slug)
        if p is None:
            raise ValueError("projeto não encontrado")
        rel, props = analisar_projeto(p, cfg, agora)
    novas = propostas.sincronizar(slug, props, agora)
    rel["duracao"] = round(time.time() - t0, 1)
    resumo = {"id": f"a{int(agora)}", "em": agora, "duracao": rel["duracao"], "propostas": len(props), "novas": len(novas),
              "titulos": [p["titulo"] for p in props][:12]}

    def mudar(d):
        d["itens"].insert(0, resumo)
        d["itens"] = d["itens"][:MAX_ANALISES]
        d["ultima"] = rel
        return d

    armazem.atualizar_json(_arq_historico(slug), {"v": 1, "itens": [], "ultima": None}, mudar)
    return {"relatorio": rel, "resumo": resumo, "propostas": propostas.listar(slug)}


def ler(slug, cfg):
    d = armazem.ler_json(_arq_historico(slug), {"v": 1, "itens": [], "ultima": None})
    intervalo = int((cfg.get("rotinas") or {}).get("autoevolucao_dias") or 7)
    ultima_em = d["itens"][0]["em"] if d.get("itens") else None
    return {"relatorio": d.get("ultima"), "historico": d.get("itens", []), "propostas": propostas.listar(slug), "tarefas": propostas.tarefas(slug),
            "intervalo_dias": intervalo, "ultima_em": ultima_em, "proxima_em": (ultima_em + intervalo * 86400) if ultima_em else None,
            "automatica": bool((cfg.get("rotinas") or {}).get("analise_automatica", True))}
