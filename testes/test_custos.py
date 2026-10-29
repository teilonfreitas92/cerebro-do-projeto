import json
import time
import unittest

from cerebro import config, custos, indice, transcricao
from testes._ambiente import linha_assistente

PRECOS = {
    "claude-opus-5-5": {"entrada": 4.0, "saida": 20.0, "cache_leitura": 0.2, "cache_escrita_5m": 5.0, "cache_escrita_1h": 8.0},
    "claude-sonnet-5": {"entrada": 2.0, "saida": 10.0, "cache_leitura": 0.1, "cache_escrita_5m": 2.5, "cache_escrita_1h": 4.0},
}


class TesteCusto(unittest.TestCase):
    def test_conta_de_um_milhao(self):
        c = custos.custo_usd((1_000_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000), PRECOS["claude-opus-5-5"])
        self.assertAlmostEqual(c, 4 + 20 + 0.2 + 5 + 8)

    def test_pequeno(self):
        c = custos.custo_usd((10, 20, 1000, 0, 0), PRECOS["claude-opus-5-5"])
        self.assertAlmostEqual(c, (10 * 4 + 20 * 20 + 1000 * 0.2) / 1e6)

    def test_sem_preco_devolve_none(self):
        self.assertIsNone(custos.custo_usd((1, 1, 1, 1, 1), None))

    def test_busca_por_prefixo_mais_longo(self):
        precos = dict(PRECOS, **{"claude-opus": {"entrada": 99}})
        self.assertIs(custos.preco_do_modelo("claude-opus-5-5-20261001", precos), precos["claude-opus-5-5"])
        self.assertIs(custos.preco_do_modelo("claude-opus-9", precos), precos["claude-opus"])
        self.assertIsNone(custos.preco_do_modelo("gpt-x", precos))
        self.assertIsNone(custos.preco_do_modelo("", precos))

    def test_total_tokens(self):
        self.assertEqual(custos.total_tokens({"entrada": 1, "saida": 2, "cache_leitura": 3, "cache_escrita": 4}), 10)


class TesteAgregacao(unittest.TestCase):
    """Projeto de mentira em .claude/projects: uma sessão e um subagente, em dois dias e dois modelos."""

    def setUp(self):
        self.slug = "C--Falso-Projeto-" + str(int(time.time() * 1000))
        pasta = config.PROJETOS_CLAUDE / self.slug
        (pasta / "sessA" / "subagents").mkdir(parents=True)
        (pasta / "sessA.jsonl").write_text(
            linha_assistente("m1", ts="2026-10-27T15:00:00.000Z", entrada=100, saida=200, leitura=10_000)
            + linha_assistente("m1", ts="2026-10-27T15:00:00.000Z", entrada=100, saida=200, leitura=10_000)      # repetida
            + linha_assistente("m2", ts="2026-10-28T15:00:00.000Z", modelo="claude-sonnet-5-5-novo", entrada=50, saida=60, leitura=0, escrita=1000, w1=1000)
            + linha_assistente("m3", ts="2026-10-28T16:00:00.000Z", modelo="modelo-desconhecido", entrada=7, saida=7, leitura=7),
            encoding="utf-8")
        (pasta / "sessA" / "subagents" / "agent-x1.jsonl").write_text(
            linha_assistente("s1", ts="2026-10-28T17:00:00.000Z", modelo="claude-sonnet-5-5", entrada=1, saida=1, leitura=1), encoding="utf-8")
        (pasta / "sessA" / "subagents" / "agent-x1.meta.json").write_text(json.dumps({"description": "Faz um teste", "model": "sonnet", "finished": True}))
        precos = dict(PRECOS)
        precos["claude-sonnet-5-5"] = PRECOS["claude-sonnet-5"]
        self.precos = precos
        indice.indexar_projeto(self.slug)

    def test_soma_por_modelo_dia_e_arquivo(self):
        d = custos.agregar(self.slug, self.precos)
        self.assertEqual(d["total"]["mensagens"], 4)           # m1 só uma vez
        self.assertEqual(d["total"]["entrada"], 100 + 50 + 7 + 1)
        self.assertEqual(d["total"]["cache_escrita"], 1000)
        self.assertEqual(set(d["por_modelo"]), {"claude-opus-5-5", "claude-sonnet-5-5-novo", "modelo-desconhecido", "claude-sonnet-5-5"})
        self.assertEqual(sorted(d["por_dia"]), ["2026-10-27", "2026-10-28"])
        self.assertEqual(d["por_modelo"]["claude-opus-5-5"]["custo"], (100 * 4 + 200 * 20 + 10_000 * 0.2) / 1e6)
        self.assertEqual(d["modelos_sem_preco"], ["modelo-desconhecido"])
        self.assertEqual(d["total"]["sem_preco"], 1)
        self.assertEqual(set(d["por_arquivo"]), {"sessA.jsonl", "sessA/subagents/agent-x1.jsonl"})
        self.assertEqual(d["por_arquivo"]["sessA/subagents/agent-x1.jsonl"]["mensagens"], 1)

    def test_cache_de_escrita_usa_preco_de_1h(self):
        d = custos.agregar(self.slug, self.precos)
        esperado = (50 * 2 + 60 * 10 + 1000 * 4.0) / 1e6
        self.assertAlmostEqual(d["por_modelo"]["claude-sonnet-5-5-novo"]["custo"], esperado)

    def test_corte_por_data(self):
        corte = transcricao.para_epoch("2026-10-28T00:00:00Z")      # as mensagens de 27/10 ficam de fora
        d = custos.agregar(self.slug, self.precos, desde_epoch=corte)
        self.assertEqual(sorted(d["por_dia"]), ["2026-10-28"])

    def test_mudar_preco_muda_resultado(self):
        a = custos.agregar(self.slug, self.precos)["total"]["custo"]
        caro = json.loads(json.dumps(self.precos))
        caro["claude-opus-5-5"]["saida"] = 40.0
        b = custos.agregar(self.slug, caro)["total"]["custo"]
        self.assertGreater(b, a)

    def test_indice_novo_invalida_cache(self):
        a = custos.agregar(self.slug, self.precos)["total"]["mensagens"]
        arq = config.PROJETOS_CLAUDE / self.slug / "sessA.jsonl"
        with open(arq, "ab") as f:
            f.write(linha_assistente("m9", ts="2026-10-28T18:00:00.000Z").encode())
        indice.indexar_projeto(self.slug)
        self.assertEqual(custos.agregar(self.slug, self.precos)["total"]["mensagens"], a + 1)

    def test_indice_guardado_em_disco_e_relido(self):
        indice.salvar_tudo()
        arq = config.CASA / "projetos" / self.slug / "indice.json"
        self.assertTrue(arq.is_file())
        dados = json.loads(arq.read_text(encoding="utf-8"))
        self.assertIn("sessA.jsonl", dados["arquivos"])


if __name__ == "__main__":
    unittest.main()
