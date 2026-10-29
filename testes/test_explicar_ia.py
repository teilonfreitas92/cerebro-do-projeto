"""Explicação por IA dos pontos do mapa: lotes, cache, retomada, desatualizada, segredo fora do lote, JSON quebrado, rotas e CLI.
Nunca roda o `claude` de verdade nem usa a rede: a função de chamada é trocada por uma falsa."""
import contextlib
import importlib.util
import io
import json
import re
import subprocess
import threading
import unittest
from unittest import mock

from aiohttp import ClientSession, CookieJar
from aiohttp.test_utils import TestServer

from testes import _ambiente as amb
from cerebro import armazem, config, explicar_ia, mapa_auto, projetos, servidor

SEGREDO_NO_CODIGO = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
SEGREDO_DO_ENV = "supersecretvalue123"


def falso_ok(sistema, prompt):
    """IA de mentira: uma frase por ponto, no formato pedido."""
    itens = re.findall(r"^### (\d+)$", prompt, re.M)
    nomes = re.findall(r"^nome: (.*)$", prompt, re.M)
    return json.dumps([{"i": int(i), "t": f"Faz {n}."} for i, n in zip(itens, nomes)]), {"entrada": 100, "saida": 50}


class ComProjeto(amb.MundoFalso):
    """Projeto de mentira com graphify-out: 45 funções em app.py (com cabeçalho), uma com segredo, util.py sem cabeçalho, .env e um json de segredos."""

    def montar(self, n=45):
        self.montar_mundo("ProjIA")
        self.prompts = []
        raiz = self.real
        fonte = ['"""Programa de teste."""', ""]
        for i in range(n):
            fonte += [f"def f{i}(x):", f"    return x + {i}", ""]
        fonte += ["def usa_chave():", f'    API_KEY = "{SEGREDO_NO_CODIGO}"', "    return API_KEY", ""]
        (raiz / "app.py").write_text("\n".join(fonte), encoding="utf-8")
        (raiz / "util.py").write_text("import os\n\n\ndef ajuda():\n    return os.getcwd()\n", encoding="utf-8")
        (raiz / ".env").write_text(f"DB_PASSWORD={SEGREDO_DO_ENV}\n", encoding="utf-8")
        (raiz / "config").mkdir()
        (raiz / "config" / "segredos.json").write_text(f'{{"senha": "{SEGREDO_DO_ENV}"}}', encoding="utf-8")
        nos = [{"id": "app", "label": "app.py", "file_type": "code", "source_file": "app.py", "source_location": "L1", "community": 0},
               {"id": "util", "label": "util.py", "file_type": "code", "source_file": "util.py", "source_location": "L1", "community": 0},
               {"id": "ajuda", "label": "ajuda()", "file_type": "code", "source_file": "util.py", "source_location": "L4", "community": 0},
               {"id": "env", "label": ".env", "file_type": "code", "source_file": ".env", "source_location": "L1", "community": 0},
               {"id": "chave", "label": "chave()", "file_type": "code", "source_file": "config/segredos.json", "source_location": "L1", "community": 0},
               {"id": "usa_chave", "label": "usa_chave()", "file_type": "code", "source_file": "app.py", "source_location": f"L{3 + 3 * n}", "community": 0}]
        ligas = [{"source": "app", "target": "usa_chave", "relation": "contains", "confidence": "EXTRACTED"},
                 {"source": "util", "target": "ajuda", "relation": "contains", "confidence": "EXTRACTED"}]
        for i in range(n):
            nos.append({"id": f"f{i}", "label": f"f{i}()", "file_type": "code", "source_file": "app.py", "source_location": f"L{3 + 3 * i}", "community": 0})
            ligas.append({"source": "app", "target": f"f{i}", "relation": "contains", "confidence": "EXTRACTED"})
        for i in range(1, 11):                         # f0 é chamada por 10: o mais ligado
            ligas.append({"source": f"f{i}", "target": "f0", "relation": "calls", "confidence": "EXTRACTED"})
        nos.append({"id": "r1", "label": "Soma o número", "file_type": "rationale", "source_file": "app.py", "source_location": "L4", "community": 0})
        ligas.append({"source": "r1", "target": "f1", "relation": "rationale_for", "confidence": "EXTRACTED"})      # f1 já tem texto próprio
        saida = raiz / "graphify-out"
        saida.mkdir()
        (saida / "graph.json").write_text(json.dumps({"directed": False, "multigraph": False, "graph": {}, "nodes": nos, "links": ligas}), encoding="utf-8")
        (saida / ".graphify_analysis.json").write_text(json.dumps({"communities": {"0": [n_["id"] for n_ in nos]}, "cohesion": {"0": 1.0}, "gods": [], "surprises": []}), encoding="utf-8")
        (saida / ".graphify_labels.json").write_text(json.dumps({"0": "Grupo de teste"}), encoding="utf-8")
        self.n = n
        self.caminho = str(raiz)

    def chamador_gravando(self, base=falso_ok):
        def f(sistema, prompt):
            self.prompts.append(prompt)
            return base(sistema, prompt)
        return f


