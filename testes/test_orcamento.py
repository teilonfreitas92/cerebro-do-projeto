"""Orçamento de gasto: períodos, virada de mês, projeção, alertas de 80% e 100%, projeto sem limite, CLI e rotas."""
import datetime
import io
import json
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import cerebro_cli
from testes import _ambiente as amb
from cerebro import config, orcamento, painel
from testes.test_servidor import Base


def epoch(ano, mes, dia, hora=15):
    return time.mktime(datetime.datetime(ano, mes, dia, hora, 0).timetuple())


def dia_acc(custo, tokens=1000, sem_preco=0):
    return {"custo": custo, "entrada": tokens, "saida": 0, "cache_leitura": 0, "cache_escrita": 0, "mensagens": 1, "sem_preco": sem_preco}


# Quinta-feira 29/10/2026. A semana começa na segunda 26/10. Domingo 25/10 e 30/09 ficam fora da semana; 30/09 fica fora do mês.
POR_DIA = {"2026-09-30": dia_acc(100.0), "2026-10-25": dia_acc(10.0), "2026-10-26": dia_acc(4.0), "2026-10-29": dia_acc(2.0, 5000)}
HOJE = epoch(2026, 10, 29)


class Fake:
    """Troca custos.agregar por números combinados (nada de transcrito)."""

    def __init__(self, por_slug):
        self.por_slug = por_slug

    def __call__(self, slug, precos, desde_epoch=0.0):
        return {"por_dia": self.por_slug.get(slug, {}), "total": {}, "por_modelo": {}, "por_arquivo": {}, "modelos_sem_preco": []}


class Base_(amb.MundoFalso):
    def preparar(self, nome="LojaOrc", por_dia=None):
        self.montar_mundo(nome)
        amb.apagar(config.CASA / "orcamento.json")
        self.por_dia = {k: dict(v) for k, v in (POR_DIA if por_dia is None else por_dia).items()}      # cópia: os testes mexem nela
        self.fake = Fake({self.slug: self.por_dia})
        self.patch = mock.patch.object(orcamento.custos, "agregar", self.fake)
        self.patch.start()

    def limpar(self):
        self.patch.stop()
        self.desmontar_mundo()
        amb.apagar(config.CASA / "orcamento.json")

    def bloco(self, agora=HOJE):
        est = orcamento.estado(agora=agora)
        return [p for p in est["projetos"] if p["slug"] == self.slug][0], est


