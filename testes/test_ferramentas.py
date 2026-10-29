"""Aba Ferramentas: detecção só de leitura, lista fechada de comandos, execução com tempo limite, saída mascarada e histórico."""
import time
import unittest

from testes import _ambiente as amb
from cerebro import config, ferramentas
from testes.test_servidor import Base

CATALOGO_ESPERADO = {"ruff", "eslint", "cargo", "gitleaks", "semgrep", "pip-audit", "cargo-deny", "osv-scanner", "coverage", "lighthouse"}


def esperar_fim(slug, limite=30):
    fim = time.time() + limite
    while time.time() < fim:
        if ferramentas.estado_execucoes(slug)["rodando"] is None:
            return ferramentas.estado_execucoes(slug)["historico"][0]
        time.sleep(0.1)
    raise AssertionError("o comando não terminou a tempo")


class TesteDeteccao(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()

    def tearDown(self):
        self.desmontar_mundo()

    def test_catalogo_tem_as_dez_ferramentas_e_mostra_como_instalar(self):
        det = ferramentas.detectar(str(self.real), forcar=True)
        self.assertEqual({d["id"] for d in det}, CATALOGO_ESPERADO)
        for d in det:
            self.assertTrue(d["o_que"] and d["instalar"], d["id"])
            self.assertIn(d["instalada"], (True, False))

    def test_relevancia_pelo_tipo_do_projeto(self):
        (self.real / "app.py").write_text("x = 1\n", encoding="utf-8")
        det = {d["id"]: d for d in ferramentas.detectar(str(self.real), forcar=True)}
        self.assertTrue(det["ruff"]["relevante"])
        self.assertFalse(det["cargo-deny"]["relevante"])
        self.assertTrue(det["gitleaks"]["relevante"])               # "sempre"

    def test_detectar_nao_cria_nada_na_pasta_do_projeto(self):
        antes = sorted(p.name for p in self.real.iterdir())
        ferramentas.detectar(str(self.real), forcar=True)
        self.assertEqual(sorted(p.name for p in self.real.iterdir()), antes)

    def test_estado_do_graphify(self):
        g = ferramentas.estado_graphify(str(self.real), self.slug)
        self.assertFalse(g["mapa"])
        (self.real / "graphify-out").mkdir()
        (self.real / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        g = ferramentas.estado_graphify(str(self.real), self.slug)
        self.assertTrue(g["mapa"])
        self.assertIsNotNone(g["graph_em"])


class TesteListaFechada(unittest.TestCase):
    def test_comandos_invalidos_sao_descartados(self):
        cfg = {"comandos": {"p": [
            {"id": "bom", "nome": "Bom", "argv": ["{python}", "a.py"], "timeout": 30},
            {"id": "MAIUSCULA", "argv": ["x"]},
            {"id": "string", "argv": "python a.py"},                     # string = shell: recusado
            {"id": "vazio", "argv": []},
            {"id": "nulo", "argv": ["a\x00b"]},
            {"id": "longo", "argv": ["x"] * 13},
            {"id": "tempo", "argv": ["x"], "timeout": 99999},
            "lixo", None]}}
        saida = {c["id"]: c for c in ferramentas.comandos_do_projeto(cfg, "p")}
        self.assertEqual(set(saida), {"bom", "tempo"})
        self.assertEqual(saida["tempo"]["timeout"], 600)             # fora da faixa volta ao padrão
        self.assertEqual(ferramentas.comandos_do_projeto(cfg, "outro"), [])

    def test_nenhum_comando_vem_pronto(self):
        self.assertEqual(config.COMANDOS_PADRAO, {})
        self.assertEqual(ferramentas.comandos_do_projeto(config.ler_config(), amb.SLUG_EXEMPLO), [])

    def test_script_fora_do_projeto_ou_inexistente_e_recusado(self):
        raiz = amb.BASE / "projeto_fake"
        raiz.mkdir(exist_ok=True)
        with self.assertRaises(ValueError):
            ferramentas._resolver_argv(["{python}", "../fora.py"], raiz)
        with self.assertRaises(ValueError):
            ferramentas._resolver_argv(["{python}", "nao_existe.py"], raiz)


class TesteExecucao(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        (self.real / "ok.py").write_text("print('OK  etapa um')\nprint('senha=abc12345xyz')\nprint('FALHA etapa dois')\n", encoding="utf-8")
        (self.real / "quebra.py").write_text("import sys\nprint('deu ruim')\nsys.exit(3)\n", encoding="utf-8")
        (self.real / "dorme.py").write_text("import time\nprint('comecou', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        cmds = [{"id": "ok", "nome": "Ok", "ferramenta": "ruff", "argv": ["{python}", "ok.py"], "timeout": 30},
                {"id": "quebra", "nome": "Quebra", "argv": ["{python}", "quebra.py"], "timeout": 30},
                {"id": "dorme", "nome": "Dorme", "argv": ["{python}", "dorme.py"], "timeout": 5}]
        config.atualizar_config(lambda c: c["comandos"].__setitem__(self.slug, cmds))
        self.cfg = config.ler_config()

    def tearDown(self):
        ferramentas.parar_todos()
        self.desmontar_mundo()

    def test_comando_fora_da_lista_nao_roda(self):
        with self.assertRaises(ValueError):
            ferramentas.rodar(self.slug, str(self.real), self.cfg, "rm-rf")
        self.assertEqual(ferramentas.estado_execucoes(self.slug)["historico"], [])

    def test_roda_guarda_saida_mascarada_e_resume(self):
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "ok")
        reg = esperar_fim(self.slug)
        self.assertEqual(reg["resultado"], "ok")
        self.assertEqual(reg["codigo"], 0)
        self.assertGreaterEqual(reg["duracao"], 0)
        self.assertIn("1 etapa(s) OK, 1 com falha", reg["resumo"])
        saida = ferramentas.saida_da_execucao(self.slug, reg["id"])
        self.assertIn("etapa um", saida)
        self.assertNotIn("abc12345xyz", saida)                       # segredo mascarado

    def test_codigo_de_saida_diferente_de_zero_vira_falha(self):
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "quebra")
        reg = esperar_fim(self.slug)
        self.assertEqual((reg["resultado"], reg["codigo"]), ("falha", 3))
        self.assertEqual(reg["resumo"], "deu ruim")

    def test_tempo_limite_interrompe(self):
        t0 = time.time()
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "dorme")
        reg = esperar_fim(self.slug)
        self.assertEqual(reg["resultado"], "tempo")
        self.assertLess(time.time() - t0, 25)
        self.assertIn("tempo limite", reg["resumo"])

    def test_um_comando_por_projeto_de_cada_vez(self):
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "dorme")
        with self.assertRaises(ValueError):
            ferramentas.rodar(self.slug, str(self.real), self.cfg, "ok")
        ferramentas.parar_todos()
        esperar_fim(self.slug)

    def test_ultima_execucao_aparece_no_cartao(self):
        ferramentas.rodar(self.slug, str(self.real), self.cfg, "ok")
        esperar_fim(self.slug)
        m = ferramentas.montar(self.slug, str(self.real), self.cfg, forcar=True)
        ruff = next(c for c in m["cartoes"] if c["id"] == "ruff")
        self.assertEqual(ruff["ultima"]["resultado"], "ok")
        self.assertEqual([c["id"] for c in ruff["comandos"]], ["ok"])
        self.assertNotIn("argv", m["comandos"][0])                   # a página nunca recebe os argumentos

    def test_historico_guarda_so_as_20_ultimas_e_apaga_saidas_velhas(self):
        for i in range(23):
            reg = {"id": f"20260101-0000{i:02d}-ok", "comando": "ok", "nome": "Ok", "ferramenta": "ruff", "inicio": i, "resultado": "ok"}
            (ferramentas._pasta_exec(self.slug) / "saidas" / f"{reg['id']}.txt").write_text("x", encoding="utf-8")
            ferramentas._guardar_registro(self.slug, reg)
        h = ferramentas.estado_execucoes(self.slug)["historico"]
        self.assertEqual(len(h), ferramentas.MAX_EXECUCOES)
        self.assertEqual(h[0]["id"], "20260101-000022-ok")
        self.assertIsNone(ferramentas.saida_da_execucao(self.slug, "20260101-000000-ok"))
        self.assertEqual(ferramentas.saida_da_execucao(self.slug, "20260101-000022-ok"), "x")

    def test_saida_so_aceita_id_de_execucao(self):
        for ruim in ("../../token", "..\\x", "", None, "20260101-000000-ok/../../x"):
            self.assertIsNone(ferramentas.saida_da_execucao(self.slug, ruim))