class TesteSensiveis(unittest.TestCase):
    def test_nomes_sensiveis(self):
        for nome in (".env", "app/.env.local", "prod.env", "chave.pem", "a/b/id_rsa", "x/credentials.json", "config/segredos.json",
                     "token_google.json", "senhas.txt", "pasta/.ssh/config", "secrets/dados.py", "cert.pfx"):
            self.assertTrue(explicar_ia.arquivo_sensivel(nome), nome)

    def test_codigo_comum_nao_e_sensivel(self):
        for nome in ("cerebro/segredos.py", "src/token_bucket.rs", "web/app.js", "tokens.css", "README.md", "util.py"):
            self.assertFalse(explicar_ia.arquivo_sensivel(nome), nome)

    def test_configuracoes_de_ferramentas_da_pasta_do_usuario_sao_sensiveis(self):
        for nome in (".claude.json", ".claude/settings.json", ".claude/settings.local.json", "settings.json", ".config/gh/hosts.yml",
                     "gh/hosts.yml", ".docker/config.json", "rclone.conf", ".config/rclone/rclone.conf", ".claude/.credentials.json"):
            self.assertTrue(explicar_ia.arquivo_sensivel(nome), nome)


class TesteRaizDoMapa(amb.MundoFalso, unittest.TestCase):
    """graphify-out/.graphify_root escolhe de onde ler o código: só vale se for a pasta do projeto ou uma pasta dentro dela."""

    def setUp(self):
        self.montar_mundo("ProjRaiz")
        (self.real / "graphify-out").mkdir()
        self.marca = self.real / "graphify-out" / ".graphify_root"

    def tearDown(self):
        self.desmontar_mundo()

    def test_raiz_fora_do_projeto_e_ignorada(self):
        fora = self.real.parent / "pasta_do_usuario_falsa"
        fora.mkdir(exist_ok=True)
        (fora / ".claude.json").write_text('{"oauth": "segredo-de-mentira"}', encoding="utf-8")
        for alvo in (fora, self.real.parent, self.real / ".." / "pasta_do_usuario_falsa"):
            self.marca.write_text(str(alvo), encoding="utf-8")
            self.assertEqual(explicar_ia._raiz_do_projeto(str(self.real)), self.real, alvo)

    def test_raiz_dentro_do_projeto_vale(self):
        (self.real / "src").mkdir()
        self.marca.write_text(str(self.real / "src"), encoding="utf-8")
        self.assertEqual(explicar_ia._raiz_do_projeto(str(self.real)).resolve(), (self.real / "src").resolve())
        self.marca.write_text(str(self.real), encoding="utf-8")
        self.assertEqual(explicar_ia._raiz_do_projeto(str(self.real)).resolve(), self.real.resolve())


