"""Comandos SUGERIDOS para um projeto (detectados só pela leitura de arquivos) e a aprovação deles.

Regra de ouro: NADA aqui executa nada. A detecção só olha nomes de arquivo e lê o package.json / pyproject.toml. Um comando
sugerido só entra na lista fechada do projeto (config.json > "comandos") quando a pessoa clica em "Aprovar" na página, e a página
manda só o id da sugestão: o comando (argv) vem SEMPRE desta detecção, feita de novo no servidor na hora da aprovação.
Depois de aprovado, rodar continua exigindo um clique em "Rodar" (ver ferramentas.rodar).
"""
import json
import re
from pathlib import Path

from . import config, ferramentas

SCRIPTS_NPM = ("test", "lint", "typecheck", "check")
CONFIG_ESLINT = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs",
                 ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml")


def _texto(p, limite=200_000):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")[:limite]
    except OSError:
        return ""


def _sugestao(id_, nome, descricao, argv, ferramenta="", timeout=600, motivo=""):
    return {"id": id_, "nome": nome, "descricao": descricao, "argv": argv, "ferramenta": ferramenta, "timeout": timeout, "motivo": motivo}


def _gerenciador_js(raiz):
    for arq, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn")):
        if (raiz / arq).is_file():
            return pm
    return "npm"


def _cargo(raiz):
    """Cargo.toml na raiz ou até dois níveis abaixo (ignora node_modules, target, .git)."""
    achados = []
    try:
        if (raiz / "Cargo.toml").is_file():
            achados.append("Cargo.toml")
        for sub in raiz.glob("*"):
            if sub.is_dir() and sub.name not in ("node_modules", "target", ".git", ".venv", "venv", "graphify-out") and (sub / "Cargo.toml").is_file():
                achados.append(f"{sub.name}/Cargo.toml")
    except OSError:
        pass
    return achados[:3]


def _testes_python(raiz):
    """(usa_pytest, pasta_de_testes_unittest ou '')."""
    pyproject = _texto(raiz / "pyproject.toml")
    usa_pytest = (raiz / "pytest.ini").is_file() or "[tool.pytest" in pyproject or (raiz / "conftest.py").is_file() \
        or "[pytest]" in _texto(raiz / "tox.ini") or "[tool:pytest]" in _texto(raiz / "setup.cfg")
    pasta = ""
    for nome in ("tests", "test", "testes"):
        p = raiz / nome
        try:
            if p.is_dir() and any(p.glob("test_*.py")):
                pasta = nome
                if not usa_pytest and any("import pytest" in _texto(f, 20000) or "from pytest" in _texto(f, 20000) for f in list(p.glob("test_*.py"))[:5]):
                    usa_pytest = True
                break
        except OSError:
            continue
    return usa_pytest, pasta


