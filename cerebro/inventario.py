"""Instalação adaptativa, etapa 1: INVENTÁRIO do que o projeto já tem e PLANO DE ENCAIXE sugerido (somente leitura).

O Cérebro nunca chega num projeto mudando o que funciona. Primeiro ele lê tudo (instruções, documentos, testes, lint,
CI, ganchos do git, agentes e configurações do Claude Code, memória, mapa) e propõe o encaixe: o que já existe e será
RESPEITADO, e o que ele acrescentaria. Este módulo só LÊ: aplicar um item (com prévia, cópia de segurança e "Desfazer")
é com o encaixe.py, e só depois do clique do dono.
"""
import json
import re
from pathlib import Path

from . import config, ferramentas, memoria

_CLI = Path(__file__).resolve().parent.parent / "cerebro_cli.py"       # onde ESTE Cérebro está instalado
_SNIPPET = """## Cérebro do Projeto (gestor)
- Todo subagente que terminar entra na fila "a conferir" do Cérebro. Antes de aceitar o trabalho dele: confira o diff, rode os testes e olhe as fotos.
- Depois de conferir, registre: `python {cli} conferir <projeto> <id-ou-descrição> --resultado aprovado|corrigido|recusado --nota "..."`
- Decisões e regras novas: `python {cli} decisao <projeto> "texto" --tipo decisao|regra|ideia --origem dono|gestor`
- Estado geral e fila: `python {cli} estado <projeto>`
"""
SNIPPET_CLAUDE_MD = _SNIPPET.replace("{cli}", str(_CLI))


def _lista(pasta, padrao, limite=30):
    try:
        return sorted(f.name for f in Path(pasta).glob(padrao) if f.is_file())[:limite]
    except OSError:
        return []


def _ler(caminho, limite=6000):
    try:
        with open(caminho, "rb") as f:
            return f.read(limite).decode("utf-8", "replace")
    except OSError:
        return ""


def _pasta_git(raiz):
    """Pasta .git real (em worktree, .git é um arquivo que aponta para ela)."""
    g = Path(raiz) / ".git"
    if g.is_dir():
        return g
    if g.is_file():
        m = re.match(r"gitdir:\s*(.+)", _ler(g, 500).strip())
        if m:
            alvo = Path(m.group(1).strip())
            if not alvo.is_absolute():
                alvo = (Path(raiz) / alvo).resolve()
            # worktree: os ganchos ficam no .git comum, dois níveis acima de worktrees/<nome>
            comum = alvo.parent.parent if alvo.parent.name == "worktrees" else alvo
            return comum if comum.is_dir() else alvo
    return None


def _ganchos_git(raiz):
    g = _pasta_git(raiz)
    nomes, graphify = [], False
    if g is not None:
        pasta = g / "hooks"
        try:
            for f in pasta.iterdir():
                if f.is_file() and not f.name.endswith(".sample"):
                    nomes.append(f.name)
                    if "graphify" in _ler(f).lower():
                        graphify = True
        except OSError:
            pass
        cfg = _ler(g / "config")
        m = re.search(r"hooksPath\s*=\s*(.+)", cfg)
        if m:
            hp = Path(m.group(1).strip())
            hp = hp if hp.is_absolute() else Path(raiz) / hp
            try:
                for f in hp.iterdir():
                    if f.is_file() and not f.name.endswith(".sample"):
                        nomes.append(f"{f.name} (hooksPath)")
                        if "graphify" in _ler(f).lower():
                            graphify = True
            except OSError:
                pass
    return sorted(set(nomes)), graphify


def _hooks_claude(raiz):
    """Nomes dos eventos de hook nos settings do Claude Code do projeto (só as chaves)."""
    eventos, arquivos = set(), []
    for nome in ("settings.json", "settings.local.json"):
        f = Path(raiz) / ".claude" / nome
        if f.is_file():
            arquivos.append(nome)
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("hooks"), dict):
                    eventos.update(str(k) for k in d["hooks"].keys())
            except (OSError, ValueError):
                pass
    return arquivos, sorted(eventos)


