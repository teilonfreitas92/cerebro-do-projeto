"""O gancho liga o Cérebro quando ele está fechado (o servidor encerra sozinho sem página e sem eventos; reiniciar o PC também)."""
import urllib.error
import unittest

from testes import _ambiente as amb
import cerebro_hook


class TesteGanchoLigaOServidor(unittest.TestCase):
    def setUp(self):
        self.c = amb.BASE / "casa_hook_liga"
        self.c.mkdir(parents=True, exist_ok=True)
        for nome in ("servidor.json", "hooks_token", ".ligando"):
            amb.apagar(self.c / nome)
        self.chamadas = []

    def ligar(self, c):
        self.chamadas.append(c)

    def test_fechado_com_ganchos_configurados_liga(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        self.assertEqual(cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', self.c, ligar=self.ligar), "")
        self.assertEqual(self.chamadas, [self.c])

    def test_porta_recusando_liga(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        (self.c / "servidor.json").write_text('{"porta": 8188}', encoding="utf-8")

        def recusa(_req, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())
        cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', self.c, abrir=recusa, ligar=self.ligar)
        self.assertEqual(self.chamadas, [self.c])

    def test_tempo_esgotado_tambem_liga(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        (self.c / "servidor.json").write_text('{"porta": 8188}', encoding="utf-8")

        def demora(_req, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))
        cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', self.c, abrir=demora, ligar=self.ligar)
        self.assertEqual(self.chamadas, [self.c])

    def test_servidor_respondeu_com_erro_nao_liga(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        (self.c / "servidor.json").write_text('{"porta": 8188}', encoding="utf-8")

        def erro(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "não", {}, None)
        cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', self.c, abrir=erro, ligar=self.ligar)
        self.assertEqual(self.chamadas, [])

    def test_sem_ganchos_configurados_nao_liga_nada(self):
        argv = []
        self.assertFalse(cerebro_hook.ligar_servidor(self.c, executar=lambda a, **k: argv.append(a)))
        self.assertEqual(argv, [])

    def test_liga_sem_janela_e_no_maximo_uma_vez_a_cada_2_min(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        argv = []
        self.assertTrue(cerebro_hook.ligar_servidor(self.c, executar=lambda a, **k: argv.append((a, k)), agora=1_000_000))
        self.assertTrue(argv[0][0][1].endswith("abrir_cerebro.py"))
        self.assertEqual(argv[0][0][2], "--sem-navegador")
        import os
        os.utime(self.c / ".ligando", (1_000_000, 1_000_000))
        self.assertFalse(cerebro_hook.ligar_servidor(self.c, executar=lambda a, **k: argv.append((a, k)), agora=1_000_060))
        self.assertEqual(len(argv), 1)
        self.assertTrue(cerebro_hook.ligar_servidor(self.c, executar=lambda a, **k: argv.append((a, k)), agora=1_000_200))

    def test_nos_testes_nunca_sobe_processo_de_verdade(self):
        (self.c / "hooks_token").write_text("t" * 43, encoding="ascii")
        self.assertFalse(cerebro_hook.ligar_servidor(self.c))          # sem executar falso: a trava dos testes recusa


if __name__ == "__main__":
    unittest.main()
