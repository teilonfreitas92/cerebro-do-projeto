"""A CLI aceita o slug do Claude Code de Linux/Mac, que começa com '-' ('-home-ana-loja').

Antes o argparse lia '-home...' como '-h' (ajuda) e saía com código 0 sem fazer nada. Vale no Windows também: o teste
só passa a palavra pela linha de comando e confere que ela chegou inteira como projeto (ou sessão, ou valor).
"""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from testes import _ambiente as amb  # noqa: F401  (isola o ambiente antes de importar o Cérebro)
import cerebro_cli

SLUG = "-home-ana--cerebro-Meu-Projeto"


class TesteSlugComTraco(unittest.TestCase):
    def rodar(self, *argv):
        vistos = []

        def achar(ref):
            vistos.append(ref)
            raise ValueError("parei aqui (teste)")
        with mock.patch.object(cerebro_cli, "achar_projeto", achar), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            codigo = cerebro_cli.main(list(argv))
        return codigo, vistos

    def test_slug_com_traco_chega_como_projeto_em_todo_subcomando(self):
        for argv in (["estado", SLUG], ["bastao", SLUG, "abc123"], ["memoria", SLUG, "--compactar", "--aplicar", "--confirmar"],
                     ["decisao", SLUG, "texto"], ["gestora", "limpar", SLUG, "--confirmar"], ["manual", SLUG, "--previa"],
                     ["encaixe", SLUG, "--previa"], ["agentes-copiar", SLUG], ["explicar", SLUG, "--estimar"]):
            codigo, vistos = self.rodar(*argv)
            self.assertEqual(codigo, cerebro_cli.SAIDA_ERRO, argv)        # chegou ao comando (o achar falso recusa), não à ajuda
            self.assertEqual(vistos, [SLUG], argv)

    def test_valor_de_opcao_com_traco_e_numero_negativo(self):
        a = {}

        def pegar(ns):
            a.update(vars(ns))
            return 0
        with mock.patch.object(cerebro_cli, "cmd_decisoes", pegar), mock.patch.object(cerebro_cli, "cmd_conferir", pegar):
            self.assertEqual(cerebro_cli.main(["decisoes", SLUG, "--limite", "-1"]), 0)
            self.assertEqual((a["projeto"], a["limite"]), (SLUG, -1))
            self.assertEqual(cerebro_cli.main(["conferir", SLUG, "-abc", "--nota", "-nota com traço"]), 0)
            self.assertEqual((a["projeto"], a["ref"], a["nota"]), (SLUG, "-abc", "-nota com traço"))

    def test_ajuda_continua_funcionando(self):
        for argv in (["-h"], ["--help"], ["bastao", "-h"], ["memoria", "--help"]):
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit) as fim:
                cerebro_cli.main(argv)
            self.assertEqual(fim.exception.code, 0, argv)
            self.assertIn("usage", out.getvalue().lower(), argv)

    def test_opcao_desconhecida_com_dois_tracos_continua_erro(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as fim:
            cerebro_cli.main(["estado", SLUG, "--nao-existe"])
        self.assertEqual(fim.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
