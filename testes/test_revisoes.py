"""Fila "a conferir", registro de decisões e a linha de comando do gestor."""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

import cerebro_cli
from testes import _ambiente as amb
from cerebro import config, decisoes, indice, revisoes


class TesteRevisoes(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.criar_subagente("a1b2c3d4e5", "Auditoria de login", modelo="claude-opus-5-5")
        self.criar_subagente("f6a7b8c9d0", "Buscar textos da documentação", modelo="claude-haiku-5-5")
        self.criar_subagente("0011223344", "Implementar tela nova", modelo="claude-sonnet-5-5")
        self.criar_subagente("9999999999", "Ainda trabalhando", terminou=False, idade_s=5)
        self.criar_subagente("8888888888", "Antigo de 30 dias", idade_s=30 * 86400)
        self.cfg = config.ler_config()

    def tearDown(self):
        self.desmontar_mundo()

    def test_so_terminados_da_gestora_entram_e_antigos_ficam_fora(self):
        f = revisoes.fila(self.slug, self.cfg)
        ids = {i["id"] for i in f["pendentes"]}
        self.assertEqual(ids, {"a1b2c3d4e5", "f6a7b8c9d0", "0011223344"})
        self.assertEqual(f["antigos"], 1)
        self.assertEqual(f["contadores"]["a_conferir"], 3)
        self.assertTrue(f["gestora"])

    def test_modelo_regra_e_parado(self):
        f = revisoes.fila(self.slug, self.cfg)
        por_id = {i["id"]: i for i in f["pendentes"]}
        self.assertEqual(por_id["a1b2c3d4e5"]["familia"], "opus")
        self.assertEqual(por_id["a1b2c3d4e5"]["regra"]["regra"], "critico")
        self.assertEqual(por_id["f6a7b8c9d0"]["regra"]["regra"], "mecanico")
        self.assertEqual(por_id["f6a7b8c9d0"]["regra"]["situacao"], "conforme")
        self.assertEqual(por_id["0011223344"]["regra"]["regra"], "codigo")
        self.assertTrue(por_id["a1b2c3d4e5"]["parado"] is False)       # terminou há 2 h, menos de 24 h

    def test_sem_gestora_fila_vazia(self):
        config.atualizar_config(lambda c: c["gestoras"].pop(self.slug))
        f = revisoes.fila(self.slug, config.ler_config())
        self.assertFalse(f["gestora"])
        self.assertEqual(f["pendentes"], [])
        self.assertEqual(revisoes.contagem(self.slug, config.ler_config())["a_conferir"], 0)

    def test_conferir_por_id_prefixo_e_descricao(self):
        it = revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "aprovado", "diff ok")
        self.assertEqual(it["resultado"], "aprovado")
        self.assertEqual(it["familia"], "opus")
        it = revisoes.conferir(self.slug, self.cfg, "f6a7b8", "corrigido")          # começo do id
        self.assertEqual(it["id"], "f6a7b8c9d0")
        it = revisoes.conferir(self.slug, self.cfg, "tela nova", "recusado", "não serviu")   # trecho da descrição
        self.assertEqual(it["id"], "0011223344")
        f = revisoes.fila(self.slug, self.cfg)
        self.assertEqual(f["pendentes"], [])
        self.assertEqual(f["contadores"]["conferidos"], 3)
        self.assertEqual((f["contadores"]["aprovados"], f["contadores"]["corrigidos"], f["contadores"]["recusados"]), (1, 1, 1))

    def test_referencia_ambigua_ou_inexistente_explica(self):
        with self.assertRaises(ValueError) as e:
            revisoes.conferir(self.slug, self.cfg, "a", "aprovado")                 # casa com várias descrições
        self.assertIn("use o id", str(e.exception))
        with self.assertRaises(ValueError):
            revisoes.conferir(self.slug, self.cfg, "nada-disso", "aprovado")
        with self.assertRaises(ValueError):
            revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "talvez")
        with self.assertRaises(ValueError):
            revisoes.conferir(self.slug, self.cfg, "", "aprovado")

    def test_reconferir_atualiza_e_guarda_historico(self):
        revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "recusado", "ruim")
        it = revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "corrigido", "refiz")
        self.assertEqual(it["resultado"], "corrigido")
        self.assertEqual(it["historico"][0]["resultado"], "recusado")

    def test_percentual_aprovado_de_primeira_por_modelo(self):
        for i in range(4):
            self.criar_subagente(f"h{i}h{i}h{i}h{i}", f"Buscar item {i}", modelo="claude-haiku-5-5")
        for i in range(3):
            revisoes.conferir(self.slug, self.cfg, f"h{i}h{i}h{i}h{i}", "aprovado")
        revisoes.conferir(self.slug, self.cfg, "h3h3h3h3", "corrigido")
        revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "recusado")
        por = {m["modelo"]: m for m in revisoes.fila(self.slug, self.cfg)["por_modelo"]}
        self.assertEqual(por["haiku"]["total"], 4)
        self.assertEqual(por["haiku"]["pct_primeira"], 75)
        self.assertEqual(por["opus"]["pct_primeira"], 0)

    def test_dispensar_antigos_nao_conta_nas_estatisticas(self):
        n = revisoes.dispensar_antigos(self.slug, self.cfg)
        self.assertEqual(n, 1)
        self.assertEqual(revisoes.dispensar_antigos(self.slug, self.cfg), 0)
        f = revisoes.fila(self.slug, self.cfg)
        self.assertEqual(f["antigos"], 0)
        self.assertEqual(f["contadores"]["conferidos"], 0)
        self.assertEqual(f["por_modelo"], [])

    def test_janela_vem_da_configuracao(self):
        config.atualizar_config(lambda c: c.__setitem__("revisao_dias", 60))
        f = revisoes.fila(self.slug, config.ler_config())
        self.assertIn("8888888888", {i["id"] for i in f["pendentes"]})

    def test_estado_do_subagente_aparece_em_agentes(self):
        from cerebro import agentes
        d = agentes.montar(self.slug, self.cfg["precos"], amb.GESTORA_ID, 24, True, self.cfg)
        subs = {s["id"]: s for s in d["sessoes"][0]["subagentes"]}
        self.assertEqual(subs["a1b2c3d4e5"]["conferencia"], "a_conferir")
        self.assertEqual(subs["a1b2c3d4e5"]["regra"]["regra"], "critico")
        revisoes.conferir(self.slug, self.cfg, "a1b2c3d4e5", "aprovado")
        d = agentes.montar(self.slug, self.cfg["precos"], amb.GESTORA_ID, 24, True, self.cfg)
        subs = {s["id"]: s for s in d["sessoes"][0]["subagentes"]}
        self.assertEqual(subs["a1b2c3d4e5"]["conferencia"], "aprovado")
        self.assertEqual(d["sessoes"][0]["titulo"], "Gestora de teste")                  # apelido da gestora