class TesteTextos(unittest.TestCase):
    def test_resposta_normal_com_cerca_e_texto_em_volta(self):
        r = explicar_ia.ler_resposta('Claro!\n```json\n[{"i": 1, "t": "Soma dois números."}, {"i": 2, "t": "Abre o arquivo."}]\n```', 2)
        self.assertEqual(r, {1: "Soma dois números.", 2: "Abre o arquivo."})

    def test_numero_fora_do_lote_e_texto_vazio_sao_ignorados(self):
        r = explicar_ia.ler_resposta('[{"i": 1, "t": "ok"}, {"i": 9, "t": "fora"}, {"i": 2, "t": "  "}, {"i": 3}]', 3)
        self.assertEqual(r, {1: "ok"})

    def test_json_quebrado_aproveita_os_objetos_inteiros(self):
        r = explicar_ia.ler_resposta('[{"i": 1, "t": "Primeira."}, {"i": 2, "t": "Segunda."}, {"i": 3, "t": "cortada no mei', 3)
        self.assertEqual(r, {1: "Primeira.", 2: "Segunda."})

    def test_lixo_nao_levanta_erro(self):
        for lixo in ("", None, "não sei", "{", "[1, 2, 3]", "[[[", '{"x": 1}'):
            self.assertEqual(explicar_ia.ler_resposta(lixo, 3), {})

    def test_frase_com_segredo_e_mascarada_e_cortada(self):
        r = explicar_ia.ler_resposta(json.dumps([{"i": 1, "t": f"Usa a chave {SEGREDO_NO_CODIGO} para entrar. " + "palavra " * 80}]), 1)
        self.assertNotIn(SEGREDO_NO_CODIGO, r[1])
        self.assertLessEqual(len(r[1]), explicar_ia.MAX_TEXTO + 1)


class TesteCandidatos(ComProjeto, unittest.TestCase):
    def setUp(self):
        self.montar()
        self.slug_ = self.slug

    def tearDown(self):
        self.desmontar_mundo()

    def test_pula_sensiveis_e_quem_ja_tem_texto(self):
        cands, cont = explicar_ia.candidatos(self.slug, self.caminho)
        ids = {c["id"] for c in cands}
        self.assertNotIn("env", ids)
        self.assertNotIn("chave", ids)
        self.assertNotIn("f1", ids)            # tem rationale
        self.assertNotIn("app", ids)           # arquivo com cabeçalho (docstring)
        self.assertIn("util", ids)             # arquivo sem cabeçalho
        self.assertIn("ajuda", ids)
        self.assertEqual(cont["sensiveis"], 2)
        self.assertEqual(cont["novas"], len(cands))

    def test_mais_ligado_vem_primeiro(self):
        cands, _ = explicar_ia.candidatos(self.slug, self.caminho)
        self.assertEqual(explicar_ia.selecionar(cands, 3)[0]["id"], "f0")

    def test_trecho_tem_so_o_ponto_e_sem_segredo(self):
        cands, _ = explicar_ia.candidatos(self.slug, self.caminho)
        c = {x["id"]: x for x in cands}
        self.assertIn("def f0(x):", c["f0"]["trecho"])
        self.assertNotIn("def f1(x):", c["f0"]["trecho"])          # parou antes do próximo ponto
        self.assertNotIn(SEGREDO_NO_CODIGO, c["usa_chave"]["trecho"])
        self.assertLessEqual(len(c["usa_chave"]["trecho"]), explicar_ia.MAX_TRECHO + 1)

    def test_sem_graph_json_devolve_vazio(self):
        cands, cont = explicar_ia.candidatos(self.slug, str(amb.BASE / "mundo" / "nao-existe"))
        self.assertEqual((cands, cont["pontos"]), ([], 0))