def _config_lint(raiz):
    raiz = Path(raiz)
    achados = []
    for nome in ("ruff.toml", ".ruff.toml", "eslint.config.mjs", "eslint.config.js", "eslint.config.cjs", ".eslintrc.json", ".eslintrc.js",
                 ".eslintrc.cjs", ".pre-commit-config.yaml", ".editorconfig", "rustfmt.toml", "clippy.toml", "mypy.ini"):
        if (raiz / nome).is_file():
            achados.append(nome)
    py = _ler(raiz / "pyproject.toml", 20000)
    if "[tool.ruff" in py:
        achados.append("pyproject.toml [tool.ruff]")
    if "[tool.pytest" in py:
        achados.append("pyproject.toml [tool.pytest]")
    return achados


def _item(id_, nome, grupo, existe, detalhe="", caminho=""):
    return {"id": id_, "nome": nome, "grupo": grupo, "existe": bool(existe), "detalhe": detalhe, "caminho": caminho}


def _plano(id_, titulo, estado, o_que, porque, texto=""):
    """estado: ja_existe (será respeitado) | acrescentar (o Cérebro propõe) | opcional."""
    return {"id": id_, "titulo": titulo, "estado": estado, "o_que": o_que, "porque": porque, "texto": texto, "aplicar": False}


