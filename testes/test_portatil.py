"""Cérebro instalável por qualquer pessoa: nada do dono no código, comandos só por aprovação, instalar/desinstalar, primeiro uso guiado,
migração do config de quem já usava, demonstração com dados fictícios."""
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import config, ferramentas, mapa_auto, sugestoes
from testes.test_servidor import Base

RAIZ = amb.RAIZ
sys.path.insert(0, str(RAIZ))
import desinstalar  # noqa: E402
import instalar  # noqa: E402


class FalsoResultado:
    returncode = 0
    stdout = ""
    stderr = ""


class Gravador:
    """Faz de conta de subprocess.run: guarda o que seria executado e diz que deu certo."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, argv, **kw):
        self.chamadas.append((list(argv), kw))
        return FalsoResultado()


# ======================================================================================================================
# 1. Nada de ninguém no repositório
# ======================================================================================================================
def _proibidos():
    pedacos = [("T" + "NF", True), ("teil" + "on", False), ("T_" + "(ROOM|TECH|BRAIN|GAME|FOREX|GOLD)", True), ("3e25" + "2248", True),
               ("CEREBRO_" + "DO_PROJETO", True)]
    return [re.compile(rf"\b{p}\b" if p.startswith("T" + "NF") else p, 0 if sens else re.I) for p, sens in pedacos]


IGNORAR_PASTAS = {".git", ".venv", "__pycache__", "node_modules", "saida", "imagens", ".cerebro-testes", ".ruff_cache", ".claude"}   # .claude: worktrees dos agentes (fora do git)
IGNORAR_ARQUIVOS = {"LICENSE", "NOTICE"}       # a licença e o aviso levam o nome de quem escolheu a MIT
BINARIOS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".lnk", ".pyc", ".woff", ".woff2"}
USUARIOS_OK = {"ana", "usuario", "você", "seu-usuario", "seuusuario", "nome", "exemplo", "public"}
EMAIL = re.compile(r"(?<![:\w.+%\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z]{2,}")
EMAIL_OK = ("example.com", "example.org", "noreply.github.com", "anthropic.com")


def arquivos_do_repositorio():
    for p in RAIZ.rglob("*"):
        if not p.is_file() or p.suffix.lower() in BINARIOS or p.name in IGNORAR_ARQUIVOS:
            continue
        if any(parte in IGNORAR_PASTAS for parte in p.relative_to(RAIZ).parts):
            continue
        yield p


class TesteNadaDoDono(unittest.TestCase):
    def test_nenhum_arquivo_traz_nome_caminho_ou_projeto_de_ninguem(self):
        achados = []
        proibidos = _proibidos()
        for p in arquivos_do_repositorio():
            try:
                texto = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = p.relative_to(RAIZ).as_posix()
            for rx in proibidos:
                for m in rx.finditer(texto):
                    achados.append(f"{rel}: {m.group(0)!r}")
            for m in re.finditer(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"']+)", texto):
                if m.group(1).lower() not in USUARIOS_OK and not m.group(1).startswith(("{", "<", "%", "$")):
                    achados.append(f"{rel}: caminho de usuário {m.group(0)!r}")
            for m in EMAIL.finditer(texto):
                if not m.group(0).lower().endswith(EMAIL_OK) and not m.group(0).startswith("@"):
                    achados.append(f"{rel}: e-mail {m.group(0)!r}")
        self.assertEqual(achados, [], "dado pessoal no repositório:\n" + "\n".join(achados[:30]))

    def test_nenhum_padrao_vem_pronto_no_codigo(self):
        self.assertEqual(config.CONFIG_PADRAO["gestoras"], {})
        self.assertEqual(config.CONFIG_PADRAO["comandos"], {})
        self.assertEqual(config.CONFIG_PADRAO["departamentos"], {})
        self.assertEqual(config.CONFIG_PADRAO["projetos_extra"], [])
        self.assertEqual(config.PORTAS_SEMPRE_PROIBIDAS, {80, 443})
        self.assertFalse(hasattr(config, "SLUG_" + "T_" + "ROOM"))

    def test_arquivo_de_status_so_vem_da_configuracao_da_pessoa(self):
        from cerebro import painel
        nomes = [str(c) for c in painel._candidatos_status()]
        self.assertTrue(all("T_" not in n for n in nomes), nomes)


# ======================================================================================================================
# 2. Departamentos genéricos
# ======================================================================================================================
class TesteDepartamentosGenericos(unittest.TestCase):
    def test_sem_configuracao_uma_cor_por_pasta_de_topo(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("deptos_t", RAIZ / "mapa" / "deptos.py")
        d = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(d)
        e = d.esquema_pastas(["src/a.py", "src/b.py", "docs/x.md", "README.md", "tests/t.py"])
        self.assertEqual(set(e.nomes), {"src", "docs", "Raiz", "tests"})
        self.assertEqual(len(set(e.cores)), len(e.cores))                  # cores automáticas, todas diferentes

    def test_regras_com_regex_e_ancora_de_quem_ja_usava(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("deptos_t2", RAIZ / "mapa" / "deptos.py")
        d = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(d)
        conf = {"modo": "regras", "padrao": "Servidor", "deptos": [
            {"nome": "Testes", "cor": "#8f9bb0", "ancora": [-110, -20], "caminhos": ["testes/"]},
            {"nome": "Mascote", "cor": "#ff5fd2", "ancora": [-900, 250], "caminhos": ["re:^programa/(.*/)?[^/]*(octo|mascote)[^/]*$"]},
            {"nome": "Programa", "cor": "#8c8cff", "caminhos": ["programa/"]}, {"nome": "Servidor", "cor": "#ff4f6d", "caminhos": ["re:^(?![^/]*\\.py$)[^/]+$"]}]}
        e = d.esquema_regras(conf)
        nome = lambda f: e.nomes[e.indice(f)]            # noqa: E731
        self.assertEqual(nome("testes/a.py"), "Testes")
        self.assertEqual(nome("programa/src/octo_mascote.rs"), "Mascote")
        self.assertEqual(nome("programa/src/main.rs"), "Programa")
        self.assertEqual(nome("Cargo.toml"), "Servidor")
        self.assertEqual(e.ancoras[0], [-110.0, -20.0])
        self.assertIsNone(e.ancoras[2])
        with self.assertRaises(ValueError):
            d.validar({"modo": "regras", "deptos": [{"nome": "A", "caminhos": ["re:("]}]})
        with self.assertRaises(ValueError):
            d.validar({"modo": "regras", "deptos": [{"nome": "A", "caminhos": [], "ancora": [1, "x"]}]})
        with self.assertRaises(ValueError):
            d.validar({"modo": "outro"})


# ======================================================================================================================
# 3. Migração do config de quem já usava (o dono) e de configs antigas
# ======================================================================================================================
class TesteMigracaoDeQuemJaUsava(unittest.TestCase):
    def setUp(self):
        amb.apagar(config.CASA / "config.json")
        config.garantir_casa()
        self.addCleanup(amb.apagar, config.CASA / "config.json")

    def test_config_da_v1_1_mantem_gestora_comandos_e_departamentos_de_regras(self):
        slug = amb.SLUG_EXEMPLO
        antigo = {"versao": 3, "tema": "claro", "gestoras": {slug: {"conversa": "11111111-2222-3333-4444-555555555555", "nome": "Gestora principal"}},
                  "comandos": {slug: [{"id": "lint", "nome": "Lint", "argv": ["{python}", "testes/lint.py"], "timeout": 600, "ferramenta": "ruff"}]},
                  "departamentos": {slug: {"modo": "regras", "padrao": "Servidor", "deptos": [{"nome": "Servidor", "cor": "#ff4f6d", "caminhos": ["server.py"]}]},
                                    "outro": {"modo": "t_antigo"}},
                  "projetos_extra": ["C:/Projetos/Extra"], "ocultos": ["abc"], "nunca_entrar": ["financeiro"], "portas_reservadas": [8090]}
        (config.CASA / "config.json").write_text(json.dumps(antigo), encoding="utf-8")
        cfg = config.ler_config()
        self.assertEqual(cfg["versao"], config.CONFIG_PADRAO["versao"])
        self.assertEqual(cfg["tema"], "claro")
        self.assertEqual(cfg["gestoras"][slug]["nome"], "Gestora principal")
        self.assertEqual([c["id"] for c in cfg["comandos"][slug]], ["lint"])
        self.assertEqual(cfg["departamentos"][slug]["modo"], "regras")
        self.assertNotIn("outro", cfg["departamentos"])                   # modo antigo que não existe mais: volta ao automático
        self.assertEqual((cfg["projetos_extra"], cfg["ocultos"], cfg["nunca_entrar"], cfg["portas_reservadas"]), (["C:/Projetos/Extra"], ["abc"], ["financeiro"], [8090]))
        self.assertIn(8090, config.portas_proibidas(cfg))
        gravado = json.loads((config.CASA / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(gravado["versao"], config.CONFIG_PADRAO["versao"])

    def test_comando_do_dono_continua_na_lista_fechada_e_exige_clique(self):
        slug = amb.SLUG_EXEMPLO
        cfg = {"comandos": {slug: [{"id": "lint", "nome": "Lint", "argv": ["{python}", "testes/lint.py"], "timeout": 600}]}}
        self.assertEqual([c["id"] for c in ferramentas.comandos_do_projeto(cfg, slug)], ["lint"])


# ======================================================================================================================
# 4. Comandos sugeridos: só sugestão; nada roda sem aprovação
# ======================================================================================================================
class TesteSugestoes(unittest.TestCase):
    def setUp(self):
        self.pasta = amb.BASE / "sug_proj"
        amb.apagar(self.pasta)
        self.pasta.mkdir(parents=True)
        self.slug = "slug-sugestoes"
        config.atualizar_config(lambda c: c["comandos"].pop(self.slug, None))

    def ids(self, caminho=None):
        return {s["id"]: s for s in sugestoes.detectar(caminho or self.pasta)}

    def test_projeto_vazio_nao_sugere_nada(self):
        self.assertEqual(sugestoes.detectar(self.pasta), [])

    def test_package_json_so_sugere_scripts_conhecidos(self):
        (self.pasta / "package.json").write_text(json.dumps({"scripts": {"test": "node --test", "lint": "eslint .", "deploy": "rm -rf /", "postinstall": "evil"}}), encoding="utf-8")
        ids = self.ids()
        self.assertEqual(set(ids), {"npm-test", "npm-lint"})                # deploy/postinstall nunca viram sugestão
        self.assertEqual(ids["npm-test"]["argv"], ["npm", "run", "test"])
        (self.pasta / "pnpm-lock.yaml").write_text("", encoding="utf-8")
        self.assertIn("pnpm-test", self.ids())

    def test_python_cargo_ruff_e_eslint(self):
        (self.pasta / "tests").mkdir()
        (self.pasta / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
        (self.pasta / "ruff.toml").write_text("", encoding="utf-8")
        (self.pasta / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
        (self.pasta / "package.json").write_text("{}", encoding="utf-8")
        (self.pasta / "eslint.config.js").write_text("export default [];\n", encoding="utf-8")
        ids = self.ids()
        self.assertEqual(ids["unittest"]["argv"], ["{python}", "-m", "unittest", "discover", "-s", "tests"])
        self.assertEqual(ids["ruff"]["argv"], ["{python}", "-m", "ruff", "check", "."])
        self.assertEqual(ids["cargo-test"]["argv"], ["cargo", "test"])
        self.assertEqual(ids["eslint"]["argv"], ["npx", "--no-install", "eslint", "."])           # nunca baixa nada

    def test_pytest_quando_ha_configuracao(self):
        (self.pasta / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (self.pasta / "tests").mkdir()
        (self.pasta / "tests" / "test_a.py").write_text("", encoding="utf-8")
        self.assertIn("pytest", self.ids())
        self.assertNotIn("unittest", self.ids())

    def test_detectar_e_listar_nao_executam_nada(self):
        (self.pasta / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}), encoding="utf-8")
        (self.pasta / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
        chamadas = []
        antes = (subprocess.Popen, subprocess.run)
        subprocess.Popen = lambda *a, **k: chamadas.append(a)
        subprocess.run = lambda *a, **k: chamadas.append(a)
        try:
            sugestoes.detectar(self.pasta)
            sugestoes.listar(self.slug, self.pasta)
        finally:
            subprocess.Popen, subprocess.run = antes
        self.assertEqual(chamadas, [])

    def test_aprovar_poe_na_lista_fechada_com_o_argv_da_deteccao(self):
        (self.pasta / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8")
        self.assertEqual(ferramentas.comandos_do_projeto(config.ler_config(), self.slug), [])         # antes: nada na lista
        sugestoes.aprovar(self.slug, self.pasta, "npm-test")
        sugestoes.aprovar(self.slug, self.pasta, "npm-test")                                           # idempotente
        lista = ferramentas.comandos_do_projeto(config.ler_config(), self.slug)
        self.assertEqual([(c["id"], c["argv"]) for c in lista], [("npm-test", ["npm", "run", "test"])])
        self.assertTrue(next(s for s in sugestoes.listar(self.slug, self.pasta) if s["id"] == "npm-test")["aprovada"])
        with self.assertRaises(ValueError):
            sugestoes.aprovar(self.slug, self.pasta, "nao-existe")
        sugestoes.remover(self.slug, "npm-test")
        self.assertEqual(ferramentas.comandos_do_projeto(config.ler_config(), self.slug), [])
        with self.assertRaises(ValueError):
            sugestoes.remover(self.slug, "npm-test")

    def test_sugestao_nao_aprovada_nao_roda(self):
        (self.pasta / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            ferramentas.rodar(self.slug, str(self.pasta), config.ler_config(), "npm-test")

    def test_so_roda_depois_de_aprovar_e_do_clique(self):
        (self.pasta / "tests").mkdir()
        (self.pasta / "tests" / "test_a.py").write_text("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n", encoding="utf-8")
        sugestoes.aprovar(self.slug, self.pasta, "unittest")
        chamadas = []
        original = ferramentas.subprocess.Popen
        ferramentas.subprocess.Popen = lambda *a, **k: (chamadas.append(a), original(*a, **k))[1]
        self.addCleanup(setattr, ferramentas.subprocess, "Popen", original)
        roda_testes = lambda: [c for c in chamadas if "unittest" in " ".join(map(str, c[0]))]            # noqa: E731
        ferramentas.montar(self.slug, str(self.pasta), config.ler_config())                            # abrir a aba não roda comando nenhum
        self.assertEqual(roda_testes(), [])
        ferramentas.rodar(self.slug, str(self.pasta), config.ler_config(), "unittest")                 # o clique em "Rodar"
        fim = time.time() + 30
        while time.time() < fim and ferramentas.estado_execucoes(self.slug)["rodando"] is not None:
            time.sleep(0.1)
        self.assertEqual(len(roda_testes()), 1)
        self.assertEqual(ferramentas.estado_execucoes(self.slug)["historico"][0]["resultado"], "ok")

    def test_primeiro_item_e_procurado_no_path_sem_shell(self):
        original = ferramentas.shutil.which
        ferramentas.shutil.which = lambda nome, *a, **k: None
        self.addCleanup(setattr, ferramentas.shutil, "which", original)
        with self.assertRaises(ValueError):
            ferramentas._resolver_argv(["programa-que-nao-existe", "x"], self.pasta)
        ferramentas.shutil.which = lambda nome, *a, **k: "C:/bin/npm.cmd" if nome == "npm" else None
        self.assertEqual(ferramentas._resolver_argv(["npm", "run", "test"], self.pasta)[0], "C:/bin/npm.cmd")


class TesteRotasSugestoes(Base):
    async def test_aprovar_so_pelo_id_e_o_argv_vem_do_servidor(self):
        (self.real / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8")
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/comandos/sugeridos")).json()
        self.assertEqual([s["id"] for s in d["sugestoes"]], ["npm-test"])
        self.assertNotIn("argv", d["sugestoes"][0])                         # a página recebe só o texto do comando
        # tentar empurrar um comando próprio na aprovação: o corpo extra é ignorado e o id desconhecido é recusado
        r = await self.post(f"/api/p/{self.slug}/comandos/aprovar", {"id": "calc", "argv": ["calc.exe"]})
        self.assertEqual(r.status, 404)
        r = await self.post(f"/api/p/{self.slug}/comandos/aprovar", {"id": "npm-test", "argv": ["calc.exe"]})
        self.assertEqual(r.status, 200)
        cmds = config.ler_config()["comandos"][self.slug]
        self.assertEqual([c["argv"] for c in cmds], [["npm", "run", "test"]])
        r = await self.post(f"/api/p/{self.slug}/comandos/aprovar", {"id": "npm-test"}, origem=False)
        self.assertEqual(r.status, 403)
        r = await self.post(f"/api/p/{self.slug}/comandos/remover", {"id": "npm-test"})
        self.assertEqual(r.status, 200)
        self.assertEqual(config.ler_config()["comandos"][self.slug], [])

    async def test_rodar_sugestao_nao_aprovada_da_409(self):
        (self.real / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}), encoding="utf-8")
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/ferramentas/rodar", {"id": "npm-test"})
        self.assertEqual(r.status, 409)

    async def test_ferramentas_traz_as_sugestoes(self):
        (self.real / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8")
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas")).json()
        self.assertIn("npm-lint", [s["id"] for s in d["sugestoes"]])
        self.assertEqual(d["comandos"], [])


# ======================================================================================================================
# 5. Primeiro uso guiado
# ======================================================================================================================
class TesteBemVindo(Base):
    async def test_flag_do_primeiro_uso_e_pagina_do_guia(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/projetos")).json()
        self.assertFalse(d["primeiro_uso_concluido"])
        self.assertEqual((await self.post("/api/config", {"primeiro_uso_concluido": "sim"})).status, 400)
        self.assertEqual((await self.post("/api/config", {"primeiro_uso_concluido": True})).status, 200)
        d = await (await self.http.get(f"{self.base}/api/projetos")).json()
        self.assertTrue(d["primeiro_uso_concluido"])
        js = await self.http.get(f"{self.base}/static/bemvindo.js")
        self.assertEqual(js.status, 200)
        self.assertIn("graphify update .", await js.text())

    async def test_gerar_mapa_sem_graphify_explica_como_instalar(self):
        await self.entrar()
        original = ferramentas.exe_graphify
        ferramentas.exe_graphify = lambda: None
        self.addCleanup(setattr, ferramentas, "exe_graphify", original)
        r = await self.post(f"/api/p/{self.slug}/mapa/criar", {})
        self.assertEqual(r.status, 409)
        self.assertIn("uv tool install graphifyy", (await r.json())["erro"])

    async def test_gerar_mapa_so_com_clique_cria_graphify_out_no_projeto_e_sugere_gitignore(self):
        await self.entrar()
        self.assertFalse((self.real / "graphify-out").exists())                # nada é criado antes do clique
        original = ferramentas.exe_graphify
        ferramentas.exe_graphify = lambda: "graphify-falso"
        self.addCleanup(setattr, ferramentas, "exe_graphify", original)
        antes = mapa_auto.criar_mapa

        def criar(slug, caminho, exe, timeout=600, rodar=None):
            def falso(c):
                (Path(c) / "graphify-out").mkdir(exist_ok=True)
                (Path(c) / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
            return antes(slug, caminho, exe, timeout, rodar=falso)
        mapa_auto.criar_mapa = criar
        gerar_original = mapa_auto.gerar
        mapa_auto.gerar = lambda caminho, timeout=300: (True, "ok")
        self.addCleanup(lambda: (setattr(mapa_auto, "criar_mapa", antes), setattr(mapa_auto, "gerar", gerar_original)))
        r = await self.post(f"/api/p/{self.slug}/mapa/criar", {})
        corpo = await r.json()
        self.assertEqual(r.status, 200, corpo)
        self.assertTrue((self.real / "graphify-out" / "graph.json").is_file())
        self.assertEqual(corpo["sugestao_gitignore"], "graphify-out/")
        self.assertFalse(corpo["ja_no_gitignore"])
        self.assertFalse((self.real / ".gitignore").exists())                  # o Cérebro só SUGERE; não mexe no .gitignore

    def test_criar_mapa_trata_falhas(self):
        mapa_auto._estado.clear()
        pasta = amb.BASE / "mapa_falha"
        amb.apagar(pasta)
        pasta.mkdir()
        ok, msg = mapa_auto.criar_mapa("slug-falha", pasta, "x", rodar=lambda c: None)
        self.assertFalse(ok)
        self.assertIn("não criou", msg)
        self.assertFalse(mapa_auto.estado("slug-falha")["gerando"])

        def explode(c):
            raise subprocess.TimeoutExpired("g", 1)
        ok, msg = mapa_auto.criar_mapa("slug-falha", pasta, "x", rodar=explode)
        self.assertFalse(ok)
        self.assertIn("tempo limite", msg)
        mapa_auto._est("slug-falha")["gerando"] = True
        ok, msg = mapa_auto.criar_mapa("slug-falha", pasta, "x", rodar=lambda c: None)
        self.assertIsNone(ok)
        mapa_auto._est("slug-falha")["gerando"] = False


# ======================================================================================================================
# 6. instalar.py
# ======================================================================================================================
class TesteInstalar(unittest.TestCase):
    def setUp(self):
        self.raiz = amb.BASE / "instalacao"
        amb.apagar(self.raiz)
        self.raiz.mkdir()
        (self.raiz / "requirements.txt").write_text("aiohttp==3.14.5\n", encoding="utf-8")
        self.saida, self.gravador, self.perguntas = [], Gravador(), []
        sem_programas = mock.patch.object(instalar.shutil, "which", return_value=None)      # o PC de quem testa pode já ter Graphify/uv
        sem_programas.start()
        self.addCleanup(sem_programas.stop)
        sem_ganchos = mock.patch.object(instalar.Instalador, "oferecer_ganchos", return_value=False)   # testado em test_gestora_troca
        sem_ganchos.start()
        self.addCleanup(sem_ganchos.stop)

    def rodar(self, *args, entrada=None, com_pip=False):
        respostas = iter(entrada or [])

        def responder(pergunta=""):
            self.perguntas.append(pergunta)
            return next(respostas, "")
        return instalar.main(list(args), entrada=responder, saida=self.saida.append, executar=self.gravador, raiz=self.raiz,
                             area=amb.BASE / "AreaDeTrabalho", com_pip=com_pip)

    def texto(self):
        return "\n".join(self.saida + self.perguntas)

    def test_instala_no_venv_cria_a_casa_registra_e_explica_cada_passo(self):
        self.assertEqual(self.rodar("--nao", "--sem-abrir"), 0)
        self.assertTrue(instalar.python_do_venv(self.raiz / ".venv").is_file())
        pip = [c for c, _ in self.gravador.chamadas if "pip" in c]
        self.assertEqual(len(pip), 1)
        self.assertIn(str(instalar.python_do_venv(self.raiz / ".venv")), pip[0][0])
        self.assertIn("-r", pip[0])
        self.assertTrue(config.CASA.is_dir())
        for n in range(1, 7):
            self.assertIn(f"[{n}/6]", self.texto())
        self.assertEqual(json.loads((self.raiz / ".instalacao.json").read_text(encoding="utf-8"))["venv"], ".venv")

    def test_e_idempotente(self):
        self.rodar("--nao", "--sem-abrir")
        self.saida.clear()
        self.assertEqual(self.rodar("--nao", "--sem-abrir"), 0)
        self.assertIn("já existe", self.texto())

    def test_graphify_sempre_pergunta_e_so_instala_se_aceitar(self):
        self.rodar("--sem-dependencias", "--sem-abrir", entrada=["n", "n", "n"])
        ger = [c for c, _ in self.gravador.chamadas if "graphifyy" in c]
        self.assertEqual(ger, [])
        self.assertIn("Instalar o Graphify agora?", self.texto())
        self.gravador.chamadas.clear()
        self.rodar("--sem-dependencias", "--sem-abrir", "--sim")
        ger = [c for c, _ in self.gravador.chamadas if "graphifyy" in c]
        self.assertEqual(len(ger), 1)
        self.assertIn("--user", ger[0])                                     # sem uv: pip no usuário
        self.gravador.chamadas.clear()
        with mock.patch.object(instalar.shutil, "which", side_effect=lambda n: "C:/bin/uv.exe" if n == "uv" else None):
            self.rodar("--sem-dependencias", "--sem-abrir", "--sim")
            self.assertIn(["uv", "tool", "install", "graphifyy"], [c for c, _ in self.gravador.chamadas])

    def test_python_velho_para_com_explicacao(self):
        with mock.patch.object(instalar, "PYTHON_MINIMO", (99, 0)):
            self.assertEqual(self.rodar("--nao", "--sem-abrir"), 1)
        self.assertIn("python.org", self.texto())
        self.assertFalse((self.raiz / ".venv").exists())

    def test_sem_venv_instala_no_usuario(self):
        self.assertEqual(self.rodar("--nao", "--sem-abrir", "--sem-venv"), 0)
        pip = [c for c, _ in self.gravador.chamadas if "pip" in c]
        self.assertIn("--user", pip[0])
        self.assertFalse((self.raiz / ".venv").exists())

    @unittest.skipUnless(os.name == "nt", "atalho .lnk é do Windows")
    def test_atalho_pergunta_e_aponta_para_o_venv(self):
        self.rodar("--sem-dependencias", "--sem-abrir", entrada=["n", "s"])        # Graphify não / atalho sim
        ps = [(c, kw) for c, kw in self.gravador.chamadas if c and c[0] == "powershell"]
        self.assertEqual(len(ps), 1)
        env = ps[0][1]["env"]
        self.assertTrue(env["CEREBRO_LNK"].endswith("Cérebro do Projeto.lnk"))
        self.assertIn(".venv", env["CEREBRO_ALVO"])
        self.assertIn("abrir_cerebro.py", env["CEREBRO_ARGS"])
        self.assertIn("atalho", json.loads((self.raiz / ".instalacao.json").read_text(encoding="utf-8")))

    @unittest.skipUnless(os.name == "nt", "atalho .lnk é do Windows")
    def test_atalho_de_verdade_e_removido_pelo_desinstalador(self):
        area = amb.BASE / "AreaReal"
        area.mkdir(exist_ok=True)
        ins = instalar.Instalador(self.raiz, saida=self.saida.append)
        venv = ins.criar_venv(com_pip=False)
        lnk = ins.criar_atalho(venv, area)
        self.assertTrue(lnk and lnk.is_file())
        alvo = subprocess.run(["powershell", "-NoProfile", "-Command", f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').TargetPath"],
                              capture_output=True, text=True, creationflags=0x08000000).stdout.strip()
        self.assertTrue(alvo.lower().endswith(("pythonw.exe", "python.exe")))
        ins.gravar_registro()
        self.assertEqual(desinstalar.main(["--sim", "--manter-dados", "--sem-encerrar"], entrada=lambda _p="": "", saida=lambda _t: None, raiz=self.raiz), 0)
        self.assertFalse(lnk.exists())
        self.assertFalse((self.raiz / ".venv").exists())

    def test_abre_o_painel_so_se_aceitar(self):
        # perguntas antes de "Abrir o painel agora?": Graphify e, só no Windows, o atalho (no macOS/Linux ele não pergunta)
        antes = ["n", "n"] if os.name == "nt" else ["n"]
        self.rodar("--sem-dependencias", entrada=antes + ["n"])
        self.assertIn("Abrir o painel agora?", self.perguntas[-1])
        self.assertFalse(any("abrir_cerebro.py" in " ".join(c) for c, _ in self.gravador.chamadas))
        self.rodar("--sem-dependencias", entrada=antes + ["s"])
        self.assertIn("Abrir o painel agora?", self.perguntas[-1])
        self.assertTrue(any("abrir_cerebro.py" in " ".join(c) for c, _ in self.gravador.chamadas))


# ======================================================================================================================
# 7. desinstalar.py e as travas de remoção
# ======================================================================================================================
class TesteDesinstalar(unittest.TestCase):
    def setUp(self):
        self.raiz = amb.BASE / "desinstalacao"
        amb.apagar(self.raiz)
        (self.raiz / ".venv" / "Scripts").mkdir(parents=True)
        (self.raiz / ".venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")
        self.area = amb.BASE / "AreaDesinstalar"
        self.area.mkdir(exist_ok=True)
        self.lnk = self.area / desinstalar.NOME_ATALHO
        self.lnk.write_text("atalho", encoding="utf-8")
        (self.raiz / ".instalacao.json").write_text(json.dumps({"venv": ".venv", "atalho": str(self.lnk)}), encoding="utf-8")
        config.garantir_casa()
        (config.CASA / "config.json").write_text("{}", encoding="utf-8")
        (config.CASA / "projetos" / "x").mkdir(parents=True, exist_ok=True)
        (config.CASA / "projetos" / "x" / "decisoes.jsonl").write_text("{}\n", encoding="utf-8")
        self.saida = []

    def rodar(self, *args, entrada=None):
        respostas = iter(entrada or [])
        return desinstalar.main(list(args) + ["--sem-encerrar"], entrada=lambda _p="": next(respostas, ""), saida=self.saida.append, raiz=self.raiz)

    def test_tira_atalho_e_venv_e_mantem_os_dados_por_padrao(self):
        self.assertEqual(self.rodar("--sim", entrada=[]), 0)
        self.assertFalse(self.lnk.exists())
        self.assertFalse((self.raiz / ".venv").exists())
        self.assertTrue((config.CASA / "config.json").is_file())             # dados: o padrão da pergunta é NÃO
        self.assertIn("Dados mantidos", "\n".join(self.saida))

    def test_pergunta_antes_de_apagar_os_dados_mostrando_o_que_tem(self):
        self.rodar("--sim", entrada=["n"])
        texto = "\n".join(self.saida)
        self.assertIn("config.json", texto)
        self.assertIn("projetos", texto)
        self.assertTrue((config.CASA / "config.json").is_file())

    def test_so_apaga_os_dados_com_sim_explicito(self):
        self.rodar("--sim", entrada=["s"])
        self.assertFalse((config.CASA / "config.json").exists())
        self.assertFalse((config.CASA / "projetos").exists())

    def test_e_idempotente_e_explica(self):
        self.rodar("--sim", "--manter-dados")
        self.saida.clear()
        self.assertEqual(self.rodar("--sim", "--manter-dados"), 0)
        texto = "\n".join(self.saida)
        self.assertIn("nada a tirar", texto)
        self.assertIn("Não há .venv", texto)
        for n in range(1, 5):
            self.assertIn(f"[{n}/4]", texto)

    def test_nao_remove_atalho_com_outro_nome_nem_fora_do_permitido(self):
        outro = self.area / "Documento importante.lnk"
        outro.write_text("x", encoding="utf-8")
        (self.raiz / ".instalacao.json").write_text(json.dumps({"atalho": str(outro)}), encoding="utf-8")
        self.rodar("--sim", "--manter-dados")
        self.assertTrue(outro.exists())
        # registro adulterado apontando para o .claude: a trava recusa
        falso = config.PROJETOS_CLAUDE / "proj" / desinstalar.NOME_ATALHO
        falso.parent.mkdir(parents=True, exist_ok=True)
        falso.write_text("x", encoding="utf-8")
        (self.raiz / ".instalacao.json").write_text(json.dumps({"atalho": str(falso)}), encoding="utf-8")
        self.saida.clear()
        self.rodar("--sim", "--manter-dados")
        self.assertTrue(falso.exists())
        self.assertIn("Não removi", "\n".join(self.saida))

    def test_travas_de_remover_em_e_remover_casa(self):
        base = self.raiz
        for alvo in (base, base.parent, Path.home() / ".claude", Path.home()):
            with self.assertRaises(config.RemocaoRecusada):
                config.remover_em(base, alvo, pasta=True)
        with self.assertRaises(config.RemocaoRecusada):
            config.remover_em(base, base / ".venv", pasta=True, somente_nomes=("outro",))
        with self.assertRaises(config.RemocaoRecusada):
            config.remover_em(base, config.PROJETOS_CLAUDE / "x")
        # remover_casa recusa a pasta do usuário, o .claude e pastas que não são a casa do Cérebro
        for estranha in (Path.home(), config.CLAUDE, config.PROJETOS_CLAUDE, Path(Path.home().anchor)):
            with mock.patch.object(config, "CASA", estranha):
                with self.assertRaises(config.RemocaoRecusada):
                    config.remover_casa()
        with mock.patch.dict(os.environ):
            os.environ.pop("CEREBRO_HOME", None)
            with self.assertRaises(config.RemocaoRecusada):
                config.remover_casa()                                       # a casa de teste não se chama .cerebro
        self.assertTrue((config.CASA / "config.json").is_file())


# ======================================================================================================================
# 8. Demonstração com dados fictícios
# ======================================================================================================================
class TesteDemonstracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.destino = amb.BASE / "demo_saida"
        r = subprocess.run([sys.executable, str(RAIZ / "demo" / "gerar_demo.py"), "--destino", str(cls.destino)], capture_output=True, text=True, timeout=240)
        cls.erro = r.returncode != 0
        cls.saida = r.stdout + r.stderr

    def test_gerou_tres_projetos_inventados_com_tudo(self):
        self.assertFalse(self.erro, self.saida)
        projetos = sorted(p.name for p in (self.destino / "projetos").iterdir())
        self.assertEqual(projetos, ["app-de-receitas", "loja-de-plantas", "painel-de-metas"])
        casa = self.destino / "casa"
        cfg = json.loads((casa / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cfg["gestoras"]), 3)
        for slug_dir in (casa / "projetos").iterdir():
            if slug_dir.name == "_cerebro":
                continue
            for esperado in ("decisoes.jsonl", "propostas.json", "revisoes.json", "analises.json", "mapa/dados.js"):
                self.assertTrue((slug_dir / esperado).is_file(), f"{slug_dir.name}/{esperado}")
        loja = next((casa / "projetos").glob("*loja-de-plantas"))
        execs = json.loads((loja / "ferramentas" / "execucoes.json").read_text(encoding="utf-8"))["itens"]
        self.assertTrue(execs and all(x["resultado"] == "ok" for x in execs), execs)
        self.assertTrue((self.destino / "projetos" / "loja-de-plantas" / "graphify-out" / "graph.json").is_file())
        self.assertTrue(list((self.destino / "claude" / "projects").glob("*/memory/MEMORY.md")))

    def test_dados_da_demonstracao_nao_tem_nada_de_ninguem(self):
        proibidos = _proibidos()
        achados = []
        for p in self.destino.rglob("*"):
            if not p.is_file() or p.suffix in (".pyc",) or ".git" in p.relative_to(self.destino).parts or "token" == p.name:
                continue
            texto = p.read_text(encoding="utf-8", errors="replace")
            dest = str(self.destino)               # o caminho da pasta de teste aparece nos dados (é daqui, não da demonstração): não conta
            for variante in (dest, dest.replace("\\", "\\\\"), dest.replace("\\", "/"), re.sub(r"[^A-Za-z0-9]", "-", dest)):
                texto = texto.replace(variante, "")
            for rx in proibidos:
                if rx.search(texto) and "CEREBRO_" + "DO_PROJETO" not in rx.pattern:
                    achados.append((p.name, rx.pattern))
        self.assertEqual(achados, [])

    def test_gerar_de_novo_so_limpa_pasta_com_a_marca(self):
        estranha = amb.BASE / "demo_estranha"
        amb.apagar(estranha)
        estranha.mkdir()
        (estranha / "meu-arquivo.txt").write_text("importante", encoding="utf-8")
        r = subprocess.run([sys.executable, str(RAIZ / "demo" / "gerar_demo.py"), "--destino", str(estranha)], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((estranha / "meu-arquivo.txt").is_file())

    def test_servidor_sobe_com_a_demonstracao_e_mostra_os_projetos(self):
        import socket
        import urllib.request
        import http.cookiejar
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            porta = s.getsockname()[1]
        env = {**os.environ, "CEREBRO_HOME": str(self.destino / "casa"), "CEREBRO_CLAUDE": str(self.destino / "claude"), "PYTHONUTF8": "1"}
        srv = subprocess.Popen([sys.executable, str(RAIZ / "cerebro.py"), "--porta", str(porta)], env=env, cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (srv.kill(), srv.wait()))
        for _ in range(60):
            time.sleep(0.25)
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=1):
                    break
            except OSError:
                continue
        token = (self.destino / "casa" / "token").read_text(encoding="ascii").strip()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.open(f"http://127.0.0.1:{porta}/?t={token}", timeout=5).read()
        d = json.loads(op.open(f"http://127.0.0.1:{porta}/api/projetos", timeout=10).read())
        self.assertEqual(sorted(p["nome"] for p in d["projetos"]), ["app-de-receitas", "loja-de-plantas", "painel-de-metas"])
        self.assertTrue(d["primeiro_uso_concluido"])


class TesteRodarDemo(unittest.TestCase):
    def test_so_gerar_nao_sobe_servidor(self):
        destino = amb.BASE / "demo_rodar"
        r = subprocess.run([sys.executable, str(RAIZ / "demo" / "rodar_demo.py"), "--destino", str(destino), "--so-gerar"], capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((destino / "casa" / "config.json").is_file())


if __name__ == "__main__":
    unittest.main()
