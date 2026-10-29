import json
import unittest

from testes import _ambiente as amb
from cerebro import config


class TesteConfig(unittest.TestCase):
    def setUp(self):
        for f in ("config.json", "token"):
            amb.apagar(config.CASA / f)

    def test_primeira_vez_cria_padrao_generico_sem_nada_de_ninguem(self):
        cfg = config.ler_config()
        self.assertEqual(cfg["gestoras"], {})
        self.assertEqual(cfg["comandos"], {})
        self.assertEqual(cfg["departamentos"], {})
        self.assertEqual(cfg["projetos_extra"], [])
        self.assertEqual(cfg["nunca_entrar"], [])
        self.assertFalse(cfg["primeiro_uso_concluido"])
        self.assertTrue((config.CASA / "config.json").is_file())
        self.assertEqual(cfg["porta"], 8188)
        self.assertEqual(cfg["rotinas"]["agendamento_ativo"], False)

    def test_config_quebrada_volta_ao_padrao(self):
        config.CASA.mkdir(parents=True, exist_ok=True)
        (config.CASA / "config.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(config.ler_config()["porta"], 8188)

    def test_chaves_novas_do_padrao_aparecem_em_config_antiga(self):
        config.CASA.mkdir(parents=True, exist_ok=True)
        (config.CASA / "config.json").write_text(json.dumps({"porta": 8200, "rotinas": {"autoevolucao_dias": 14}}), encoding="utf-8")
        cfg = config.ler_config()
        self.assertEqual(cfg["porta"], 8200)
        self.assertEqual(cfg["rotinas"]["autoevolucao_dias"], 14)
        self.assertEqual(cfg["rotinas"]["vigia_novidades_dias"], 3)
        self.assertIn("claude-opus-5-5", cfg["precos"])

    def test_precos_iniciais_sao_coerentes(self):
        for modelo, p in config.PRECOS_PADRAO.items():
            for campo in ("entrada", "saida", "cache_leitura", "cache_escrita_5m", "cache_escrita_1h"):
                self.assertGreater(p[campo], 0, f"{modelo}/{campo}")
            self.assertGreater(p["saida"], p["entrada"])
            self.assertLess(p["cache_leitura"], p["entrada"])

    def test_token_aleatorio_estavel_e_cookie_nao_e_o_token(self):
        t1 = config.ler_token()
        self.assertGreaterEqual(len(t1), 32)
        self.assertEqual(config.ler_token(), t1)
        amb.apagar(config.CASA / "token")
        self.assertNotEqual(config.ler_token(), t1)
        c = config.valor_cookie(t1)
        self.assertNotIn(t1, c)
        self.assertEqual(c, config.valor_cookie(t1))
        self.assertNotEqual(c, config.valor_cookie(config.ler_token()))

    def test_token_continua_legivel_pelo_dono(self):
        t = config.ler_token()
        self.assertEqual((config.CASA / "token").read_text(encoding="ascii").strip(), t)

    def test_pasta_de_projeto_recusa_slug_malicioso(self):
        for ruim in ["../x", "a/b", "", "a\\b", "x" * 300]:
            with self.assertRaises(ValueError):
                config.pasta_projeto(ruim)


if __name__ == "__main__":
    unittest.main()