class TesteRotasFerramentas(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        (self.real / "ok.py").write_text("print('feito')\n", encoding="utf-8")
        config.atualizar_config(lambda c: c["comandos"].__setitem__(
            self.slug, [{"id": "ok", "nome": "Ok", "ferramenta": "ruff", "argv": ["{python}", "ok.py"], "timeout": 30}]))

    async def asyncTearDown(self):
        ferramentas.parar_todos()
        await super().asyncTearDown()

    async def test_so_o_id_vale_e_comando_livre_e_recusado(self):
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/ferramentas/rodar", {"id": "python -c print(1)"})
        self.assertEqual(r.status, 409)
        r = await self.post(f"/api/p/{self.slug}/ferramentas/rodar", {"argv": ["calc.exe"]})
        self.assertEqual(r.status, 400)
        r = await self.post(f"/api/p/{self.slug}/ferramentas/rodar", {"id": "ok"})
        self.assertEqual(r.status, 200)
        esperar_fim(self.slug)
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas/execucoes")).json()
        self.assertEqual(d["historico"][0]["resultado"], "ok")
        s = await (await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas/saida", params={"id": d["historico"][0]["id"]})).json()
        self.assertIn("feito", s["texto"])

    async def test_config_nao_aceita_comandos_vindos_da_pagina(self):
        await self.entrar()
        antes = config.ler_config()["comandos"]
        await self.post("/api/config", {"comandos": {self.slug: [{"id": "mau", "argv": ["calc.exe"]}]}})
        self.assertEqual(config.ler_config()["comandos"], antes)

    async def test_rodar_exige_origin(self):
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/ferramentas/rodar", {"id": "ok"}, origem=False)
        self.assertEqual(r.status, 403)


if __name__ == "__main__":
    unittest.main()