def montar(slug, caminho, cfg):
    raiz = Path(caminho)
    itens, plano = [], []

    claude_md, agents_md, readme = raiz / "CLAUDE.md", raiz / "AGENTS.md", raiz / "README.md"
    for arq in (claude_md, agents_md):
        itens.append(_item("doc-" + arq.name, arq.name, "Instruções", arq.is_file(),
                           (f"{arq.stat().st_size // 1024 or 1} KB · ≈ {memoria.estimar_tokens(arq.stat().st_size)} tokens por conversa" if arq.is_file() else "não existe"),
                           str(arq)))
    itens.append(_item("doc-readme", "README.md", "Instruções", readme.is_file(), "" if readme.is_file() else "não existe", str(readme)))
    docs = _lista(raiz / "docs", "*.md", 200)
    itens.append(_item("docs", "docs/", "Instruções", bool(docs), f"{len(docs)} documento(s) .md" if docs else "não existe", str(raiz / "docs")))

    pm = memoria.pasta_memoria(slug)
    mem = _lista(pm, "*.md", 500)
    tam_idx = (pm / "MEMORY.md").stat().st_size if (pm / "MEMORY.md").is_file() else 0
    itens.append(_item("memoria", "Memória do Claude Code", "Memória", bool(mem), f"{len(mem)} arquivo(s); MEMORY.md com {tam_idx // 1024} KB" if mem else "sem pasta de memória", str(pm)))

    bat = ferramentas.baterias(caminho)
    itens.append(_item("testes", "Testes", "Qualidade", bool(bat["scripts"]) or bool(bat["como_rodar"]),
                       (f"{bat['scripts']} script(s) em {bat['pasta']}/ · rodar: {bat['como_rodar'] or '(não achei)'}" if bat["pasta"] else "nenhuma pasta de testes"),
                       str(raiz / (bat["pasta"] or "testes"))))
    lint = _config_lint(raiz)
    itens.append(_item("lint", "Lint e formatação", "Qualidade", bool(lint), ", ".join(lint) if lint else "nenhuma configuração encontrada"))
    wf = _lista(raiz / ".github" / "workflows", "*.y*ml")
    itens.append(_item("ci", "CI (GitHub Actions)", "Qualidade", bool(wf), ", ".join(wf) if wf else "sem .github/workflows", str(raiz / ".github" / "workflows")))
    dep_bot = (raiz / ".github" / "dependabot.yml").is_file() or (raiz / ".github" / "dependabot.yaml").is_file()
    itens.append(_item("dependabot", "Dependabot", "Segurança", dep_bot, "configurado" if dep_bot else "não configurado"))

    ganchos, grafo_no_gancho = _ganchos_git(raiz)
    itens.append(_item("ganchos-git", "Ganchos do git", "Automação", bool(ganchos), ", ".join(ganchos) if ganchos else "nenhum gancho ativo"))
    pre = (raiz / ".pre-commit-config.yaml").is_file() or (raiz / ".husky").is_dir()
    itens.append(_item("pre-commit", "pre-commit / husky", "Automação", pre, "encontrado" if pre else "não encontrado"))

    agentes_proj = _lista(raiz / ".claude" / "agents", "*.md")
    itens.append(_item("agentes", "Agentes do projeto (.claude/agents)", "Claude Code", bool(agentes_proj), ", ".join(agentes_proj) if agentes_proj else "nenhum",
                       str(raiz / ".claude" / "agents")))
    st_arqs, eventos = _hooks_claude(raiz)
    itens.append(_item("settings", "Configurações do Claude Code (.claude/settings*)", "Claude Code", bool(st_arqs),
                       (", ".join(st_arqs) + (" · ganchos: " + ", ".join(eventos) if eventos else " · sem ganchos")) if st_arqs else "não há"))
    habilidades = _lista(raiz / ".claude" / "skills", "*", 50) + _lista(raiz / ".claude" / "commands", "*.md", 50)
    itens.append(_item("skills", "Skills e comandos do projeto", "Claude Code", bool(habilidades), ", ".join(habilidades[:12]) if habilidades else "nenhum"))

    graph = raiz / "graphify-out" / "graph.json"
    itens.append(_item("graphify", "Mapa do Graphify (graphify-out)", "Mapa", graph.is_file(), "mapa pronto" if graph.is_file() else "sem mapa", str(graph.parent)))
    itens.append(_item("graphifyignore", ".graphifyignore", "Mapa", (raiz / ".graphifyignore").is_file(), "" if (raiz / ".graphifyignore").is_file() else "não existe"))
    gi = _ler(raiz / ".gitignore", 20000)
    cobre_env = bool(re.search(r"(?m)^\s*\.env\b", gi))
    itens.append(_item("gitignore", ".gitignore protege o .env", "Segurança", cobre_env, "sim" if cobre_env else ("sem .env no .gitignore" if gi else "sem .gitignore")))
    deps = [n for n in ("requirements.txt", "pyproject.toml", "package.json", "Cargo.toml") if (raiz / n).is_file()]
    itens.append(_item("dependencias", "Arquivos de dependências", "Segurança", bool(deps), ", ".join(deps) if deps else "nenhum"))
    dados_cerebro = (config.CASA / "projetos" / slug)
    itens.append(_item("cerebro", "Dados do Cérebro para este projeto", "Cérebro", dados_cerebro.is_dir(), str(dados_cerebro)))

    # ---------------- plano de encaixe ----------------
    det = {d["id"]: d for d in ferramentas.detectar(caminho)}
    plano.append(_plano("memoria-cerebro", "Memória persistente no Cérebro", "acrescentar",
                        "Decisões, fila 'a conferir', análises e propostas ficam em ~/.cerebro/projetos/" + slug + ". Nada é escrito no projeto.",
                        "É a base da economia de tokens: o que já foi decidido e verificado é reaproveitado, sem cortar revisão."))
    if claude_md.is_file() or agents_md.is_file():
        plano.append(_plano("instrucoes", "Instruções do gestor", "acrescentar",
                            "Manter o " + ("CLAUDE.md" if claude_md.is_file() else "AGENTS.md") + " como está e acrescentar um bloco curto (6 linhas) explicando a fila 'a conferir' e a linha de comando.",
                            "O gestor precisa saber conferir e registrar; o texto abaixo é só uma sugestão.", SNIPPET_CLAUDE_MD))
    else:
        plano.append(_plano("instrucoes", "Instruções do gestor", "acrescentar", "Criar um CLAUDE.md curto com o bloco do Cérebro e as regras básicas do projeto.",
                            "Sem instruções, cada conversa começa sem saber as regras.", SNIPPET_CLAUDE_MD))
    if graph.is_file():
        plano.append(_plano("mapa", "Mapa do código", "ja_existe", "Já existe e será respeitado: o Cérebro só LÊ o graphify-out e desenha a própria página.", "Nada muda no seu fluxo do Graphify."))
    else:
        plano.append(_plano("mapa", "Mapa do código", "acrescentar", "Rodar o Graphify uma vez neste projeto para criar o graphify-out.",
                            "Sem o mapa não há grafo, departamentos nem linha do tempo.", "graphify . (na pasta do projeto)"))
    if grafo_no_gancho:
        plano.append(_plano("mapa-auto", "Atualização automática do mapa", "ja_existe", "Há gancho do git que atualiza o Graphify; o vigia do Cérebro refaz a página quando o graph.json mudar.", "Respeitado."))
    else:
        plano.append(_plano("mapa-auto", "Atualização automática do mapa", "acrescentar",
                            "Hoje o vigia do Cérebro refaz a PÁGINA sozinho quando o graph.json muda. Para o graph.json acompanhar os commits sem você pedir, falta um gancho do git (post-commit) rodando o Graphify.",
                            "Gancho do git mexe em .git/hooks do projeto: só com a sua aprovação."))
    if lint or wf:
        plano.append(_plano("qualidade", "Lint e CI", "ja_existe", "Já existem (" + ", ".join((lint + wf)[:4]) + ") e serão respeitados; a aba Ferramentas só roda os comandos que o config permitir.", "Nada muda."))
    else:
        plano.append(_plano("qualidade", "Lint e CI", "acrescentar", "Criar configuração mínima de lint (ruff/ESLint) e um fluxo de CI.", "Pega erro antes de ir para o ar."))
    if det["gitleaks"]["instalada"]:
        plano.append(_plano("segredos", "Segurança antes do commit", "opcional", "gitleaks já está instalado; falta ligá-lo no gancho pre-commit.", "Evita subir senha ou chave.", "mexe em .git/hooks: precisa da sua aprovação"))
    else:
        plano.append(_plano("segredos", "Segurança antes do commit", "acrescentar", "Instalar o gitleaks e ligá-lo no pre-commit.", "Evita subir senha ou chave.", det["gitleaks"]["instalar"]))
    if deps:
        faltam = [det[i]["nome"] for i in ("pip-audit", "osv-scanner", "cargo-deny") if not det[i]["instalada"] and det[i]["relevante"]]
        plano.append(_plano("dependencias", "Dependências", "acrescentar" if (faltam or not dep_bot) else "ja_existe",
                            ("Faltam: " + ", ".join(faltam) + ". " if faltam else "") + ("Dependabot não configurado." if not dep_bot else "Dependabot já configurado e respeitado."),
                            "Avisa pacote com falha de segurança conhecida."))
    if agentes_proj:
        plano.append(_plano("agentes", "Agentes por tipo de tarefa", "ja_existe", f"O projeto já tem {len(agentes_proj)} agente(s) em .claude/agents e eles serão mantidos. O Cérebro só gera uma PRÉVIA dos agentes por tipo, fora do projeto.",
                            "Você compara e decide o que copiar."))
    else:
        plano.append(_plano("agentes", "Agentes por tipo de tarefa", "acrescentar", "Gerar a prévia de agentes por tipo (mecânico/Haiku, código/Sonnet, crítico/Opus) e, se você aprovar, copiar para .claude/agents.",
                            "Modelo certo para cada tarefa, sempre com revisão do gestor."))
    if eventos:
        plano.append(_plano("hooks-claude", "Eventos em tempo real (hooks do Claude Code)", "opcional", "Já há ganchos no settings (" + ", ".join(eventos) + "). Eventos em tempo real pelo Cérebro exigiriam mais um; não é necessário agora.",
                            "O Cérebro lê as conversas direto dos arquivos."))
    return {"projeto": slug, "itens": itens, "plano": plano, "snippet_claude_md": SNIPPET_CLAUDE_MD,
            "nota": "Nada foi aplicado ainda. Cada item mostra antes o que mudaria e só muda o projeto com o seu clique em Aplicar."}
