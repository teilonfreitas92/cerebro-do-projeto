"""Autoevolução (Analisar agora), propostas e tarefas, rotinas com o servidor no ar, e o inventário (instalação adaptativa)."""
import subprocess
import time
import unittest

from testes import _ambiente as amb
from cerebro import analise, config, inventario, propostas, rotinas
from testes.test_servidor import Base


def git(raiz, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(raiz), capture_output=True, check=True)


class TesteAnalise(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        git(self.real, "init", "-q")
        (self.real / "grande.py").write_text("x = 1\n" * 1600, encoding="utf-8")
        (self.real / "pequeno.py").write_text("y = 2\n", encoding="utf-8")
        git(self.real, "add", "-A")
        git(self.real, "commit", "-qm", "inicio")
        self.cfg = config.ler_config()

    def tearDown(self):
        self.desmontar_mundo()

    def test_relatorio_tem_todas_as_partes_sem_ia(self):
        out = analise.executar(self.slug, self.cfg)
        rel = out["relatorio"]
        for chave in ("git", "maiores", "cresceram", "mapa", "memoria", "contexto_fixo", "custos", "revisoes", "ferramentas", "avisos"):
            self.assertIn(chave, rel)
        self.assertEqual(rel["maiores"][0]["caminho"], "grande.py")
        self.assertEqual(rel["maiores"][0]["linhas"], 1600)
        self.assertIsNotNone(rel["git"]["commits_30d"])

    def test_propostas_tem_motivo_esforco_e_risco(self):
        out = analise.executar(self.slug, self.cfg)
        self.assertTrue(out["propostas"])
        for p in out["propostas"]:
            self.assertTrue(p["motivo"])
            self.assertIn(p["esforco"], ("P", "M", "G"))
            self.assertIn(p["risco"], ("baixo", "médio", "alto"))
            self.assertEqual(p["estado"], "nova")
        self.assertTrue(any("1500 linhas" in p["titulo"] for p in out["propostas"]))

    def test_repetir_a_analise_nao_duplica_e_guarda_historico(self):
        a = analise.executar(self.slug, self.cfg)
        b = analise.executar(self.slug, self.cfg)
        self.assertEqual(len(a["propostas"]), len(b["propostas"]))
        self.assertEqual(b["resumo"]["novas"], 0)
        self.assertEqual(len(analise.ler(self.slug, self.cfg)["historico"]), 2)

    def test_problema_que_some_vira_obsoleta(self):
        analise.executar(self.slug, self.cfg)
        (self.real / "grande.py").write_text("x = 1\n", encoding="utf-8")
        out = analise.executar(self.slug, self.cfg)
        self.assertFalse(any("1500 linhas" in p["titulo"] for p in out["propostas"]))
        obsoletas = [p for p in propostas.listar(self.slug, incluir_obsoletas=True) if p["estado"] == "obsoleta"]
        self.assertTrue(any("1500 linhas" in p["titulo"] for p in obsoletas))

    def test_aprovar_vira_tarefa_para_o_gestor_e_descartar_nao(self):
        out = analise.executar(self.slug, self.cfg)
        a, b = out["propostas"][0], out["propostas"][1]
        propostas.decidir(self.slug, a["id"], True, nota="pode fazer")
        propostas.decidir(self.slug, b["id"], False)
        tarefas = propostas.tarefas(self.slug)
        self.assertEqual([t["proposta_id"] for t in tarefas], [a["id"]])
        self.assertEqual(tarefas[0]["estado"], "aberta")
        self.assertEqual(propostas.contagem(self.slug)["tarefas_abertas"], 1)
        propostas.concluir_tarefa(self.slug, tarefas[0]["id"], "feito")
        self.assertEqual(propostas.contagem(self.slug)["tarefas_abertas"], 0)
        propostas.reabrir(self.slug, b["id"])
        self.assertEqual(next(p for p in propostas.listar(self.slug) if p["id"] == b["id"])["estado"], "nova")
        with self.assertRaises(ValueError):
            propostas.decidir(self.slug, "naoexiste", True)

    def test_proposta_aprovada_continua_aprovada_na_proxima_analise(self):
        out = analise.executar(self.slug, self.cfg)
        pid = out["propostas"][0]["id"]
        propostas.decidir(self.slug, pid, True)
        analise.executar(self.slug, self.cfg)
        self.assertEqual(next(p for p in propostas.listar(self.slug) if p["id"] == pid)["estado"], "aprovada")

    def test_proposta_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            propostas.proposta("x", "y", "t", "m", esforco="Z")
        with self.assertRaises(ValueError):
            propostas.proposta("x", "y", "t", "m", risco="enorme")

    def test_analise_do_proprio_cerebro(self):
        out = analise.executar(propostas.ESCOPO_CEREBRO, self.cfg)
        self.assertIn("quando", out["relatorio"])
        self.assertEqual(analise.ler(propostas.ESCOPO_CEREBRO, self.cfg)["historico"][0]["id"], out["resumo"]["id"])

    def test_historico_limitado(self):
        antes = analise.MAX_ANALISES
        self.addCleanup(setattr, analise, "MAX_ANALISES", antes)
        analise.MAX_ANALISES = 3
        for i in range(6):
            analise.executar(self.slug, self.cfg, agora=1000.0 + i)
        self.assertEqual(len(analise.ler(self.slug, self.cfg)["historico"]), 3)

    def test_proxima_analise_vem_do_intervalo_configurado(self):
        self.assertIsNone(analise.ler(self.slug, self.cfg)["proxima_em"])
        analise.executar(self.slug, self.cfg, agora=1_000_000.0)
        d = analise.ler(self.slug, self.cfg)
        self.assertEqual(d["proxima_em"], 1_000_000.0 + d["intervalo_dias"] * 86400)

    def test_projeto_inexistente(self):
        with self.assertRaises(ValueError):
            analise.executar("nao-existe", self.cfg)


class TesteRotinas(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        rotinas._erro_em.clear()
        rotinas._ultimo_erro.clear()

    def tearDown(self):
        self.desmontar_mundo()

    def test_so_o_que_passou_do_prazo(self):
        cfg = config.ler_config()
        d = rotinas.devidos(cfg, agora=time.time())
        self.assertIn(("analise", self.slug), d)                    # nunca analisado
        self.assertIn(("analise", propostas.ESCOPO_CEREBRO), d)
        self.assertNotIn(("novidades", ""), d)                       # novidades automáticas vêm desligadas (consulta a internet)
        analise.executar(self.slug, cfg, agora=time.time())
        self.assertNotIn(("analise", self.slug), rotinas.devidos(cfg, agora=time.time() + 3600))
        self.assertIn(("analise", self.slug), rotinas.devidos(cfg, agora=time.time() + 8 * 86400))

    def test_desligar_a_analise_automatica(self):
        config.atualizar_config(lambda c: c["rotinas"].__setitem__("analise_automatica", False))
        self.assertEqual(rotinas.devidos(config.ler_config()), [])

    def test_tick_roda_uma_por_vez_e_erro_nao_derruba(self):
        feitos = []
        self.assertEqual(len(rotinas.tick(fazer_analise=feitos.append)), 1)
        self.assertEqual(len(feitos), 1)

        def quebra(slug):
            raise RuntimeError("falhou")

        rotinas._erro_em.clear()
        r = rotinas.tick(fazer_analise=quebra)
        self.assertTrue(r[0].endswith("(erro)"))
        self.assertTrue(rotinas.situacao()["erros"])


class TesteInventario(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.cfg = config.ler_config()

    def tearDown(self):
        self.desmontar_mundo()

    def inv(self):
        d = inventario.montar(self.slug, str(self.real), self.cfg)
        return {i["id"]: i for i in d["itens"]}, {p["id"]: p for p in d["plano"]}, d

    def test_projeto_vazio_propoe_criar_tudo(self):
        itens, plano, d = self.inv()
        self.assertFalse(itens["doc-CLAUDE.md"]["existe"])
        self.assertFalse(itens["testes"]["existe"])
        self.assertEqual(plano["instrucoes"]["estado"], "acrescentar")
        self.assertEqual(plano["agentes"]["estado"], "acrescentar")
        self.assertIn("Nada foi aplicado", d["nota"])

    def test_projeto_em_andamento_e_respeitado(self):
        (self.real / "CLAUDE.md").write_text("# regras\n", encoding="utf-8")
        (self.real / "AGENTS.md").write_text("# agentes\n", encoding="utf-8")
        (self.real / "docs").mkdir()
        (self.real / "docs" / "a.md").write_text("a", encoding="utf-8")
        (self.real / "testes").mkdir()
        (self.real / "testes" / "rodar_testes.py").write_text("", encoding="utf-8")
        (self.real / "testes" / "test_a.py").write_text("", encoding="utf-8")
        (self.real / ".github" / "workflows").mkdir(parents=True)
        (self.real / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
        (self.real / ".claude" / "agents").mkdir(parents=True)
        (self.real / ".claude" / "agents" / "revisor.md").write_text("---\nname: revisor\n---\n", encoding="utf-8")
        (self.real / ".claude" / "settings.json").write_text('{"hooks": {"PostToolUse": []}}', encoding="utf-8")
        (self.real / "graphify-out").mkdir()
        (self.real / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        itens, plano, _ = self.inv()
        for k in ("doc-CLAUDE.md", "doc-AGENTS.md", "docs", "testes", "ci", "agentes", "settings", "graphify"):
            self.assertTrue(itens[k]["existe"], k)
        self.assertIn("python testes/rodar_testes.py", itens["testes"]["detalhe"])
        self.assertEqual(plano["agentes"]["estado"], "ja_existe")      # agentes do projeto são mantidos
        self.assertEqual(plano["mapa"]["estado"], "ja_existe")
        self.assertEqual(plano["qualidade"]["estado"], "ja_existe")

    def test_plano_nao_aplica_nada_e_nao_escreve_no_projeto(self):
        antes = sorted(str(p.relative_to(self.real)) for p in self.real.rglob("*"))
        _, plano, _ = self.inv()
        self.assertTrue(all(p["aplicar"] is False for p in plano.values()))
        self.assertEqual(sorted(str(p.relative_to(self.real)) for p in self.real.rglob("*")), antes)

    def test_ganchos_do_git_sao_lidos_sem_alterar(self):
        git(self.real, "init", "-q")
        gancho = self.real / ".git" / "hooks" / "post-commit"
        gancho.write_text("#!/bin/sh\ngraphify update .\n", encoding="utf-8")
        antes = gancho.read_text(encoding="utf-8")
        itens, plano, _ = self.inv()
        self.assertTrue(itens["ganchos-git"]["existe"])
        self.assertEqual(plano["mapa-auto"]["estado"], "ja_existe")
        self.assertEqual(gancho.read_text(encoding="utf-8"), antes)


class TesteRotasAnalise(Base):
    async def test_analisar_aprovar_e_tarefa_pela_api(self):
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/analise", {})
        self.assertEqual(r.status, 200)
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/analise")).json()
        self.assertTrue(d["relatorio"])
        self.assertTrue(d["propostas"])
        pid = d["propostas"][0]["id"]
        r = await self.post(f"/api/p/{self.slug}/propostas/{pid}", {"acao": "aprovar", "nota": "ok"})
        self.assertEqual(r.status, 200)
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/analise")).json()
        self.assertEqual(len(d["tarefas"]), 1)
        r = await self.post(f"/api/p/{self.slug}/propostas/naoexiste", {"acao": "aprovar"})
        self.assertIn(r.status, (400, 404))

    async def test_inventario_pela_api(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/inventario")).json()
        self.assertTrue(d["itens"] and d["plano"])


if __name__ == "__main__":
    unittest.main()