class TesteDecisoes(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()

    def tearDown(self):
        self.desmontar_mundo()

    def test_registrar_e_listar_mais_novas_primeiro(self):
        a = decisoes.registrar(self.slug, "Botões com 28 px", "decisao", "dono")
        b = decisoes.registrar(self.slug, "Nunca mexer na pasta financeiro", "regra", "gestor")
        lista = decisoes.listar(self.slug)
        self.assertEqual([x["id"] for x in lista], [b["id"], a["id"]])
        self.assertEqual(lista[0]["tipo"], "regra")
        self.assertTrue((config.pasta_projeto(self.slug) / "decisoes.jsonl").is_file())

    def test_validacao_e_mascara(self):
        with self.assertRaises(ValueError):
            decisoes.registrar(self.slug, "  ", "decisao", "dono")
        with self.assertRaises(ValueError):
            decisoes.registrar(self.slug, "ok ok", "tipo-errado", "dono")
        with self.assertRaises(ValueError):
            decisoes.registrar(self.slug, "x" * 3000, "decisao", "dono")
        with self.assertRaises(ValueError):
            decisoes.registrar(self.slug, "ok ok", "decisao", "<script>")
        d = decisoes.registrar(self.slug, "usar a senha=abc12345xyz no teste", "ideia", "dono")
        self.assertNotIn("abc12345xyz", d["texto"])

    def test_linha_quebrada_no_arquivo_nao_derruba(self):
        decisoes.registrar(self.slug, "primeira", "decisao", "dono")
        with open(config.pasta_projeto(self.slug) / "decisoes.jsonl", "ab") as f:
            f.write(b'{quebrada\n')
        decisoes.registrar(self.slug, "segunda", "decisao", "dono")
        self.assertEqual([x["texto"] for x in decisoes.listar(self.slug)], ["segunda", "primeira"])


class TesteCli(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo("ProjetoCli")
        self.criar_subagente("c1c2c3c4c5", "Revisar pagamentos", modelo="claude-opus-5-5")

    def tearDown(self):
        self.desmontar_mundo()

    def rodar(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            codigo = cerebro_cli.main(list(args))
        return codigo, out.getvalue(), err.getvalue()

    def test_conferir_e_estado(self):
        codigo, out, _ = self.rodar("a-conferir", "ProjetoCli")
        self.assertEqual(codigo, 0)
        self.assertIn("Revisar pagamentos", out)
        codigo, out, _ = self.rodar("conferir", "ProjetoCli", "pagamentos", "--resultado", "aprovado", "--nota", "diff e testes ok")
        self.assertEqual(codigo, 0)
        self.assertIn("aprovado", out)
        codigo, out, _ = self.rodar("estado", "ProjetoCli")
        self.assertIn("A conferir: 0", out)
        self.assertIn("aprovados 1", out)

    def test_decisao_e_listagem(self):
        codigo, _, _ = self.rodar("decisao", "ProjetoCli", "Usar Haiku só para buscas", "--tipo", "regra", "--origem", "dono")
        self.assertEqual(codigo, 0)
        _, out, _ = self.rodar("decisoes", "ProjetoCli")
        self.assertIn("Usar Haiku só para buscas", out)
        self.assertIn("regra/dono", out)

    def test_erros_sao_claros_e_saem_com_codigo_2(self):
        codigo, _, err = self.rodar("estado", "ProjetoQueNaoExiste")
        self.assertEqual(codigo, 2)
        self.assertIn("nenhum projeto casa", err)
        codigo, _, err = self.rodar("conferir", "ProjetoCli", "nada-disso", "--resultado", "aprovado")
        self.assertEqual(codigo, 2)
        codigo, _, err = self.rodar("conferir", "ProjetoCli")
        self.assertEqual(codigo, 2)

    def test_projeto_por_caminho_e_slug(self):
        self.assertEqual(cerebro_cli.achar_projeto(str(self.real))["slug"], self.slug)
        self.assertEqual(cerebro_cli.achar_projeto(self.slug)["nome"], "ProjetoCli")
        self.assertEqual(cerebro_cli.achar_projeto("projetocli")["slug"], self.slug)

    def test_tarefas_do_cerebro_e_analise_via_cli(self):
        codigo, out, _ = self.rodar("tarefas", "_cerebro")
        self.assertEqual(codigo, 0)
        self.assertIn("Nenhuma tarefa", out)
        self.assertEqual(json.loads(json.dumps(indice.estado(self.slug).progresso["rodando"])), False)


if __name__ == "__main__":
    unittest.main()