def detectar(caminho):
    """Lista de sugestões para o projeto. Só leitura; nunca executa nada."""
    raiz = Path(caminho)
    saida = []
    try:
        # ---- JavaScript: scripts do package.json (nomes fixos, nunca um script qualquer) ----
        pj = raiz / "package.json"
        if pj.is_file():
            try:
                scripts = (json.loads(_texto(pj)) or {}).get("scripts") or {}
            except (ValueError, AttributeError):
                scripts = {}
            pm = _gerenciador_js(raiz)
            for nome in SCRIPTS_NPM:
                if isinstance(scripts, dict) and isinstance(scripts.get(nome), str) and scripts[nome].strip():
                    saida.append(_sugestao(f"{pm}-{nome}", f"{pm} run {nome}", f"Roda o script \"{nome}\" do package.json: {scripts[nome].strip()[:120]}",
                                           [pm, "run", nome], "eslint" if nome == "lint" else "", 900, "package.json tem o script " + nome))
        if (raiz / "package.json").is_file() and (any((raiz / c).is_file() for c in CONFIG_ESLINT) or "eslintConfig" in _texto(raiz / "package.json")):
            if not any(s["id"].endswith("-lint") for s in saida):
                saida.append(_sugestao("eslint", "ESLint no projeto", "Verifica o JavaScript com o ESLint já instalado no projeto (sem baixar nada: npx --no-install).",
                                       ["npx", "--no-install", "eslint", "."], "eslint", 600, "achei a configuração do ESLint"))
        # ---- Python ----
        usa_pytest, pasta = _testes_python(raiz)
        if usa_pytest:
            saida.append(_sugestao("pytest", "pytest", "Roda os testes com o pytest.", ["{python}", "-m", "pytest", "-q"], "", 900, "achei a configuração ou o uso do pytest"))
        elif pasta:
            saida.append(_sugestao("unittest", "unittest", f"Roda os testes da pasta {pasta}/ com o unittest do Python.",
                                   ["{python}", "-m", "unittest", "discover", "-s", pasta], "", 900, f"achei test_*.py em {pasta}/"))
        if usa_pytest or pasta:          # cobertura: o coverage roda o MESMO executor de testes e depois mostra o relatório
            executor = ["pytest", "-q"] if usa_pytest else ["unittest", "discover", "-s", pasta]
            saida.append(_sugestao("coverage-rodar", "coverage: rodar os testes medindo",
                                   "Roda os testes com o coverage, que anota quais linhas o teste executou (grava o arquivo .coverage na pasta do "
                                   "projeto). Precisa do coverage instalado (aba Ferramentas).", ["{python}", "-m", "coverage", "run", "-m", *executor],
                                   "coverage", 1200, "o projeto tem testes em Python"))
            saida.append(_sugestao("coverage-relatorio", "coverage: relatório", "Mostra quanto de cada arquivo os testes executaram (rode antes "
                                   "'coverage: rodar os testes medindo').", ["{python}", "-m", "coverage", "report"], "coverage", 300,
                                   "o projeto tem testes em Python"))
        tem_py = any(raiz.glob("*.py")) or any(raiz.glob("*/*.py")) or (raiz / "pyproject.toml").is_file() or (raiz / "requirements.txt").is_file()
        config_ruff = (raiz / "ruff.toml").is_file() or (raiz / ".ruff.toml").is_file() or "[tool.ruff" in _texto(raiz / "pyproject.toml")
        if config_ruff or tem_py:
            saida.append(_sugestao("ruff", "ruff (verificação do Python)", "Procura erros no código Python com o ruff.", ["{python}", "-m", "ruff", "check", "."], "ruff", 600,
                                   "achei a configuração do ruff" if config_ruff else "o projeto tem arquivos Python"))
        # ---- Rust ----
        for toml in _cargo(raiz):
            sufixo = "" if toml == "Cargo.toml" else f" ({toml.split('/')[0]})"
            extra = [] if toml == "Cargo.toml" else ["--manifest-path", toml]
            saida.append(_sugestao("cargo-test" + ("" if toml == "Cargo.toml" else "-" + re.sub(r"[^a-z0-9]", "", toml.split("/")[0].lower())[:20]),
                                   "cargo test" + sufixo, "Compila e roda os testes do programa em Rust.", ["cargo", "test", *extra], "cargo", 1800, "achei " + toml))
    except OSError:
        pass
    vistos, unicas = set(), []
    for s in saida:
        if s["id"] not in vistos and re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,40}", s["id"]):
            vistos.add(s["id"])
            unicas.append(s)
    return unicas


def listar(slug, caminho, cfg=None):
    """Sugestões para a tela, com 'aprovada' = já está na lista fechada. Não devolve nada além do que a tela precisa mostrar."""
    cfg = cfg if cfg is not None else config.ler_config()
    aprovados = {c["id"] for c in ferramentas.comandos_do_projeto(cfg, slug)}
    return [{"id": s["id"], "nome": s["nome"], "descricao": s["descricao"], "comando": " ".join(s["argv"]).replace("{python}", "python"),
             "ferramenta": s["ferramenta"], "timeout": s["timeout"], "motivo": s["motivo"], "aprovada": s["id"] in aprovados} for s in detectar(caminho)]


def aprovar(slug, caminho, sugestao_id):
    """Põe a sugestão na lista fechada do projeto. O comando vem da DETECÇÃO feita agora, nunca de quem pediu."""
    achada = next((s for s in detectar(caminho) if s["id"] == sugestao_id), None)
    if achada is None:
        raise ValueError("essa sugestão não existe (ou o projeto mudou); recarregue a lista")

    def mudar(cfg):
        lista = cfg.setdefault("comandos", {}).setdefault(slug, [])
        if not any(isinstance(c, dict) and c.get("id") == achada["id"] for c in lista):
            lista.append({"id": achada["id"], "nome": achada["nome"], "descricao": achada["descricao"], "ferramenta": achada["ferramenta"],
                          "argv": list(achada["argv"]), "timeout": achada["timeout"]})

    config.atualizar_config(mudar)
    return achada


def remover(slug, comando_id):
    """Tira um comando da lista fechada do projeto (a pessoa muda de ideia)."""
    achou = {}

    def mudar(cfg):
        lista = (cfg.get("comandos") or {}).get(slug) or []
        novo = [c for c in lista if not (isinstance(c, dict) and c.get("id") == comando_id)]
        achou["ok"] = len(novo) != len(lista)
        if achou["ok"]:
            cfg["comandos"][slug] = novo

    config.atualizar_config(mudar)
    if not achou.get("ok"):
        raise ValueError("esse comando não está na lista do projeto")
