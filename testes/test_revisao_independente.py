"""Regressões dos achados da revisão independente da v1.1 (máscara de campos, detecção sem executar código do projeto, migração do
config, token/cookie não-ASCII, caminhos com '..', trava de arquivo, comando preso, mapa travado, dois servidores, ACL do token)."""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import acesso_windows, agentes, armazem, config, ferramentas, indice, mapa_auto, memoria, novidades, projetos, servidor, transcricao
from cerebro.segredos import OCULTO
from testes.test_servidor import Base

CRLF = chr(13) + chr(10)
CHAVE = "sk-ant-api03-" + "Zq9" * 12          # "segredo" falso, no formato de chave


def carregar_gerar():
    spec = importlib.util.spec_from_file_location("gerar_mapa_ri", amb.RAIZ / "mapa" / "gerar.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TesteMascaraDosCampos(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()

    def tearDown(self):
        self.desmontar_mundo()

    def test_titulo_da_memoria_e_busca_mascarados_antes_do_corte(self):
        mem = self.pasta_claude / "memory"
        mem.mkdir(exist_ok=True)
        (mem / "a.md").write_text(f"---\nname: titulo {CHAVE}\ndescription: d\nmetadata:\n  type: feedback\n---\nCorpo\n", encoding="utf-8")
        # o segredo começa pouco antes de onde o trecho seria cortado (termo + 110 caracteres)
        corpo = "zebra " + "x" * 100 + " " + CHAVE + " fim"
        (mem / "b.md").write_text(f"---\nname: b\n---\n{corpo}\n", encoding="utf-8")
        itens = {i["arquivo"]: i for i in memoria.listar(self.slug, str(self.real))["itens"]}
        self.assertNotIn(CHAVE[:20], itens["a.md"]["titulo"])
        achados = memoria.buscar(self.slug, str(self.real), "zebra")
        self.assertTrue(achados)
        for a in achados:
            self.assertNotIn("sk-ant", a["trecho"], a["trecho"])
            self.assertNotIn(CHAVE[-12:], a["trecho"])

    def test_descricao_do_subagente_chega_mascarada(self):
        self.criar_subagente("c1c2c3c4c5", f"Testar a API usando {CHAVE} agora")
        arq = next(a for a in indice.listar_arquivos(self.slug) if a["tipo"] == "subagente")
        self.assertNotIn("sk-ant", indice.ler_meta(self.slug, arq)["description"])
        cfg = config.ler_config()
        d = agentes.montar(self.slug, cfg["precos"], cfg["gestoras"][self.slug]["conversa"], todas=True, cfg=cfg)
        for ses in d["sessoes"]:
            for s in ses["subagentes"]:
                self.assertNotIn("sk-ant", s["descricao"])
                self.assertIn(OCULTO, s["descricao"])

    def test_assunto_do_commit_mascarado(self):
        subprocess.run(["git", "init", "-q"], cwd=str(self.real), check=True)
        (self.real / "a.txt").write_text("a", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(self.real), check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ajusta login password=hunter22abc"],
                       cwd=str(self.real), check=True, capture_output=True)
        projetos._git_cache.clear()
        info = projetos.info_git(str(self.real))
        self.assertNotIn("hunter22abc", info["assunto"])
        self.assertIn("ajusta login", info["assunto"])

    def test_titulo_nome_e_resumo_do_indice_mascarados(self):
        pasta = amb.BASE / "ind"
        pasta.mkdir(exist_ok=True)
        arq = pasta / "s.jsonl"
        arq.write_text(
            json.dumps({"type": "custom-title", "customTitle": f"meu titulo {CHAVE}"}) + "\n"
            + json.dumps({"type": "agent-name", "agentName": "agente senha: abc"}) + "\n"
            + json.dumps({"type": "summary", "summary": f"resumo com {CHAVE}", "aiTitle": f"ia {CHAVE}"}) + "\n", encoding="utf-8")
        ind, _ = transcricao.atualizar_indice(arq)
        for campo in ("titulo", "nome_agente", "resumo", "titulo_ia"):
            self.assertNotIn("sk-ant", ind[campo], campo)
        self.assertNotIn("abc", ind["nome_agente"].replace("agente", ""))

    def test_docstring_e_comentario_do_mapa_mascarados_antes_do_corte(self):
        gerar = carregar_gerar()
        self.assertNotIn("sk-ant", gerar._corta("a" * 40 + " " + CHAVE + " resto", 60))
        doc = gerar.cabecalho_do_arquivo("x.py", [f'"""Usa {CHAVE} para chamar a API."""', "x = 1"])
        self.assertNotIn("sk-ant", doc)
        js = gerar.cabecalho_do_arquivo("x.js", [f"// senha: {'q' * 12} e {CHAVE}", "var a = 1;"])
        self.assertNotIn("sk-ant", js)
        self.assertNotIn("qqqqqqqq", js)

    def test_index_antigo_em_disco_e_refeito(self):
        self.assertGreaterEqual(indice.VERSAO_INDICE, 2)


class TesteDeteccaoSemExecutarOProjeto(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        (self.real / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        ferramentas._cache_det.clear()

    def tearDown(self):
        self.desmontar_mundo()

    def test_binario_de_node_modules_nao_e_executado(self):
        bin_ = self.real / "node_modules" / ".bin"
        bin_.mkdir(parents=True)
        marca = self.real / "executou.txt"
        (bin_ / "eslint.cmd").write_text(f"@echo off\r\necho rodei > \"{marca}\"\r\necho 9.9.9\r\n", encoding="utf-8")
        (bin_ / "eslint").write_text(f"#!/bin/sh\necho rodei > '{marca}'\n", encoding="utf-8")
        (self.real / "node_modules" / "eslint").mkdir()
        (self.real / "node_modules" / "eslint" / "package.json").write_text('{"version": "9.1.2"}', encoding="utf-8")
        antes = ferramentas.shutil.which
        ferramentas.shutil.which = lambda nome, *a, **k: None          # sem eslint global no PATH
        self.addCleanup(setattr, ferramentas.shutil, "which", antes)
        det = {d["id"]: d for d in ferramentas.detectar(str(self.real), forcar=True)}
        self.assertFalse(marca.exists(), "a detecção executou um binário de dentro do projeto")
        self.assertTrue(det["eslint"]["instalada"])
        self.assertIn("node_modules", det["eslint"]["versao"])
        self.assertIn("9.1.2", det["eslint"]["versao"])

    def test_exe_nunca_procura_dentro_do_projeto(self):
        bin_ = self.real / "node_modules" / ".bin"
        bin_.mkdir(parents=True)
        (bin_ / "foo.cmd").write_text("@echo off\r\n", encoding="utf-8")
        antes = ferramentas.shutil.which
        ferramentas.shutil.which = lambda nome, *a, **k: None
        self.addCleanup(setattr, ferramentas.shutil, "which", antes)
        self.assertIsNone(ferramentas._exe("foo", str(self.real)))

    def test_versao_roda_em_pasta_neutra_e_modulo_python_isolado(self):
        chamadas = []

        class R:
            returncode, stdout, stderr = 0, "x 1.0\n", ""

        original = ferramentas.subprocess.run
        ferramentas.subprocess.run = lambda argv, **kw: (chamadas.append((argv, kw)), R())[1]
        self.addCleanup(setattr, ferramentas.subprocess, "run", original)
        ferramentas._modulo_python("ruff")
        argv, kw = chamadas[0]
        self.assertEqual(kw["cwd"], str(config.CASA))
        self.assertNotEqual(Path(kw["cwd"]).resolve(), Path.home().resolve())
        self.assertEqual(argv[1:3], ["-I", "-m"])


class TesteMigracaoDoConfig(unittest.TestCase):
    def setUp(self):
        amb.apagar(config.CASA / "config.json")

    def gravar(self, d):
        config.garantir_casa()
        (config.CASA / "config.json").write_text(json.dumps(d), encoding="utf-8")

    def test_padroes_novos_entram_sem_apagar_o_que_o_dono_mudou(self):
        self.gravar({"versao": 2, "tema": "claro",
                     "precos": {"claude-opus-5-5": {"entrada": 99.0, "saida": 1, "cache_leitura": 1, "cache_escrita_5m": 1, "cache_escrita_1h": 1}},
                     "agentes_regras": [{"id": "meu", "nome": "Meu", "modelo": "haiku", "revisor": "eu", "palavras": ["x"]},
                                        {"id": "codigo", "nome": "Código do dono", "modelo": "opus", "revisor": "eu", "palavras": ["y"]}],
                     "fontes_novidades": [{"id": "claude-code", "nome": "Meu nome", "repo": "anthropics/claude-code"}],
                     "comandos": {amb.SLUG_EXEMPLO: [{"id": "lint", "nome": "Meu lint", "argv": ["{python}", "x.py"]}], "outro": []},
                     "gestoras": {"x": {"conversa": "c", "nome": "n"}}, "departamentos": {"x": {"modo": "pastas"}}})
        cfg = config.ler_config()
        self.assertEqual(cfg["tema"], "claro")
        self.assertEqual(cfg["versao"], config.CONFIG_PADRAO["versao"])
        self.assertEqual(cfg["precos"]["claude-opus-5-5"]["entrada"], 99.0)                    # o do dono vale
        self.assertIn("claude-haiku-5-5", cfg["precos"])                                       # o novo entrou
        regras = {r["id"]: r for r in cfg["agentes_regras"]}
        self.assertEqual(regras["codigo"]["nome"], "Código do dono")
        self.assertIn("meu", regras)
        self.assertIn("critico", regras)
        self.assertIn("mecanico", regras)
        fontes = {f["id"]: f for f in cfg["fontes_novidades"]}
        self.assertEqual(fontes["claude-code"]["nome"], "Meu nome")
        self.assertIn("graphify", fontes)
        cmds = {c["id"]: c for c in cfg["comandos"][amb.SLUG_EXEMPLO]}
        self.assertEqual(cmds["lint"]["nome"], "Meu lint")
        self.assertIn("outro", cfg["comandos"])
        self.assertIn("x", cfg["gestoras"])
        self.assertNotIn(amb.SLUG_EXEMPLO, cfg["gestoras"])              # nenhum projeto vem com gestora pronta
        self.assertIn("x", cfg["departamentos"])

    def test_migracao_roda_uma_vez_e_o_que_o_dono_apagar_depois_nao_volta(self):
        self.gravar({"versao": 1})
        cfg = config.ler_config()
        gravado = json.loads((config.CASA / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(gravado["versao"], config.CONFIG_PADRAO["versao"])                    # gravou a versão nova
        config.atualizar_config(lambda c: c.__setitem__("agentes_regras", [r for r in c["agentes_regras"] if r["id"] != "mecanico"]))
        self.assertNotIn("mecanico", [r["id"] for r in config.ler_config()["agentes_regras"]])
        self.assertIn("critico", [r["id"] for r in cfg["agentes_regras"]])

    def test_config_nova_ja_nasce_na_versao_atual(self):
        cfg = config.ler_config()
        self.assertEqual(cfg["versao"], config.CONFIG_PADRAO["versao"])

    def test_comentario_dos_comandos_nao_manda_editar_o_codigo(self):
        fonte = (amb.RAIZ / "cerebro" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("edite este arquivo", fonte)


class TesteTokenECookie(Base):
    async def test_token_nao_ascii_da_401_e_nao_500(self):
        r = await self.http.get(f"{self.base}/?t=%C3%A9", allow_redirects=False)
        self.assertEqual(r.status, 401)
        r = await self.http.get(f"{self.base}/?t=%FF%FE", allow_redirects=False)
        self.assertEqual(r.status, 401)

    async def test_cookie_nao_ascii_da_401(self):
        import asyncio
        for valor in ("é", "€€", "a" * 10 + "ç"):
            leitor, escritor = await asyncio.open_connection("127.0.0.1", self.porta)
            pedido = CRLF.join(["GET /api/projetos HTTP/1.1", f"Host: 127.0.0.1:{self.porta}", "Connection: close", f"Cookie: cerebro_sessao_{self.porta}={valor}", "", ""])
            escritor.write(pedido.encode("utf-8"))
            await escritor.drain()
            linha = (await leitor.readline()).decode("latin-1")
            escritor.close()
            self.assertIn(" 401 ", linha, valor)

    def test_comparacao_em_bytes(self):
        self.assertTrue(servidor._iguais("abc", "abc"))
        self.assertFalse(servidor._iguais("abç", "abc"))
        self.assertFalse(servidor._iguais("é", "e"))

    def test_sem_aviso_de_appkey(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            servidor.criar_app(8999, token="t" * 43)
        self.assertEqual([x for x in w if "AppKey" in str(x.message)], [])


class TesteCaminhosDoTranscrito(Base):
    def test_ponto_e_ponto_ponto_sao_recusados(self):
        ruins = ["../subagents/agent-x.jsonl", "./subagents/agent-x.jsonl", "../x.jsonl", "..", ".", "a/../subagents/agent-x.jsonl",
                 "...//subagents/agent-x.jsonl", "a/subagents/../agent-x.jsonl", "x.txt", "", None, "a/b.jsonl"]
        for r in ruins:
            self.assertFalse(servidor.rel_valido(r), r)
        for r in ["abc.jsonl", "11111111-2222-3333-4444-555555555555.jsonl", "3e25/subagents/agent-a1b2.jsonl"]:
            self.assertTrue(servidor.rel_valido(r), r)

    async def test_passos_recusa_ponto_ponto(self):
        await self.entrar()
        r = await self.http.get(f"{self.base}/api/p/{self.slug}/passos", params={"rel": "../subagents/agent-x.jsonl"})
        self.assertIn(r.status, (400, 404))


class TesteTravaDeArquivo(unittest.TestCase):
    def setUp(self):
        self.arq = amb.CASA / "trava_teste.json"
        amb.CASA.mkdir(parents=True, exist_ok=True)
        self.lock = Path(str(self.arq) + ".lock")
        amb.apagar(self.lock)

    def test_normal_cria_e_remove(self):
        with armazem._TravaDeArquivo(self.arq):
            self.assertTrue(self.lock.is_file())
        self.assertFalse(self.lock.exists())

    def test_nao_remove_a_trava_dos_outros_ao_estourar_o_prazo(self):
        self.lock.write_text("marca-de-outro-processo", encoding="ascii")
        t0 = time.monotonic()
        with armazem._TravaDeArquivo(self.arq, espera=0.3):
            pass
        self.assertLess(time.monotonic() - t0, 3)                       # respeita o prazo
        self.assertTrue(self.lock.is_file())                            # e a trava do outro continua lá
        self.assertEqual(self.lock.read_text(encoding="ascii"), "marca-de-outro-processo")

    def test_trava_velha_e_descartada(self):
        self.lock.write_text("velha", encoding="ascii")
        antiga = time.time() - 120
        os.utime(self.lock, (antiga, antiga))
        with armazem._TravaDeArquivo(self.arq, espera=2) as t:
            self.assertTrue(t.minha)
            self.assertEqual(self.lock.read_text(encoding="ascii"), t.marca)
        self.assertFalse(self.lock.exists())

    def test_so_remove_se_a_marca_for_a_sua(self):
        t = armazem._TravaDeArquivo(self.arq)
        with t:
            self.lock.write_text("outra-marca", encoding="ascii")        # alguém trocou a trava
        self.assertTrue(self.lock.is_file())

    def test_espera_com_sleep_e_prazo_mesmo_com_arquivo_sumindo(self):
        t0 = time.monotonic()
        os_open = os.open
        chamadas = []

        def instavel(caminho, flags, *a, **k):
            chamadas.append(1)
            raise PermissionError("negado")                              # erro que antes virava laço sem sleep
        os.open = instavel
        try:
            with armazem._TravaDeArquivo(self.arq, espera=0.4):
                pass
        finally:
            os.open = os_open
        self.assertLess(time.monotonic() - t0, 3)
        self.assertLess(len(chamadas), 200)                              # dormiu entre as tentativas


class TesteComandoPreso(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        (self.real / "ok.py").write_text("print('feito')\n", encoding="utf-8")
        config.atualizar_config(lambda c: c["comandos"].__setitem__(self.slug, [{"id": "ok", "nome": "Ok", "argv": ["{python}", "ok.py"], "timeout": 30}]))
        self.cfg = config.ler_config()

    def tearDown(self):
        self.desmontar_mundo()

    def test_remocao_recusada_ao_guardar_nao_prende_o_projeto(self):
        original = ferramentas._guardar_registro

        def recusa(slug, registro):
            raise config.RemocaoRecusada("teste")
        ferramentas._guardar_registro = recusa
        self.addCleanup(setattr, ferramentas, "_guardar_registro", original)
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "ok")
        fim = time.time() + 20
        while time.time() < fim and self.slug in ferramentas._rodando:
            time.sleep(0.1)
        self.assertNotIn(self.slug, ferramentas._rodando)
        ferramentas._guardar_registro = original
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "ok")          # dá para rodar de novo
        fim = time.time() + 20
        while time.time() < fim and self.slug in ferramentas._rodando:
            time.sleep(0.1)
        self.assertNotIn(self.slug, ferramentas._rodando)


class TesteMapaTravado(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        mapa_auto._estado.clear()
        self.graph = self.real / "graphify-out" / "graph.json"
        self.graph.parent.mkdir()
        self.graph.write_text("{}", encoding="utf-8")
        antiga = time.time() - 120
        os.utime(self.graph, (antiga, antiga))

    def tearDown(self):
        self.desmontar_mundo()

    def test_excecao_qualquer_solta_o_gerando(self):
        def explode(caminho):
            raise RuntimeError("quebrou")
        mapa_auto.varrer(gerar_fn=explode)
        e = mapa_auto.estado(self.slug)
        self.assertFalse(e["gerando"])
        self.assertIn("quebrou", e["ultimo_erro"])

    def test_timeout_vira_mensagem_clara(self):
        def demora(caminho):
            raise subprocess.TimeoutExpired("gerar", 300)
        mapa_auto.varrer(gerar_fn=demora)
        e = mapa_auto.estado(self.slug)
        self.assertFalse(e["gerando"])
        self.assertIn("tempo limite", e["ultimo_erro"])

    def test_botao_manual_marca_gerando_e_nao_roda_junto(self):
        livre, entrou = threading.Event(), threading.Event()
        original = mapa_auto.gerar

        def lento(caminho, timeout=300):
            entrou.set()
            livre.wait(10)
            return True, "ok"
        mapa_auto.gerar = lento
        self.addCleanup(setattr, mapa_auto, "gerar", original)
        resultado = []
        t = threading.Thread(target=lambda: resultado.append(mapa_auto.gerar_agora(self.slug, str(self.real))))
        t.start()
        self.assertTrue(entrou.wait(5))
        self.assertTrue(mapa_auto.estado(self.slug)["gerando"])
        ok, msg = mapa_auto.gerar_agora(self.slug, str(self.real))             # segundo pedido: recusado, sem rodar junto
        self.assertIsNone(ok)
        self.assertIn("já está sendo gerado", msg)
        chamou = []
        self.assertEqual(mapa_auto.varrer(forcar=True, gerar_fn=lambda c: chamou.append(c) or (True, "")), [])    # o vigia também espera
        self.assertEqual(chamou, [])
        livre.set()
        t.join(10)
        self.assertEqual(resultado[0][0], True)
        self.assertFalse(mapa_auto.estado(self.slug)["gerando"])

    def test_manual_com_timeout_e_erro_solta_a_marca(self):
        original = mapa_auto.gerar
        self.addCleanup(setattr, mapa_auto, "gerar", original)
        mapa_auto.gerar = lambda c, timeout=300: (_ for _ in ()).throw(subprocess.TimeoutExpired("g", 1))
        ok, msg = mapa_auto.gerar_agora(self.slug, str(self.real))
        self.assertFalse(ok)
        self.assertIn("tempo limite", msg)
        self.assertFalse(mapa_auto.estado(self.slug)["gerando"])
        mapa_auto.gerar = lambda c, timeout=300: (_ for _ in ()).throw(OSError("sem python"))
        ok, msg = mapa_auto.gerar_agora(self.slug, str(self.real))
        self.assertFalse(ok)
        self.assertIn("sem python", msg)
        self.assertFalse(mapa_auto.estado(self.slug)["gerando"])


class TesteRotasDoMapa(Base):
    async def test_botao_gerar_timeout_e_ocupado_e_intervalo_na_tela(self):
        graph = self.real / "graphify-out" / "graph.json"
        graph.parent.mkdir()
        graph.write_text("{}", encoding="utf-8")
        mapa_auto._estado.clear()
        await self.entrar()
        original = mapa_auto.gerar
        self.addCleanup(setattr, mapa_auto, "gerar", original)
        mapa_auto.gerar = lambda c, timeout=300: (_ for _ in ()).throw(subprocess.TimeoutExpired("g", 1))
        r = await self.post(f"/api/p/{self.slug}/mapa/gerar", {})
        self.assertEqual(r.status, 500)
        corpo = await r.json()
        self.assertIn("tempo limite", corpo["erro"])
        mapa_auto._est(self.slug)["gerando"] = True
        r = await self.post(f"/api/p/{self.slug}/mapa/gerar", {})
        self.assertEqual(r.status, 409)
        mapa_auto._est(self.slug)["gerando"] = False
        config.atualizar_config(lambda c: c["rotinas"].__setitem__("mapa_vigia_segundos", 45))
        est = await (await self.http.get(f"{self.base}/api/p/{self.slug}/mapa/estado")).json()
        self.assertEqual(est["intervalo_s"], 45)

    def test_texto_fixo_de_30_s_saiu_da_tela(self):
        js = (amb.RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("a cada 30 s", js)
        self.assertIn("intervalo_s", js)


class TesteDoisServidores(unittest.TestCase):
    def setUp(self):
        self.arq = config.CASA / "servidor.json"
        config.garantir_casa()
        amb.apagar(self.arq)
        self.outro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: (self.outro.kill(), self.outro.wait()))

    def test_segundo_servidor_nao_sobrescreve_nem_apaga_o_do_primeiro(self):
        original = json.dumps({"pid": self.outro.pid, "porta": 8188, "inicio": 1, "versao": "x"})
        self.arq.write_text(original, encoding="utf-8")
        self.assertFalse(servidor.registrar_instancia(8199))              # outro servidor vivo: não grava
        self.assertEqual(self.arq.read_text(encoding="utf-8"), original)
        servidor.liberar_instancia()                                      # nem apaga o que não é seu
        self.assertEqual(self.arq.read_text(encoding="utf-8"), original)

    def test_pid_morto_e_sobrescrito_e_so_o_dono_apaga(self):
        self.outro.kill()
        self.outro.wait()
        self.arq.write_text(json.dumps({"pid": self.outro.pid, "porta": 8188}), encoding="utf-8")
        self.assertTrue(servidor.registrar_instancia(8199))
        self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8"))["pid"], os.getpid())
        servidor.liberar_instancia()
        self.assertFalse(self.arq.exists())

    def test_arquivo_quebrado_nao_derruba(self):
        self.arq.write_text("lixo{", encoding="utf-8")
        self.assertTrue(servidor.registrar_instancia(8199))
        servidor.liberar_instancia()

    def test_pid_vivo(self):
        self.assertTrue(servidor._pid_vivo(os.getpid()))
        self.assertFalse(servidor._pid_vivo(0))
        self.assertFalse(servidor._pid_vivo(-5))
        self.assertFalse(servidor._pid_vivo("x"))


class TesteAclDoToken(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "lista de acesso (ACL) e icacls são do Windows; no macOS/Linux vale o modo 600")
    def test_token_existente_tem_o_acesso_reaplicado(self):
        amb.apagar(config.CASA / "token")
        t = config.ler_token()
        caminho = config.CASA / "token"

        def quem():                                    # aparece no registro do CI se falhar: SID do usuário e as entradas
            return f"usuário {acesso_windows.sid_do_usuario()!r}, entradas {acesso_windows.entradas(caminho)!r}"
        self.assertTrue(acesso_windows.sid_do_usuario().startswith("S-"))
        self.assertTrue(config.acesso_so_do_dono(caminho), quem())
        subprocess.run(["icacls", str(caminho), "/inheritance:e"], capture_output=True, creationflags=0x08000000)    # volta a herdar: mais de um acesso
        self.assertFalse(config.acesso_so_do_dono(caminho), quem())
        config._acl_feita.clear()
        self.assertEqual(config.ler_token(), t)                           # ler um token que já existe reaplica a restrição
        self.assertTrue(config.acesso_so_do_dono(caminho), quem())

    @unittest.skipUnless(os.name == "nt", "lista de acesso (ACL) e icacls são do Windows")
    def test_entradas_explicitas_de_outros_tambem_saem(self):
        # No runner do GitHub (administrador) o arquivo nasce com SYSTEM, Administradores e OWNER RIGHTS EXPLÍCITOS, que o
        # `icacls /inheritance:r` não tira. Simula com uma entrada explícita para Administradores (S-1-5-32-544).
        for via_api in (True, False):                                    # False: a API falha e vale a reserva do icacls
            with self.subTest(via_api=via_api):
                caminho = amb.BASE / f"acl_extra_{via_api}.txt"
                amb.apagar(caminho)
                caminho.write_text("segredo", encoding="ascii")
                subprocess.run(["icacls", str(caminho), "/grant", "*S-1-5-32-544:R"], capture_output=True, creationflags=0x08000000)
                self.assertIn((0, "S-1-5-32-544"), acesso_windows.entradas(caminho))
                self.assertFalse(config.acesso_so_do_dono(caminho))
                if via_api:
                    config._restringir_ao_dono(caminho)
                else:
                    with mock.patch.object(acesso_windows, "restringir", return_value=False):
                        config._restringir_ao_dono(caminho)
                eu = acesso_windows.sid_do_usuario()
                self.assertTrue(config.acesso_so_do_dono(caminho), f"entradas {acesso_windows.entradas(caminho)!r}")
                self.assertEqual([s for t, s in acesso_windows.entradas(caminho) if t == 0], [eu])
                self.assertEqual(caminho.read_text(encoding="ascii"), "segredo")        # o dono continua lendo

    @unittest.skipIf(os.name == "nt", "no Windows vale a lista de acesso (teste acima)")
    def test_token_fica_com_modo_600_fora_do_windows(self):
        amb.apagar(config.CASA / "token")
        config.ler_token()
        caminho = config.CASA / "token"
        self.assertTrue(config.acesso_so_do_dono(caminho))
        os.chmod(caminho, 0o644)
        self.assertFalse(config.acesso_so_do_dono(caminho))
        config._acl_feita.clear()
        config.ler_token()
        self.assertTrue(config.acesso_so_do_dono(caminho))

    def test_regra_so_do_dono_pelos_sids(self):
        eu, outro = "S-1-5-21-1-2-3-1001", "S-1-5-18"
        casos = [([(0, eu)], True), ([(0, eu), (1, outro)], True),           # negar acesso a outro não abre nada
                 ([(0, eu), (0, outro)], False), ([(0, outro)], False),      # SYSTEM/Administradores herdados = não é só do dono
                 ([(1, eu)], False), ([], False), (None, False),             # ninguém tem acesso / lista ilegível ou nula
                 ([(0, eu), (5, "")], False)]                                # tipo que não sabemos ler: na dúvida, não
        for lista, esperado in casos:
            with mock.patch.object(acesso_windows, "entradas", return_value=lista):
                self.assertEqual(acesso_windows.so_do_dono("x", sid=eu), esperado, lista)


class TesteNovidadesHref(unittest.TestCase):
    def test_url_estranha_vira_a_pagina_de_releases(self):
        def buscar(url):
            return 200, {"tag_name": "v1", "name": "v1", "published_at": "", "body": "", "html_url": "javascript:alert(1)"}
        v = novidades._ultima_versao("anthropics/claude-code", buscar)
        self.assertTrue(v["url"].startswith("https://github.com/"))

    def test_tela_so_cria_link_https(self):
        js = (amb.RAIZ / "web" / "abas.js").read_text(encoding="utf-8")
        self.assertIn("/^https:\\/\\//.test(f.ultima.url", js)


if __name__ == "__main__":
    unittest.main()