class TesteConfiguracao(Base_, unittest.TestCase):
    def setUp(self):
        self.preparar()

    def tearDown(self):
        self.limpar()

    def test_padrao_e_sem_limite(self):
        c = orcamento.ler()
        self.assertEqual(c["geral"], {"dia": None, "semana": None, "mes": None, "aviso_pct": 80})
        self.assertEqual(c["projetos"], {})

    def test_definir_projeto_e_geral_e_tirar_limite(self):
        orcamento.definir(self.slug, dia=5, mes=80.5)
        orcamento.definir("geral", semana=200)
        c = orcamento.ler()
        self.assertEqual((c["projetos"][self.slug]["dia"], c["projetos"][self.slug]["mes"], c["projetos"][self.slug]["semana"]), (5.0, 80.5, None))
        self.assertEqual(c["geral"]["semana"], 200.0)
        orcamento.definir(self.slug, dia=0)                                # 0 tira só aquele limite
        self.assertIsNone(orcamento.ler()["projetos"][self.slug]["dia"])
        self.assertEqual(orcamento.ler()["projetos"][self.slug]["mes"], 80.5)
        orcamento.definir(self.slug, mes=None)                             # sem nada configurado, a entrada some do arquivo
        self.assertNotIn(self.slug, json.loads((config.CASA / "orcamento.json").read_text(encoding="utf-8"))["projetos"])

    def test_aviso_personalizado(self):
        orcamento.definir(self.slug, mes=100, aviso_pct=50)
        self.assertEqual(orcamento.ler()["projetos"][self.slug]["aviso_pct"], 50)

    def test_valores_invalidos_nao_gravam_nada(self):
        for kw in [{"dia": -1}, {"dia": "dez"}, {"mes": True}, {"mes": 10_000_000}, {"aviso_pct": 0}, {"aviso_pct": 100}, {"aviso_pct": "x"},
                   {"dia": float("nan")}]:
            with self.assertRaises(ValueError, msg=str(kw)):
                orcamento.definir(self.slug, **kw)
        with self.assertRaises(ValueError):
            orcamento.definir("../fora", dia=1)
        self.assertFalse((config.CASA / "orcamento.json").exists())

    def test_arquivo_quebrado_ou_estranho_vira_sem_limite(self):
        (config.CASA / "orcamento.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(orcamento.ler()["geral"]["mes"], None)
        (config.CASA / "orcamento.json").write_text(json.dumps({"geral": {"dia": "abc", "mes": -3, "aviso_pct": 500}, "projetos": {"x": 5}}), encoding="utf-8")
        c = orcamento.ler()
        self.assertEqual(c["geral"], {"dia": None, "semana": None, "mes": None, "aviso_pct": 80})
        self.assertEqual(c["projetos"]["x"]["mes"], None)
        self.assertEqual(orcamento.alertas(), [])                          # nada configurado de verdade: nada a avisar

    def test_arquivo_fica_so_na_casa_do_cerebro(self):
        orcamento.definir("geral", dia=1)
        self.assertTrue(str((config.CASA / "orcamento.json").resolve()).startswith(str(config.CASA.resolve())))


class TestePeriodos(Base_, unittest.TestCase):
    def setUp(self):
        self.preparar()

    def tearDown(self):
        self.limpar()

    def test_dia_semana_e_mes(self):
        orcamento.definir(self.slug, dia=2, semana=20, mes=100)
        b, _ = self.bloco()
        p = b["periodos"]
        self.assertEqual((p["dia"]["gasto"], p["semana"]["gasto"], p["mes"]["gasto"]), (2.0, 6.0, 16.0))      # domingo 25 e 30/09 ficam de fora
        self.assertEqual(p["dia"]["tokens"], 5000)
        self.assertEqual(p["mes"]["tokens"], 1000 + 1000 + 5000)
        self.assertEqual((p["semana"]["pct"], p["semana"]["falta"], p["mes"]["falta"]), (30.0, 14.0, 84.0))

    def test_semana_comeca_na_segunda_e_atravessa_o_mes(self):
        from datetime import date
        self.assertEqual(orcamento.inicio_do_periodo("semana", date(2026, 10, 29)), date(2026, 10, 26))
        self.assertEqual(orcamento.inicio_do_periodo("semana", date(2026, 10, 26)), date(2026, 10, 26))      # segunda
        self.assertEqual(orcamento.inicio_do_periodo("semana", date(2026, 11, 1)), date(2026, 10, 26))       # domingo, semana de outubro
        self.assertEqual(orcamento.inicio_do_periodo("mes", date(2026, 11, 1)), date(2026, 11, 1))

    def test_virada_de_mes_zera_o_mes_e_muda_a_chave_do_alerta(self):
        orcamento.definir(self.slug, mes=16)
        antes = [a for a in orcamento.alertas(agora=HOJE) if a["escopo"] == self.slug]
        self.assertEqual([a["nivel"] for a in antes], ["estourou"])
        self.assertIn("2026-10", antes[0]["chave"])
        # 2 de novembro de 2026 (segunda): mês novo sem gasto; a semana começa em 02/11, então o gasto de outubro não conta
        b, _ = self.bloco(agora=epoch(2026, 11, 2))
        self.assertEqual((b["periodos"]["mes"]["gasto"], b["periodos"]["semana"]["gasto"], b["periodos"]["mes"]["nivel"]), (0.0, 0.0, "ok"))
        self.assertEqual([a for a in orcamento.alertas(agora=epoch(2026, 11, 2)) if a["escopo"] == self.slug], [])
        # gasto no mês novo: a chave carrega o mês novo, então o aviso volta a valer
        self.por_dia["2026-11-02"] = dia_acc(17.0)
        novo = [a for a in orcamento.alertas(agora=epoch(2026, 11, 2)) if a["escopo"] == self.slug]
        self.assertEqual(len(novo), 1)
        self.assertIn("2026-11", novo[0]["chave"])
        self.assertNotEqual(novo[0]["chave"], antes[0]["chave"])

    def test_dia_novo_muda_a_chave_do_alerta_do_dia(self):
        orcamento.definir(self.slug, dia=1)
        c1 = [a["chave"] for a in orcamento.alertas(agora=HOJE) if a["periodo"] == "dia"]
        self.por_dia["2026-10-30"] = dia_acc(3.0)
        c2 = [a["chave"] for a in orcamento.alertas(agora=epoch(2026, 10, 30)) if a["periodo"] == "dia"]
        self.assertEqual((len(c1), len(c2)), (1, 1))
        self.assertNotEqual(c1, c2)

    def test_gasto_sem_preco_e_sinalizado(self):
        self.por_dia["2026-10-29"] = dia_acc(0.0, 5000, sem_preco=3)
        orcamento.definir(self.slug, mes=100)
        b, _ = self.bloco()
        self.assertEqual(b["periodos"]["mes"]["sem_preco"], 3)


class TesteProjecao(Base_, unittest.TestCase):
    def setUp(self):
        self.preparar()

    def tearDown(self):
        self.limpar()

    def test_projecao_pelo_ritmo_do_mes(self):
        b, _ = self.bloco()
        pj = b["projecao_mes"]
        self.assertEqual((pj["dias_decorridos"], pj["dias_no_mes"]), (29, 31))
        self.assertAlmostEqual(pj["valor"], 16.0 / 29 * 31, places=3)
        self.assertFalse(pj["vai_passar"])                                  # sem limite do mês, não há o que passar
        self.assertIsNone(pj["pct"])

    def test_projecao_passa_do_limite_sem_ter_estourado(self):
        orcamento.definir(self.slug, mes=17)                                # gasto 16 < 17, mas 16/29*31 = 17,1
        b, _ = self.bloco()
        self.assertTrue(b["projecao_mes"]["vai_passar"])
        self.assertEqual(b["periodos"]["mes"]["nivel"], "atencao")          # 94% já é atenção; a projeção só aparece quando está "ok"
        orcamento.definir(self.slug, mes=40)
        b, _ = self.bloco()
        self.assertEqual(b["periodos"]["mes"]["nivel"], "ok")               # 40%: ok
        self.assertFalse(b["projecao_mes"]["vai_passar"])                   # projeta 17,1 < 40

    def test_alerta_de_projecao_so_quando_o_mes_esta_ok(self):
        # gasto 16 de 24 (66%, ok), mas o ritmo leva a 17,1... então não passa; limite 17 já é atenção. Monta um caso "ok" que passa:
        self.por_dia.clear()
        self.por_dia.update({"2026-10-03": dia_acc(9.0), "2026-10-04": dia_acc(9.0)})        # 18 em 29 dias de ritmo -> 19,2
        orcamento.definir(self.slug, mes=19, aviso_pct=99)                   # 18/19 = 94,7% < 99%: ok
        al = [a for a in orcamento.alertas(agora=HOJE) if a["escopo"] == self.slug]
        self.assertEqual([a["nivel"] for a in al], ["projecao"])
        self.assertIn("ritmo", al[0]["titulo"])
        self.assertEqual(al[0]["chave"], f"orcamento:{self.slug}:mes:2026-10:projecao")

    def test_sem_projecao_nos_primeiros_dias(self):
        self.por_dia.clear()
        self.por_dia["2026-11-01"] = dia_acc(9.0)
        orcamento.definir(self.slug, mes=20, aviso_pct=99)
        b, _ = self.bloco(agora=epoch(2026, 11, 1))
        self.assertFalse(b["projecao_mes"]["vai_passar"])                    # um dia de dados não prova ritmo
        self.assertEqual([a for a in orcamento.alertas(agora=epoch(2026, 11, 1)) if a["escopo"] == self.slug], [])


class TesteAlertas(Base_, unittest.TestCase):
    def setUp(self):
        self.preparar()

    def tearDown(self):
        self.limpar()

    def alertas(self):
        return [a for a in orcamento.alertas(agora=HOJE) if a["escopo"] == self.slug]

    def test_projeto_sem_limite_nao_alerta_e_aparece_sem_limite(self):
        self.assertEqual(orcamento.alertas(agora=HOJE), [])
        b, est = self.bloco()
        self.assertFalse(b["tem_limite"])
        self.assertEqual(b["nivel"], "sem_limite")
        self.assertEqual(b["periodos"]["dia"]["nivel"], "sem_limite")
        self.assertIsNone(b["periodos"]["dia"]["pct"])
        self.assertEqual(b["periodos"]["mes"]["gasto"], 16.0)               # o gasto aparece mesmo sem limite
        self.assertFalse(est["geral"]["tem_limite"])

    def test_abaixo_do_aviso_nada(self):
        orcamento.definir(self.slug, mes=21)                                # 16/21 = 76%
        self.assertEqual([a for a in self.alertas() if a["nivel"] != "projecao"], [])

    def test_80_por_cento_e_atencao(self):
        orcamento.definir(self.slug, mes=20)                                # 16/20 = 80% exato
        al = self.alertas()
        self.assertEqual([a["nivel"] for a in al], ["atencao"])
        self.assertIn("quase no fim", al[0]["titulo"])
        self.assertIn("US$ 16,00 de US$ 20,00 (80%)", al[0]["texto"])
        self.assertIn("Faltam US$ 4,00", al[0]["texto"])

    def test_79_por_cento_ainda_ok(self):
        orcamento.definir(self.slug, mes=20.2)                              # 79,2%
        self.assertEqual([a for a in self.alertas() if a["nivel"] != "projecao"], [])

    def test_100_por_cento_e_estouro(self):
        orcamento.definir(self.slug, mes=16)
        al = self.alertas()
        self.assertEqual([a["nivel"] for a in al], ["estourou"])
        self.assertIn("estourou", al[0]["titulo"])
        orcamento.definir(self.slug, mes=10)
        al = self.alertas()
        self.assertEqual([a["nivel"] for a in al], ["estourou"])
        self.assertIn("160%", al[0]["texto"])

    def test_aviso_personalizado_muda_o_ponto_de_atencao(self):
        orcamento.definir(self.slug, mes=40, aviso_pct=40)                  # 16/40 = 40%
        self.assertEqual([a["nivel"] for a in self.alertas()], ["atencao"])

    def test_varios_periodos_e_ordem_estouro_primeiro(self):
        orcamento.definir(self.slug, dia=2.2, semana=6, mes=19)             # dia 91% atenção, semana 100% estourou, mês 84% atenção
        al = self.alertas()
        self.assertEqual([(a["periodo"], a["nivel"]) for a in al], [("semana", "estourou"), ("dia", "atencao"), ("mes", "atencao")])
        self.assertEqual(len({a["chave"] for a in al}), 3)

    def test_chave_estavel_e_muda_com_o_nivel(self):
        orcamento.definir(self.slug, mes=20)
        c1 = self.alertas()[0]["chave"]
        self.assertEqual(c1, self.alertas()[0]["chave"])                    # mesma chamada, mesma chave (não avisa duas vezes)
        orcamento.definir(self.slug, mes=16)
        c2 = self.alertas()[0]["chave"]
        self.assertNotEqual(c1, c2)                                         # piorou para "estourou": novo aviso
        self.assertTrue(c1.endswith(":atencao") and c2.endswith(":estourou"))

    def test_formato_dos_alertas(self):
        orcamento.definir("geral", mes=10)
        for a in orcamento.alertas(agora=HOJE):
            self.assertEqual({"titulo", "texto", "chave", "nivel", "escopo", "periodo"}, set(a))
            self.assertTrue(all(isinstance(a[k], str) and a[k] for k in ("titulo", "texto", "chave", "nivel")))

    def test_orcamento_geral_soma_os_projetos(self):
        outro = "C--Users-ana-Projetos-Outro"
        self.fake.por_slug[outro] = {"2026-10-29": dia_acc(3.0)}
        with mock.patch.object(orcamento.projetos, "descobrir", return_value=[{"slug": self.slug, "nome": "A", "oculto": False},
                                                                              {"slug": outro, "nome": "B", "oculto": True}]):
            orcamento.definir("geral", dia=5)
            est = orcamento.estado(agora=HOJE)
            self.assertEqual(est["geral"]["periodos"]["dia"]["gasto"], 5.0)           # 2 + 3, incluindo o projeto oculto
            al = orcamento.alertas(agora=HOJE)
            self.assertEqual([(a["escopo"], a["nivel"]) for a in al], [("geral", "estourou")])
            self.assertIn("todos os projetos", al[0]["titulo"])

    def test_itens_do_precisa_de_voce(self):
        orcamento.definir(self.slug, mes=16, dia=2.4)                        # mês estourou; dia 83% atenção
        with mock.patch.object(orcamento, "hoje_local", return_value=datetime.date(2026, 10, 29)):
            itens = orcamento.itens_fila()
        por_nivel = {i["nivel"]: i for i in itens}
        self.assertEqual(set(por_nivel), {"acao", "aviso"})
        self.assertEqual(por_nivel["acao"]["projeto"], self.slug)
        self.assertEqual(por_nivel["acao"]["aba"], "custos")
        orcamento.definir("geral", mes=1)
        with mock.patch.object(orcamento, "hoje_local", return_value=datetime.date(2026, 10, 29)):
            geral = [i for i in orcamento.itens_fila() if i["projeto"] == ""]
        self.assertEqual(len(geral), 1)

    def test_painel_fila_inclui_o_orcamento(self):
        orcamento.definir(self.slug, mes=16)
        with mock.patch.object(orcamento, "hoje_local", return_value=datetime.date(2026, 10, 29)):
            titulos = [i["titulo"] for i in painel.fila(config.ler_config())]
        self.assertTrue(any("Orçamento estourou" in t for t in titulos), titulos)


class TesteComCustosReais(unittest.TestCase):
    """O orçamento lê os mesmos dias que a aba Custos soma (custos.agregar), aqui com um transcrito de mentira de verdade."""

    def test_gasto_do_dia_vem_do_indice(self):
        from cerebro import indice
        slug = "C--Falso-Orcamento-" + str(int(time.time() * 1000))
        pasta = config.PROJETOS_CLAUDE / slug
        pasta.mkdir(parents=True)
        (pasta / "s1.jsonl").write_text(
            amb.linha_assistente("m1", ts="2026-10-28T15:00:00.000Z", modelo="claude-opus-5-5", entrada=1_000_000, saida=0, leitura=0)
            + amb.linha_assistente("m2", ts="2026-10-28T15:30:00.000Z", modelo="claude-opus-5-5", entrada=500_000, saida=0, leitura=0), encoding="utf-8")
        indice.indexar_projeto(slug)
        precos = {"claude-opus-5-5": {"entrada": 4.0, "saida": 20.0, "cache_leitura": 0.2, "cache_escrita_5m": 5.0, "cache_escrita_1h": 8.0}}
        por_dia = orcamento._por_dia_do_projeto(slug, precos)
        self.assertEqual(len(por_dia), 1)
        dia_real = list(por_dia)[0]
        b = orcamento.bloco(por_dia, {"dia": 5.0, "aviso_pct": 80}, datetime.date.fromisoformat(dia_real))
        self.assertAlmostEqual(b["periodos"]["dia"]["gasto"], 6.0)               # 1,5 milhão de tokens de entrada x US$ 4
        self.assertEqual(b["periodos"]["dia"]["tokens"], 1_500_000)
        self.assertEqual(b["periodos"]["dia"]["nivel"], "estourou")


class TesteCliOrcamento(Base_, unittest.TestCase):
    def setUp(self):
        self.preparar("ProjetoOrc")

    def tearDown(self):
        self.limpar()

    def rodar(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                codigo = cerebro_cli.main(list(args))
            except SystemExit as e:
                codigo = e.code
        return codigo, out.getvalue(), err.getvalue()

    def test_mostrar_sem_nada_definido(self):
        codigo, out, _ = self.rodar("orcamento")
        self.assertEqual(codigo, 0)
        self.assertIn("ESTIMATIVA", out)
        self.assertIn("GERAL", out)

    def test_definir_por_projeto_e_geral(self):
        codigo, out, _ = self.rodar("orcamento", "ProjetoOrc", "--dia", "5", "--semana", "25,5", "--mes", "80", "--aviso", "70")
        self.assertEqual(codigo, 0)
        self.assertIn("salvo", out)
        c = orcamento.ler()["projetos"][self.slug]
        self.assertEqual((c["dia"], c["semana"], c["mes"], c["aviso_pct"]), (5.0, 25.5, 80.0, 70))
        self.assertIn("ProjetoOrc", self.rodar("orcamento")[1])
        codigo, out, _ = self.rodar("orcamento", "--mes", "300")
        self.assertEqual(orcamento.ler()["geral"]["mes"], 300.0)
        self.rodar("orcamento", "ProjetoOrc", "--dia", "0")
        self.assertIsNone(orcamento.ler()["projetos"][self.slug]["dia"])

    def test_valor_ruim_da_erro(self):
        self.assertEqual(self.rodar("orcamento", "ProjetoOrc", "--dia", "muito")[0], 2)
        codigo, _, err = self.rodar("orcamento", "ProjetoOrc", "--aviso", "150")
        self.assertEqual(codigo, 2)
        self.assertIn("aviso", err)
        self.assertEqual(self.rodar("orcamento", "NaoExiste")[0], 2)


class TesteRotasOrcamento(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        amb.apagar(config.CASA / "orcamento.json")

    async def asyncTearDown(self):
        amb.apagar(config.CASA / "orcamento.json")
        await super().asyncTearDown()

    async def test_exige_cookie_origin_e_json(self):
        self.assertEqual((await self.http.get(self.base + "/api/orcamento")).status, 401)
        self.assertEqual((await self.http.get(f"{self.base}/api/p/{self.slug}/orcamento")).status, 401)
        self.assertEqual((await self.post("/api/orcamento", {"escopo": "geral", "mes": 1})).status, 401)
        await self.entrar()
        self.assertEqual((await self.post("/api/orcamento", {"escopo": "geral", "mes": 1}, origem=False)).status, 403)
        self.assertEqual((await self.http.post(self.base + "/api/orcamento", data="mes=1", headers={"Origin": self.base})).status, 415)
        self.assertEqual((await self.http.post(self.base + "/api/orcamento", data="{}", headers={"Origin": "http://evil.com", "Content-Type": "application/json"})).status, 403)
        self.assertFalse((config.CASA / "orcamento.json").exists())

    async def test_salvar_e_ler(self):
        await self.entrar()
        r = await self.post("/api/orcamento", {"escopo": self.slug, "dia": 5, "mes": 60, "aviso_pct": 75})
        self.assertEqual(r.status, 200)
        d = await r.json()
        p = [x for x in d["projetos"] if x["slug"] == self.slug][0]
        self.assertEqual((p["limites"]["dia"], p["limites"]["mes"], p["aviso_pct"], p["tem_limite"]), (5.0, 60.0, 75, True))
        self.assertIn("ESTIMATIVA", d["estimativa"])
        r = await self.post("/api/orcamento", {"escopo": "geral", "semana": 100})
        self.assertEqual((await r.json())["geral"]["limites"]["semana"], 100.0)
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/orcamento")).json()
        self.assertEqual(d["projeto"]["limites"]["mes"], 60.0)
        self.assertEqual(d["geral"]["limites"]["semana"], 100.0)

    async def test_erros(self):
        await self.entrar()
        for corpo in [{}, {"escopo": ""}, {"escopo": 5}, {"escopo": "geral", "dia": -3}, {"escopo": "geral", "mes": "x"}, {"escopo": "geral", "aviso_pct": 100}]:
            self.assertEqual((await self.post("/api/orcamento", corpo)).status, 400, corpo)
        self.assertEqual((await self.post("/api/orcamento", {"escopo": "C--Nao-Existe", "dia": 1})).status, 404)
        self.assertEqual((await self.post("/api/orcamento", {"escopo": "../x", "dia": 1})).status, 404)
        self.assertEqual((await self.http.get(f"{self.base}/api/p/Inexistente/orcamento")).status, 404)
        self.assertFalse((config.CASA / "orcamento.json").exists())


if __name__ == "__main__":
    unittest.main()
