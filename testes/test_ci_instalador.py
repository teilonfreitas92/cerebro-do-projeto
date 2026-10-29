"""Ajudantes do testes/ci_instalador.py (a prova inteira do instalador roda no GitHub Actions ou à mão: ela sobe servidor e instala)."""
import unittest

from testes import _ambiente as amb
from testes import ci_instalador as ci


class TesteAjudantes(unittest.TestCase):
    def test_porta_livre_nunca_e_proibida(self):
        for _ in range(20):
            p = ci.porta_livre()
            self.assertNotIn(p, ci.PORTAS_PROIBIDAS)
            self.assertNotEqual(p, 8188)
            self.assertGreater(p, 1023)

    def test_proibidas_cobrem_a_referencia(self):
        self.assertTrue({80, 8050, 8060, 8070, 8090, 8091, 8095, 8097, 7980, 8188} <= ci.PORTAS_PROIBIDAS)

    def test_instantaneo_e_diferencas(self):
        pasta = amb.BASE / "ci_helpers"
        (pasta / "a").mkdir(parents=True, exist_ok=True)
        (pasta / "a" / "x.txt").write_text("1", encoding="utf-8")
        (pasta / "y.txt").write_text("2", encoding="utf-8")
        (pasta / "__pycache__").mkdir(exist_ok=True)
        (pasta / "__pycache__" / "z.pyc").write_text("ruído", encoding="utf-8")
        antes = ci.instantaneo(pasta)
        self.assertEqual(sorted(antes), ["a/x.txt", "y.txt"])                     # __pycache__ não conta
        self.assertEqual(ci.diferencas(antes, ci.instantaneo(pasta)), ([], [], []))
        (pasta / "y.txt").write_text("outro", encoding="utf-8")
        (pasta / "novo.txt").write_text("n", encoding="utf-8")
        amb.apagar(pasta / "a" / "x.txt")
        self.assertEqual(ci.diferencas(antes, ci.instantaneo(pasta)), (["a/x.txt"], ["novo.txt"], ["y.txt"]))
        amb.apagar(pasta)

    def test_pasta_inexistente_e_vazia(self):
        self.assertEqual(ci.instantaneo(amb.BASE / "nao-existe-ci"), {})

    def test_conferir_levanta_falha_e_registra_ok(self):
        lista = []
        ci.conferir(True, "passou", lista)
        self.assertEqual(lista, ["passou"])
        with self.assertRaises(ci.Falha):
            ci.conferir(False, "não passou", lista)
        self.assertEqual(lista, ["passou"])

    def test_copia_nao_leva_dados_do_dono(self):
        nomes = ["token", "servidor.json", "config.json", ".venv", ".git", "__pycache__", "graphify-out", ".instalacao.json", "cerebro.py"]
        self.assertEqual(sorted(ci.IGNORAR_NA_COPIA("x", nomes)), sorted(nomes[:-1]))     # tudo menos o código

    def test_python_do_venv_fica_dentro_da_pasta(self):
        self.assertIn(".venv", ci.python_do_venv(amb.BASE / "p").parts)


if __name__ == "__main__":
    unittest.main()