class TesteRodada(ComProjeto, unittest.TestCase):
    def setUp(self):
        self.montar()

    def tearDown(self):
        self.desmontar_mundo()

    def test_lotes_de_20_e_cache(self):
        total = len([c for c in explicar_ia.candidatos(self.slug, self.caminho)[0]])
        res = explicar_ia.rodar(self.slug, self.caminho, 45, self.chamador_gravando())
        self.assertEqual((res["pedidos"], res["lotes"], res["explicados"], res["falhas"]), (45, 3, 45, 0))
        self.assertEqual([p.count("### ") for p in self.prompts], [20, 20, 5])
        self.assertEqual(res["tokens_entrada"], 300)
        cache = explicar_ia.ler_cache(self.slug)
        self.assertEqual(len(cache), 45)
        self.assertEqual(cache["f0"]["t"], "Faz f0().")
        self.assertTrue(cache["f0"]["h"])
        self.assertTrue(explicar_ia.arquivo_cache(self.slug).is_file())
        self.assertTrue(str(explicar_ia.arquivo_cache(self.slug)).startswith(str(config.CASA)))
        self.assertGreater(total, 45)

    def test_nenhum_lote_leva_segredo_nem_conteudo_de_arquivo_sensivel(self):
        explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        todo = "\n".join(self.prompts)
        self.assertIn("usa_chave()", todo)                      # o ponto foi explicado...
        self.assertNotIn(SEGREDO_NO_CODIGO, todo)               # ...mas sem a chave
        self.assertNotIn(SEGREDO_DO_ENV, todo)
        self.assertNotIn("DB_PASSWORD", todo)
        self.assertNotIn("segredos.json", todo)
        self.assertNotIn(".env", todo)
        self.assertNotIn("Programa de teste", todo)             # cabeçalho do arquivo (já é texto próprio) nem vai
        self.assertNotIn(SEGREDO_NO_CODIGO, json.dumps(armazem.ler_json(explicar_ia.arquivo_cache(self.slug), {})))

    def test_retoma_de_onde_parou(self):
        parar = threading.Event()

        def para_no_primeiro(sistema, prompt):
            r = falso_ok(sistema, prompt)
            parar.set()
            return r
        res = explicar_ia.rodar(self.slug, self.caminho, 45, para_no_primeiro, parar)
        self.assertTrue(res["parado"])
        self.assertEqual((res["lotes_feitos"], res["explicados"]), (1, 20))
        self.assertEqual(len(explicar_ia.ler_cache(self.slug)), 20)
        ja = set(explicar_ia.ler_cache(self.slug))
        faltam = len(explicar_ia.candidatos(self.slug, self.caminho)[0]) - 20
        res2 = explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        self.assertEqual((res2["pedidos"], res2["explicados"]), (faltam, faltam))     # só os que faltam: os 20 de antes não voltam
        self.assertEqual(len(explicar_ia.ler_cache(self.slug)), 20 + faltam)
        pedidos = "\n".join(self.prompts)
        for nid in ja:
            self.assertNotIn(f"nome: {nid}()\n", pedidos)

    def test_segunda_rodada_completa_nao_chama_a_ia(self):
        explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        chamadas = len(self.prompts)
        res = explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        self.assertEqual((res["pedidos"], res["lotes"]), (0, 0))
        self.assertEqual(len(self.prompts), chamadas)

    def test_codigo_mudou_fica_desatualizada_e_volta_a_ser_pedida(self):
        explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        app = self.real / "app.py"
        app.write_text(app.read_text(encoding="utf-8").replace("return x + 5\n", "return x * 5000\n"), encoding="utf-8")
        cands, cont = explicar_ia.candidatos(self.slug, self.caminho)
        estados = {c["id"]: c["estado"] for c in cands}
        self.assertEqual(estados["f5"], "desatualizada")
        self.assertEqual(estados["f6"], "ok")
        self.assertEqual(cont["desatualizadas"], 1)
        self.prompts.clear()
        res = explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        self.assertEqual(res["pedidos"], 1)
        self.assertIn("nome: f5()", self.prompts[0])

    def test_falhas_seguidas_param_a_rodada_e_nao_gravam_nada(self):
        def quebra(sistema, prompt):
            self.prompts.append(prompt)
            raise RuntimeError(f"caiu a conexão com {SEGREDO_NO_CODIGO}")
        res = explicar_ia.rodar(self.slug, self.caminho, 100, quebra)
        self.assertEqual(len(self.prompts), explicar_ia.FALHAS_SEGUIDAS_MAX)       # não insiste em loop
        self.assertEqual((res["explicados"], res["falhas"]), (0, explicar_ia.FALHAS_SEGUIDAS_MAX))
        self.assertNotIn(SEGREDO_NO_CODIGO, res["erro"])
        self.assertEqual(explicar_ia.ler_cache(self.slug), {})

    def test_json_quebrado_da_ia_e_tolerado(self):
        def meio_quebrado(sistema, prompt):
            texto, uso = falso_ok(sistema, prompt)
            return texto[:len(texto) // 2], uso                                    # corta no meio
        res = explicar_ia.rodar(self.slug, self.caminho, 20, meio_quebrado)
        self.assertGreater(res["explicados"], 0)
        self.assertLess(res["explicados"], 20)
        self.assertEqual(res["explicados"] + res["sem_resposta"], 20)
        self.assertEqual(len(explicar_ia.ler_cache(self.slug)), res["explicados"])

    def test_resposta_so_lixo_nao_derruba(self):
        res = explicar_ia.rodar(self.slug, self.caminho, 20, lambda s, p: ("desculpe, não consigo", {}))
        self.assertEqual((res["explicados"], res["falhas"]), (0, 1))
        self.assertEqual(explicar_ia.ler_cache(self.slug), {})

    def test_cache_quebrado_e_ignorado(self):
        explicar_ia.arquivo_cache(self.slug).parent.mkdir(parents=True, exist_ok=True)
        explicar_ia.arquivo_cache(self.slug).write_text("{ isto nao e json", encoding="utf-8")
        self.assertEqual(explicar_ia.ler_cache(self.slug), {})
        res = explicar_ia.rodar(self.slug, self.caminho, 5, self.chamador_gravando())
        self.assertEqual(res["explicados"], 5)

    def test_estimativa_nao_chama_nada(self):
        with mock.patch.object(explicar_ia, "chamar_claude", side_effect=AssertionError("não pode chamar")):
            e = explicar_ia.estimar(self.slug, self.caminho, 200)
        self.assertEqual((e["nesta_rodada"], e["lotes"]), (min(200, e["faltam"]), -(-min(200, e["faltam"]) // 20)))
        self.assertGreater(e["tokens_total"], 0)
        self.assertEqual(e["pulados_sensiveis"], 2)
        self.assertEqual(explicar_ia.ler_cache(self.slug), {})

    def test_limite_e_respeitado(self):
        res = explicar_ia.rodar(self.slug, self.caminho, 7, self.chamador_gravando())
        self.assertEqual((res["pedidos"], res["explicados"]), (7, 7))


class TesteChamadas(unittest.TestCase):
    def test_claude_sem_ferramentas_sem_sessao_e_sem_chave_de_api(self):
        visto = {}

        def executar(argv, **kw):
            visto.update(argv=argv, **kw)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"type": "result", "is_error": False, "result": '[{"i":1,"t":"ok"}]',
                                                                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 7}}), "")
        with mock.patch.object(explicar_ia, "achar_claude", return_value="claude-falso"), mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-nao-pode-ir"}):
            texto, uso = explicar_ia.chamar_claude("SIS", "PEDIDO", executar=executar)
        argv = visto["argv"]
        self.assertEqual(argv[0], "claude-falso")
        self.assertIsInstance(argv, list)                                       # lista de argumentos: sem shell
        self.assertNotIn("shell", visto)
        self.assertEqual(argv[argv.index("--tools") + 1], "")                    # nenhuma ferramenta
        for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(visto["input"], "PEDIDO")
        self.assertEqual(visto["timeout"], explicar_ia.TEMPO_CHAMADA)
        self.assertNotIn("ANTHROPIC_API_KEY", visto["env"])
        self.assertEqual(visto["creationflags"], explicar_ia.SEM_JANELA)
        self.assertTrue(str(visto["cwd"]).startswith(str(config.CASA)))          # pasta neutra, nunca o projeto
        self.assertEqual((texto, uso), ('[{"i":1,"t":"ok"}]', {"entrada": 15, "saida": 7}))

    def test_erros_do_claude_viram_mensagem_curta(self):
        with mock.patch.object(explicar_ia, "achar_claude", return_value="c"):
            for retorno in (subprocess.CompletedProcess([], 1, "", "falhou feio"),
                            subprocess.CompletedProcess([], 0, "não é json", ""),
                            subprocess.CompletedProcess([], 0, json.dumps({"is_error": True, "result": "limite de uso"}), "")):
                with self.assertRaises(RuntimeError):
                    explicar_ia.chamar_claude("s", "p", executar=lambda *a, _r=retorno, **k: _r)

            def estoura(*a, **k):
                raise subprocess.TimeoutExpired("claude", 1)
            with self.assertRaisesRegex(RuntimeError, "tempo limite"):
                explicar_ia.chamar_claude("s", "p", executar=estoura)

    def test_trava_nunca_roda_o_claude_de_verdade_em_teste_ou_sem_efeitos(self):
        falso = mock.Mock(side_effect=AssertionError("rodou o claude de verdade"))
        for env in ({}, {"CEREBRO_TESTE_HOME": "", "CEREBRO_SEM_EFEITOS": "1"}):
            with mock.patch.object(explicar_ia, "achar_claude", return_value="claude-falso"), \
                    mock.patch.object(subprocess, "run", falso), mock.patch.dict("os.environ", env):
                with self.assertRaisesRegex(RuntimeError, "bloquead"):
                    explicar_ia.chamar_claude("s", "p")
        falso.assert_not_called()

    def test_sem_claude_instalado(self):
        with mock.patch.object(explicar_ia, "achar_claude", return_value=None), self.assertRaisesRegex(RuntimeError, "claude"):
            explicar_ia.chamar_claude("s", "p")

    def test_api_usa_haiku_e_a_chave(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"content": [{"type": "text", "text": "[]"}], "usage": {"input_tokens": 4, "output_tokens": 2}}).encode()
        pedido = {}

        def abrir(req, timeout):
            pedido.update(url=req.full_url, corpo=json.loads(req.data), chave=req.get_header("X-api-key"), timeout=timeout)
            return Resp()
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "chave-de-teste"}):
            texto, uso = explicar_ia.chamar_api("s", "p", abrir=abrir)
        self.assertEqual(pedido["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(pedido["corpo"]["model"], "claude-haiku-5-5")
        self.assertEqual(pedido["chave"], "chave-de-teste")
        self.assertEqual(uso, {"entrada": 4, "saida": 2})
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                explicar_ia.chamar_api("s", "p")

    def test_via_invalida(self):
        with self.assertRaises(ValueError):
            explicar_ia.chamador("outra")


class TesteSegundoPlano(ComProjeto, unittest.TestCase):
    def setUp(self):
        self.montar()

    def tearDown(self):
        self.desmontar_mundo()

    def test_iniciar_estado_e_regerar_no_fim(self):
        refeito = []
        est = explicar_ia.iniciar(self.slug, self.caminho, 25, "claude", self.chamador_gravando(), lambda s, c: refeito.append((s, c)))
        self.assertTrue(est["rodando"] or est["terminou_em"])
        explicar_ia.esperar(self.slug)
        est = explicar_ia.estado(self.slug)
        self.assertFalse(est["rodando"])
        self.assertEqual(est["resumo"]["explicados"], 25)
        self.assertEqual(refeito, [(self.slug, self.caminho)])

    def test_nao_deixa_duas_rodadas_juntas_e_pode_parar(self):
        solta, entrou = threading.Event(), threading.Event()

        def devagar(sistema, prompt):
            entrou.set()
            solta.wait(10)
            return falso_ok(sistema, prompt)
        explicar_ia.iniciar(self.slug, self.caminho, 100, "claude", devagar)
        self.assertTrue(entrou.wait(10))
        with self.assertRaisesRegex(ValueError, "já existe"):
            explicar_ia.iniciar(self.slug, self.caminho, 10, "claude", falso_ok)
        self.assertTrue(explicar_ia.parar(self.slug))
        self.assertTrue(explicar_ia.estado(self.slug)["parando"])
        solta.set()
        explicar_ia.esperar(self.slug)
        est = explicar_ia.estado(self.slug)
        self.assertFalse(est["rodando"])
        self.assertTrue(est["resumo"]["parado"])
        self.assertEqual(est["resumo"]["lotes_feitos"], 1)                          # terminou o lote em andamento e parou
        self.assertFalse(explicar_ia.parar(self.slug))

    def test_sem_claude_nao_inicia(self):
        with mock.patch.object(explicar_ia, "achar_claude", return_value=None), self.assertRaisesRegex(ValueError, "claude"):
            explicar_ia.iniciar(self.slug, self.caminho, 10, "claude")


class TesteGerador(ComProjeto, unittest.TestCase):
    def setUp(self):
        self.montar(6)
        spec = importlib.util.spec_from_file_location("gerar_mapa_ia", amb.RAIZ / "mapa" / "gerar.py")
        self.gerar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gerar)

    def tearDown(self):
        self.desmontar_mundo()

    def _processar(self):
        return self.gerar.processar(self.real / "graphify-out", self.real, self.slug)[0]

    def test_sem_arquivo_de_explicacoes_o_mapa_e_o_de_sempre(self):
        d = self._processar()
        self.assertEqual(d["ia"], {})
        self.assertEqual(d["meta"]["totais"]["explicadosIA"], 0)
        self.assertNotIn("Faz f0().", json.dumps(d["expl"]))

    def test_explicacao_da_ia_entra_no_painel_marcada(self):
        explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        d = self._processar()
        nomes = d["nos"]["n"]
        i = nomes.index("f0()")
        self.assertEqual(d["expl"][str(i)], "Faz f0().")
        self.assertEqual(d["ia"][str(i)], 0)
        i1 = nomes.index("f1()")                      # f1 tem texto próprio: a IA nunca sobrescreve
        self.assertNotIn("Faz f1().", d["expl"].get(str(i1), ""))
        self.assertNotIn(str(i1), d["ia"])
        self.assertGreater(d["meta"]["totais"]["explicadosIA"], 0)

    def test_desatualizada_aparece_marcada(self):
        explicar_ia.rodar(self.slug, self.caminho, 500, self.chamador_gravando())
        app = self.real / "app.py"
        app.write_text(app.read_text(encoding="utf-8").replace("return x + 2\n", "return x - 2000\n"), encoding="utf-8")
        d = self._processar()
        i = d["nos"]["n"].index("f2()")
        self.assertEqual(d["ia"][str(i)], 1)
        self.assertEqual(d["expl"][str(i)], "Faz f2().")

    def test_cache_quebrado_nao_derruba_o_gerador(self):
        explicar_ia.arquivo_cache(self.slug).parent.mkdir(parents=True, exist_ok=True)
        explicar_ia.arquivo_cache(self.slug).write_text("[[[", encoding="utf-8")
        self.assertEqual(self._processar()["ia"], {})


class TesteRotasECli(ComProjeto, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.montar()
        import socket
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.porta = sk.getsockname()[1]
        self.app = servidor.criar_app(self.porta, token="t" * 43)
        self.srv = TestServer(self.app, port=self.porta)
        await self.srv.start_server()
        self.base = f"http://127.0.0.1:{self.porta}"
        self.http = ClientSession(cookie_jar=CookieJar(unsafe=True))
        self.url = f"{self.base}/api/p/{self.slug}/explicar"
        self.json_h = {"Origin": self.base, "Content-Type": "application/json"}

    async def asyncTearDown(self):
        await self.http.close()
        await self.srv.close()
        self.desmontar_mundo()

    async def entrar(self):
        await self.http.get(f"{self.base}/?t={'t' * 43}", allow_redirects=False)

    async def test_exige_cookie_e_origin(self):
        r = await self.http.get(self.url)
        self.assertEqual(r.status, 401)
        await self.entrar()
        r = await self.http.post(self.url + "/rodar", data="{}", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)                                            # POST sem Origin
        r = await self.http.post(self.url + "/rodar", data="{}", headers={"Origin": self.base})
        self.assertEqual(r.status, 415)                                            # sem JSON

    async def test_estimativa_e_so_leitura(self):
        await self.entrar()
        with mock.patch.object(explicar_ia, "chamar_claude", side_effect=AssertionError("não pode chamar")):
            r = await self.http.get(self.url + "?limite=30")
            d = await r.json()
        self.assertEqual(r.status, 200)
        self.assertEqual((d["estimativa"]["nesta_rodada"], d["estimativa"]["lotes"]), (30, 2))
        self.assertEqual(d["estimativa"]["rotulo"], "explicação automática (IA)")
        self.assertFalse(d["rodada"]["rodando"])
        r = await self.http.get(self.url + "?via=outra")
        self.assertEqual(r.status, 400)

    async def test_rodar_ate_o_fim_e_parar(self):
        await self.entrar()
        refeito = []
        with mock.patch.object(explicar_ia, "achar_claude", return_value="c"), \
                mock.patch.object(explicar_ia, "chamar_claude", self.chamador_gravando()), \
                mock.patch.object(mapa_auto, "gerar_agora", lambda s, c: refeito.append(s) or (True, "")):
            r = await self.http.post(self.url + "/rodar", json={"limite": 25, "via": "claude"}, headers={"Origin": self.base})
            self.assertEqual(r.status, 200)
            explicar_ia.esperar(self.slug)
            d = await (await self.http.get(self.url + "/estado")).json()
        self.assertFalse(d["rodada"]["rodando"])
        self.assertEqual(d["rodada"]["resumo"]["explicados"], 25)
        self.assertEqual(refeito, [self.slug])
        r = await self.http.post(self.url + "/parar", json={}, headers={"Origin": self.base})
        self.assertEqual((await r.json())["ok"], False)                           # nada rodando

    async def test_rodar_recusa_limite_louco_e_via_invalida(self):
        await self.entrar()
        r = await self.http.post(self.url + "/rodar", json={"via": "xyz"}, headers={"Origin": self.base})
        self.assertEqual(r.status, 400)
        with mock.patch.object(explicar_ia, "achar_claude", return_value=None):
            r = await self.http.post(self.url + "/rodar", json={"limite": 10**9}, headers={"Origin": self.base})
            self.assertEqual(r.status, 409)                                        # sem claude: explica em vez de quebrar

    async def test_projeto_sem_mapa(self):
        sem = amb.BASE / "mundo" / "Desktop" / "SemMapa"
        sem.mkdir(parents=True)
        pasta_claude = config.PROJETOS_CLAUDE / projetos.codificar(sem)
        pasta_claude.mkdir(parents=True)
        (pasta_claude / "s.jsonl").write_text(json.dumps({"type": "user", "cwd": str(sem)}) + "\n", encoding="utf-8")
        projetos.descobrir(forcar=True)
        await self.entrar()
        r = await self.http.get(f"{self.base}/api/p/{projetos.codificar(sem)}/explicar")
        self.assertEqual(r.status, 409)

    def test_cli_estimar_nao_gasta_e_rodar_grava(self):
        import cerebro_cli
        with mock.patch.object(explicar_ia, "chamar_claude", side_effect=AssertionError("não pode chamar")):
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                self.assertEqual(cerebro_cli.main(["explicar", "ProjIA", "--estimar", "--limite", "10"]), 0)
        self.assertIn("Nada foi gasto", saida.getvalue())
        self.assertEqual(explicar_ia.ler_cache(self.slug), {})
        saida = io.StringIO()
        with mock.patch.object(explicar_ia, "achar_claude", return_value="c"), \
                mock.patch.object(explicar_ia, "chamar_claude", self.chamador_gravando()), \
                mock.patch.object(mapa_auto, "gerar_agora", return_value=(True, "")), contextlib.redirect_stdout(saida):
            self.assertEqual(cerebro_cli.main(["explicar", "ProjIA", "--rodar", "--limite", "10"]), 0)
        self.assertIn("10 pontos explicados", saida.getvalue())
        self.assertEqual(len(explicar_ia.ler_cache(self.slug)), 10)


if __name__ == "__main__":
    unittest.main()
