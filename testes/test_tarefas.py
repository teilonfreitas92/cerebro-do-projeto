"""Tarefas para o gestor: criação, estados e histórico, migração do tarefas.json antigo, texto para o gestor, CLI e rotas."""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import cerebro_cli
from testes import _ambiente as amb
from cerebro import armazem, config, projetos, propostas, tarefas_gestor
from testes.test_servidor import Base

DADOS_MAPA = {
    "meta": {}, "deptos": ["Núcleo"], "cores": ["#00b2ff"], "ancoras": [None],
    "tipos": ["arquivo", "classe", "função", "método", "símbolo", "dependência externa", "pacote ou conceito"],
    "arquivos": ["src/api.py", "src/util.py"],
    "grupos": [{"n": "Servidor", "d": 0, "t": 3, "c": 0.5}, {"n": "Utilitários", "d": 0, "t": 1, "c": 0.4}],
    "nos": {"n": ["api.py", "util.py", "criar_pedido", "limpar_texto"], "a": [0, 1, 0, 1], "l": [0, 0, 12, 5], "k": [0, 0, 2, 2],
            "g": [0, 1, 0, 1], "d": [0, 0, 0, 0]},
}


def gravar_mapa(slug, dados=DADOS_MAPA):
    pasta = config.CASA / "projetos" / slug / "mapa"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "dados.js").write_text("window.CEREBRO = " + json.dumps(dados, ensure_ascii=False) + ";\n", encoding="utf-8")


def limpar_arquivos(slug):
    for nome in ("tarefas.json", "propostas.json"):
        amb.apagar(config.CASA / "projetos" / slug / nome)
    amb.apagar(config.CASA / "projetos" / slug / "mapa")
    tarefas_gestor._cache_mapa.clear()


PONTO_FUNCAO = {"tipo": "função", "nome": "criar_pedido", "arquivo": "src/api.py", "linha": 12, "grupo": "Servidor"}


class TesteCriarEEstados(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo("LojaTarefas")
        limpar_arquivos(self.slug)

    def tearDown(self):
        self.desmontar_mundo()

    def test_criar_guarda_tudo_e_sugere_o_agente(self):
        t = tarefas_gestor.criar(self.slug, "Corrigir bug no cálculo do frete", "Ao somar dois itens o frete dobra.", "alta", [PONTO_FUNCAO])
        self.assertTrue(t["id"].startswith("n-"))
        self.assertEqual((t["estado"], t["prioridade"], t["origem"]), ("nova", "alta", "dono"))
        self.assertEqual(t["pontos"][0]["nome"], "criar_pedido")
        self.assertEqual(t["agente_tipo"], "codigo")                       # "corrigir" e "bug" casam com o tipo de código comum
        self.assertTrue(t["agente_sugerido"])
        self.assertEqual((t["agente"]["modelo"], t["agente"]["id"]), ("sonnet", "codigo"))
        self.assertIn("confere", t["agente"]["revisor"].lower())
        self.assertEqual([h["para"] for h in t["historico"]], ["nova"])
        self.assertEqual(t["historico"][0]["por"], "dono")
        self.assertEqual(tarefas_gestor.achar(self.slug, t["id"])["titulo"], t["titulo"])

    def test_tipo_de_agente_escolhido_vale_e_desconhecido_e_recusado(self):
        t = tarefas_gestor.criar(self.slug, "Revisar tudo", agente_tipo="critico")
        self.assertEqual((t["agente_tipo"], t["agente_sugerido"], t["agente"]["modelo"]), ("critico", False, "opus"))
        with self.assertRaises(ValueError):
            tarefas_gestor.criar(self.slug, "Algo", agente_tipo="inventado")

    def test_validacoes(self):
        for args in [("",), ("   ",), ("x" * 5, "", "urgentissima"), ("ok", "", "normal", "nao-lista"), ("ok", "", "normal", [{"nome": ""}]),
                     ("ok", "", "normal", [PONTO_FUNCAO] * 1 + [dict(PONTO_FUNCAO, nome=f"f{i}") for i in range(25)])]:
            with self.assertRaises(ValueError, msg=str(args)):
                tarefas_gestor.criar(self.slug, *args)
        self.assertEqual(tarefas_gestor.listar(self.slug), [])             # nada foi gravado

    def test_titulo_comprido_e_segredo_sao_tratados(self):
        t = tarefas_gestor.criar(self.slug, "Trocar a senha=abc12345xyz do banco " + "x" * 300)
        self.assertNotIn("abc12345xyz", t["titulo"])
        self.assertLessEqual(len(t["titulo"]), tarefas_gestor.MAX_TITULO)

    def test_pontos_repetidos_somem(self):
        t = tarefas_gestor.criar(self.slug, "Mexer", pontos=[PONTO_FUNCAO, dict(PONTO_FUNCAO)])
        self.assertEqual(len(t["pontos"]), 1)

    def test_ponto_de_grupo_ganha_os_arquivos_do_mapa(self):
        gravar_mapa(self.slug)
        t = tarefas_gestor.criar(self.slug, "Revisar o servidor", pontos=[{"tipo": "grupo", "nome": "Servidor"}])
        self.assertEqual(t["pontos"][0]["arquivos"], ["src/api.py"])

    def test_ciclo_completo_com_historico(self):
        t = tarefas_gestor.criar(self.slug, "Fazer X", agora=1000.0)
        tid = t["id"]
        tarefas_gestor.mudar_estado(self.slug, tid, "recebida", "gestor", "Gestor", agora=1100.0)
        tarefas_gestor.mudar_estado(self.slug, tid, "andamento", "gestor", "agente-codigo #2", "começando", agora=1200.0)
        tarefas_gestor.mudar_estado(self.slug, tid, "conferir", "gestor", "agente-codigo #2", "testes ok", agora=1300.0)
        f = tarefas_gestor.mudar_estado(self.slug, tid, "feita", "dono", "", "conferido", agora=1400.0)
        self.assertEqual(f["estado"], "feita")
        self.assertEqual(f["feita_em"], 1400.0)
        self.assertEqual(f["nota_final"], "conferido")
        self.assertEqual(f["agente_atual"], "agente-codigo #2")
        h = f["historico"]
        self.assertEqual([(x["de"], x["para"]) for x in h], [(None, "nova"), ("nova", "recebida"), ("recebida", "andamento"),
                                                              ("andamento", "conferir"), ("conferir", "feita")])
        self.assertEqual([x["por"] for x in h], ["dono", "gestor", "gestor", "gestor", "dono"])
        self.assertEqual([x["em"] for x in h], [1000.0, 1100.0, 1200.0, 1300.0, 1400.0])
        self.assertEqual(h[2]["agente"], "agente-codigo #2")
        self.assertEqual(h[2]["nota"], "começando")

    def test_recusar_e_reabrir(self):
        tid = tarefas_gestor.criar(self.slug, "Fazer Y")["id"]
        tarefas_gestor.mudar_estado(self.slug, tid, "andamento", "gestor", "ag")
        self.assertEqual(tarefas_gestor.mudar_estado(self.slug, tid, "recusada", "dono", nota="não era isso")["estado"], "recusada")
        r = tarefas_gestor.mudar_estado(self.slug, tid, "nova", "dono", nota="refaça")
        self.assertEqual((r["estado"], r["agente_atual"]), ("nova", ""))   # voltou para a fila: ninguém está com ela
        self.assertEqual(len(r["historico"]), 4)

    def test_estado_invalido_e_tarefa_inexistente(self):
        tid = tarefas_gestor.criar(self.slug, "Z")["id"]
        with self.assertRaises(ValueError):
            tarefas_gestor.mudar_estado(self.slug, tid, "voando")
        with self.assertRaises(ValueError):
            tarefas_gestor.mudar_estado(self.slug, "n-naoexiste", "feita")
        self.assertEqual(tarefas_gestor.achar(self.slug, tid)["estado"], "nova")

    def test_editar_e_nao_editar_terminada(self):
        tid = tarefas_gestor.criar(self.slug, "Antes", prioridade="baixa")["id"]
        e = tarefas_gestor.editar(self.slug, tid, {"titulo": "Depois", "prioridade": "urgente", "pontos": [PONTO_FUNCAO]})
        self.assertEqual((e["titulo"], e["prioridade"], len(e["pontos"])), ("Depois", "urgente", 1))
        self.assertIn("editou", e["historico"][-1]["nota"])
        with self.assertRaises(ValueError):
            tarefas_gestor.editar(self.slug, tid, {})
        tarefas_gestor.mudar_estado(self.slug, tid, "feita", "dono")
        with self.assertRaises(ValueError):
            tarefas_gestor.editar(self.slug, tid, {"titulo": "Tarde"})

    def test_editar_tipo_de_agente_em_branco_volta_a_sugerir(self):
        tid = tarefas_gestor.criar(self.slug, "Revisar segurança", agente_tipo="mecanico")["id"]
        e = tarefas_gestor.editar(self.slug, tid, {"agente_tipo": ""})
        self.assertEqual((e["agente_tipo"], e["agente_sugerido"]), ("critico", True))
        e = tarefas_gestor.editar(self.slug, tid, {"agente_tipo": "mecanico"})
        self.assertEqual((e["agente_tipo"], e["agente_sugerido"]), ("mecanico", False))

    def test_listar_filtra_e_ordena(self):
        a = tarefas_gestor.criar(self.slug, "Baixa antiga", prioridade="baixa", agora=10.0)["id"]
        b = tarefas_gestor.criar(self.slug, "Urgente", prioridade="urgente", agora=20.0)["id"]
        c = tarefas_gestor.criar(self.slug, "Feita", agora=30.0)["id"]
        tarefas_gestor.mudar_estado(self.slug, c, "feita", "dono")
        ordem = [t["id"] for t in tarefas_gestor.listar(self.slug)]
        self.assertEqual(ordem, [b, a, c])                                   # urgente antes; terminadas por último
        self.assertEqual([t["id"] for t in tarefas_gestor.listar(self.slug, incluir_finais=False)], [b, a])
        self.assertEqual([t["id"] for t in tarefas_gestor.listar(self.slug, estado="feita")], [c])
        self.assertEqual([t["id"] for t in tarefas_gestor.listar(self.slug, prioridade="baixa")], [a])
        self.assertEqual([t["id"] for t in tarefas_gestor.listar(self.slug, busca="urgen")], [b])

    def test_contagem(self):
        a = tarefas_gestor.criar(self.slug, "A")["id"]
        b = tarefas_gestor.criar(self.slug, "B")["id"]
        tarefas_gestor.criar(self.slug, "C")
        tarefas_gestor.mudar_estado(self.slug, a, "conferir")
        tarefas_gestor.mudar_estado(self.slug, b, "feita")
        c = tarefas_gestor.contagem(self.slug)
        self.assertEqual((c["nova"], c["conferir"], c["feita"], c["abertas"], c["do_dono_abertas"]), (1, 1, 1, 2, 2))


class TesteMigracao(amb.MundoFalso, unittest.TestCase):
    """tarefas.json no formato antigo (só as tarefas de propostas aprovadas)."""

    def setUp(self):
        self.montar_mundo("LojaMigra")
        limpar_arquivos(self.slug)
        self.arq = config.pasta_projeto(self.slug) / "tarefas.json"
        self.antigo = {"v": 1, "itens": {
            "t-aaaaaaaaaa": {"id": "t-aaaaaaaaaa", "proposta_id": "aaaaaaaaaa", "titulo": "Quebrar arquivo grande", "motivo": "Tem 3000 linhas.",
                             "esforco": "M", "risco": "baixo", "criada_em": 1000.0, "estado": "aberta", "nota": "ok", "origem": "projeto"},
            "t-bbbbbbbbbb": {"id": "t-bbbbbbbbbb", "proposta_id": "bbbbbbbbbb", "titulo": "Já feita", "motivo": "m", "esforco": "P", "risco": "baixo",
                             "criada_em": 900.0, "estado": "feita", "feita_em": 950.0, "nota_final": "feito no commit 123", "origem": "projeto"}}}
        self.arq.write_text(json.dumps(self.antigo), encoding="utf-8")
        self.bytes_antes = self.arq.read_bytes()

    def tearDown(self):
        self.desmontar_mundo()

    def test_leitura_preenche_o_que_falta_sem_reescrever_o_arquivo(self):
        lista = {t["id"]: t for t in tarefas_gestor.listar(self.slug)}
        a = lista["t-aaaaaaaaaa"]
        self.assertEqual(a["estado"], "nova")                                # "aberta" vale como nova
        self.assertEqual((a["prioridade"], a["pontos"], a["agente_tipo"]), ("normal", [], ""))
        self.assertEqual(a["descricao"], "Tem 3000 linhas.")
        self.assertTrue(a["da_proposta"])
        self.assertEqual([h["para"] for h in a["historico"]], ["nova"])
        b = lista["t-bbbbbbbbbb"]
        self.assertEqual(b["estado"], "feita")
        self.assertEqual([h["para"] for h in b["historico"]], ["nova", "feita"])
        self.assertEqual(self.arq.read_bytes(), self.bytes_antes)           # só ler não mexe no arquivo

    def test_visao_antiga_continua_igual(self):
        self.assertEqual([(t["id"], t["estado"]) for t in propostas.tarefas(self.slug)], [("t-aaaaaaaaaa", "aberta"), ("t-bbbbbbbbbb", "feita")])
        self.assertEqual(propostas.contagem(self.slug)["tarefas_abertas"], 1)

    def test_mudar_uma_tarefa_antiga_preserva_os_campos_antigos(self):
        tarefas_gestor.mudar_estado(self.slug, "t-aaaaaaaaaa", "andamento", "gestor", "ag1", "pegou")
        bruto = json.loads(self.arq.read_text(encoding="utf-8"))["itens"]["t-aaaaaaaaaa"]
        for k in ("proposta_id", "motivo", "esforco", "risco", "nota", "origem", "criada_em"):
            self.assertEqual(bruto[k], self.antigo["itens"]["t-aaaaaaaaaa"][k], k)
        self.assertEqual(bruto["estado"], "andamento")
        self.assertEqual([h["para"] for h in bruto["historico"]], ["nova", "andamento"])     # histórico sintetizado + a mudança nova
        # a aba Análise (visão antiga) continua achando a tarefa aberta, e o fluxo antigo de concluir segue valendo
        self.assertEqual(propostas.tarefas(self.slug)[0]["estado"], "aberta")
        propostas.concluir_tarefa(self.slug, "t-aaaaaaaaaa", "feito")
        self.assertEqual(propostas.contagem(self.slug)["tarefas_abertas"], 0)
        depois = tarefas_gestor.achar(self.slug, "t-aaaaaaaaaa")
        self.assertEqual((depois["estado"], depois["nota_final"]), ("feita", "feito"))
        self.assertEqual(depois["historico"][-1]["para"], "feita")

    def test_tarefa_do_dono_nao_aparece_na_visao_antiga(self):
        tarefas_gestor.criar(self.slug, "Do dono")
        self.assertEqual(len(propostas.tarefas(self.slug)), 2)
        self.assertEqual(len(tarefas_gestor.listar(self.slug)), 3)

    def test_recusada_aparece_como_recusada_na_visao_antiga(self):
        tarefas_gestor.mudar_estado(self.slug, "t-aaaaaaaaaa", "recusada", "dono")
        self.assertEqual({t["id"]: t["estado"] for t in propostas.tarefas(self.slug)}["t-aaaaaaaaaa"], "recusada")
        self.assertEqual(propostas.contagem(self.slug)["tarefas_abertas"], 0)

    def test_proposta_aprovada_vira_tarefa_nova(self):
        p = propostas.proposta("projeto", "x", "Melhorar y", "porque sim", "P", "baixo")
        propostas.sincronizar(self.slug, [p])
        propostas.decidir(self.slug, p["id"], True)
        t = [x for x in tarefas_gestor.listar(self.slug) if x["id"] == "t-" + p["id"]][0]
        self.assertEqual(t["estado"], "nova")
        self.assertEqual(tarefas_gestor.contagem(self.slug)["nova"], 2)

    def test_arquivo_quebrado_nao_derruba(self):
        self.arq.write_text("{isso nao e json", encoding="utf-8")
        self.assertEqual(tarefas_gestor.listar(self.slug), [])
        t = tarefas_gestor.criar(self.slug, "Depois do arquivo quebrado")
        self.assertEqual(len(tarefas_gestor.listar(self.slug)), 1)
        self.assertEqual(t["estado"], "nova")


class TesteTextoParaOGestor(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo("LojaTexto")
        limpar_arquivos(self.slug)
        gravar_mapa(self.slug)

    def tearDown(self):
        self.desmontar_mundo()

    def test_sem_tarefas_o_texto_e_vazio(self):
        self.assertEqual(tarefas_gestor.texto_para_contexto(self.slug), "")
        self.assertEqual(tarefas_gestor.texto_novas(self.slug), "")

    def test_so_as_novas_entram_e_o_texto_e_curto(self):
        a = tarefas_gestor.criar(self.slug, "Corrigir o frete", "descrição longa " * 50, "alta", [PONTO_FUNCAO, {"tipo": "grupo", "nome": "Servidor"}])["id"]
        b = tarefas_gestor.criar(self.slug, "Já recebida")["id"]
        c = tarefas_gestor.criar(self.slug, "Em andamento")["id"]
        tarefas_gestor.mudar_estado(self.slug, b, "recebida")
        tarefas_gestor.mudar_estado(self.slug, c, "andamento")
        txt = tarefas_gestor.texto_para_contexto(self.slug)
        self.assertIn(a, txt)
        self.assertNotIn(b, txt)
        self.assertNotIn(c, txt)
        self.assertIn("1 tarefa(s) nova(s)", txt)
        self.assertIn("Corrigir o frete", txt)
        self.assertIn("criar_pedido", txt)                                  # ponto do mapa
        self.assertIn("sonnet", txt)                                        # modelo sugerido
        self.assertIn("--estado recebida", txt)                             # como pegar
        self.assertNotIn("descrição longa", txt)                            # a descrição fica para o --novas
        self.assertLess(len(txt), 700)

    def test_muitas_novas_cortam_em_cinco(self):
        for i in range(8):
            tarefas_gestor.criar(self.slug, f"Tarefa número {i}")
        txt = tarefas_gestor.texto_para_contexto(self.slug)
        self.assertEqual(txt.count("\n- n-"), 5)
        self.assertIn("e mais 3", txt)

    def test_contexto_nunca_levanta_erro(self):
        tarefas_gestor.criar(self.slug, "Algo")
        with mock.patch.object(tarefas_gestor, "listar", side_effect=OSError("disco")):
            self.assertEqual(tarefas_gestor.texto_para_contexto(self.slug), "")

    def test_texto_detalhado_traz_ponto_arquivos_agente_modelo_e_revisor(self):
        tarefas_gestor.criar(self.slug, "Revisar segurança do login", "Ver o token.", "urgente",
                             [PONTO_FUNCAO, {"tipo": "grupo", "nome": "Servidor"}, {"tipo": "arquivo", "nome": "util.py", "arquivo": "src/util.py"}])
        txt = tarefas_gestor.texto_novas(self.slug)
        for trecho in ["prioridade urgente", "Revisar segurança do login", "Ver o token.", 'função "criar_pedido" (src/api.py:12, grupo Servidor)',
                       'grupo "Servidor": src/api.py', "arquivo src/util.py", "Arquivos envolvidos: src/api.py, src/util.py", "modelo sugerido opus",
                       "quem revisa:", "Criada pelo dono", "--estado recebida"]:
            self.assertIn(trecho, txt)

    def test_itens_da_fila_precisa_de_voce(self):
        p = projetos.achar(self.slug)
        a = tarefas_gestor.criar(self.slug, "Para conferir")["id"]
        tarefas_gestor.criar(self.slug, "Esperando")
        tarefas_gestor.mudar_estado(self.slug, a, "conferir")
        itens = tarefas_gestor.itens_fila(p)
        niveis = {i["nivel"] for i in itens}
        self.assertEqual(niveis, {"acao", "info"})
        self.assertTrue(all(i["aba"] == "tarefas" and i["projeto"] == self.slug for i in itens))
        self.assertIn("a conferir", itens[0]["titulo"])
        # parada há mais de 24 h vira aviso
        tarefas_gestor.criar(self.slug, "Antiga", agora=1.0)
        self.assertIn("aviso", {i["nivel"] for i in tarefas_gestor.itens_fila(p)})

    def test_precisa_de_voce_do_painel_inclui_as_tarefas(self):
        from cerebro import painel
        a = tarefas_gestor.criar(self.slug, "Para conferir")["id"]
        tarefas_gestor.mudar_estado(self.slug, a, "conferir")
        titulos = [i["titulo"] for i in painel.fila(config.ler_config())]
        self.assertTrue(any("tarefa(s) a conferir" in t for t in titulos), titulos)


class TesteMapaPontos(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo("LojaMapa")
        limpar_arquivos(self.slug)

    def tearDown(self):
        self.desmontar_mundo()

    def test_sem_mapa(self):
        self.assertEqual(tarefas_gestor.pontos_do_mapa(self.slug, "x"), {"mapa": False, "pontos": []})
        self.assertEqual(tarefas_gestor.arquivos_do_grupo(self.slug, "Servidor"), [])

    def test_lista_busca_grupos_arquivos_e_funcoes(self):
        gravar_mapa(self.slug)
        d = tarefas_gestor.pontos_do_mapa(self.slug)
        self.assertTrue(d["mapa"])
        self.assertEqual([p["nome"] for p in d["pontos"]], ["Servidor", "Utilitários"])        # o maior primeiro
        d = tarefas_gestor.pontos_do_mapa(self.slug, "pedido")
        self.assertEqual((d["pontos"][0]["tipo"], d["pontos"][0]["nome"], d["pontos"][0]["arquivo"], d["pontos"][0]["linha"], d["pontos"][0]["grupo"]),
                         ("função", "criar_pedido", "src/api.py", 12, "Servidor"))
        nomes = [(p["tipo"], p["nome"]) for p in tarefas_gestor.pontos_do_mapa(self.slug, "util")["pontos"]]
        self.assertIn(("grupo", "Utilitários"), nomes)
        self.assertIn(("arquivo", "util.py"), nomes)
        self.assertEqual(tarefas_gestor.arquivos_do_grupo(self.slug, "Servidor"), ["src/api.py"])

    def test_mapa_quebrado_nao_derruba(self):
        pasta = config.CASA / "projetos" / self.slug / "mapa"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "dados.js").write_text("window.CEREBRO = {nao e json", encoding="utf-8")
        self.assertEqual(tarefas_gestor.pontos_do_mapa(self.slug, "a")["mapa"], False)

    def test_mapa_novo_invalida_o_cache(self):
        gravar_mapa(self.slug)
        self.assertEqual(len(tarefas_gestor.pontos_do_mapa(self.slug)["pontos"]), 2)
        outro = dict(DADOS_MAPA, grupos=DADOS_MAPA["grupos"] + [{"n": "Novo", "d": 0, "t": 0, "c": 0}])
        gravar_mapa(self.slug, outro)
        self.assertEqual(len(tarefas_gestor.pontos_do_mapa(self.slug)["pontos"]), 3)


class TesteCliTarefas(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo("ProjetoTarefas")
        limpar_arquivos(self.slug)

    def tearDown(self):
        self.desmontar_mundo()

    def rodar(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                codigo = cerebro_cli.main(list(args))
            except SystemExit as e:                                         # argparse recusando uma opção
                codigo = e.code
        return codigo, out.getvalue(), err.getvalue()

    def test_novas_tarefa_e_historico(self):
        codigo, out, _ = self.rodar("tarefas", "ProjetoTarefas", "--novas")
        self.assertEqual((codigo, out.strip()), (0, "Nenhuma tarefa nova."))
        t = tarefas_gestor.criar(self.slug, "Corrigir o frete", "Somando dois itens dobra.", "alta", [PONTO_FUNCAO])
        codigo, out, _ = self.rodar("tarefas", "ProjetoTarefas", "--novas")
        self.assertEqual(codigo, 0)
        for trecho in [t["id"], "Corrigir o frete", "criar_pedido", "src/api.py", "modelo sugerido sonnet", "quem revisa"]:
            self.assertIn(trecho, out)
        codigo, out, _ = self.rodar("tarefa", "ProjetoTarefas", t["id"], "--estado", "recebida", "--agente", "Gestor", "--nota", "li")
        self.assertEqual(codigo, 0)
        self.assertIn("recebida pelo gestor", out)
        self.assertEqual(self.rodar("tarefas", "ProjetoTarefas", "--novas")[1].strip(), "Nenhuma tarefa nova.")
        self.rodar("tarefa", "ProjetoTarefas", t["id"], "--estado", "andamento", "--agente", "agente-codigo")
        self.rodar("tarefa", "ProjetoTarefas", t["id"], "--estado", "conferir", "--nota", "testes ok")
        h = tarefas_gestor.achar(self.slug, t["id"])["historico"]
        self.assertEqual([(x["por"], x["para"], x["agente"]) for x in h[1:]], [("gestor", "recebida", "Gestor"), ("gestor", "andamento", "agente-codigo"),
                                                                              ("gestor", "conferir", "")])
        codigo, out, _ = self.rodar("tarefas", "ProjetoTarefas")
        self.assertIn("[conferir]", out)

    def test_erros(self):
        codigo, _, err = self.rodar("tarefa", "ProjetoTarefas", "n-naoexiste", "--estado", "feita")
        self.assertEqual(codigo, 2)
        self.assertIn("não encontrada", err)
        codigo, _, err = self.rodar("tarefa", "ProjetoTarefas", "n-x")
        self.assertEqual(codigo, 2)
        self.assertIn("--estado", err)
        self.assertEqual(self.rodar("tarefa", "ProjetoTarefas", "n-x", "--estado", "voando")[0], 2)

    def test_tarefa_feita_antiga_e_estado(self):
        p = propostas.proposta("projeto", "k", "Melhorar", "motivo", "P", "baixo")
        propostas.sincronizar(self.slug, [p])
        propostas.decidir(self.slug, p["id"], True)
        _, out, _ = self.rodar("tarefas", "ProjetoTarefas")
        self.assertIn("t-" + p["id"], out)
        self.assertIn("P/baixo", out)                                      # o formato antigo mostra esforço e risco
        _, out, _ = self.rodar("estado", "ProjetoTarefas")
        self.assertIn("Tarefas abertas: 1", out)
        self.assertEqual(self.rodar("tarefa-feita", "ProjetoTarefas", "t-" + p["id"], "--nota", "ok")[0], 0)
        self.assertEqual(self.rodar("tarefas", "ProjetoTarefas")[1].strip(), "Nenhuma tarefa aberta.")


class TesteRotasTarefas(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        limpar_arquivos(self.slug)

    def url(self, fim=""):
        return f"/api/p/{self.slug}/tarefas-gestor{fim}"

    async def test_tudo_exige_cookie_e_origin(self):
        for caminho in [self.url(), self.url("/pontos")]:
            self.assertEqual((await self.http.get(self.base + caminho)).status, 401)
        await self.entrar()
        self.assertEqual((await self.http.get(self.base + self.url(), headers={"Origin": "http://evil.com"})).status, 403)
        self.assertEqual((await self.post(self.url(), {"titulo": "x"}, origem=False)).status, 403)
        self.assertEqual((await self.http.post(self.base + self.url(), data="titulo=x", headers={"Origin": self.base})).status, 415)
        self.assertEqual((await self.http.post(self.base + self.url(), data="{}", headers={"Origin": "http://evil.com", "Content-Type": "application/json"})).status, 403)
        self.assertEqual(tarefas_gestor.listar(self.slug), [])             # as recusadas não gravaram nada

    async def test_sem_cookie_o_post_tambem_e_negado(self):
        r = await self.post(self.url(), {"titulo": "x"})
        self.assertEqual(r.status, 401)
        self.assertEqual(tarefas_gestor.listar(self.slug), [])

    async def test_criar_listar_filtrar_e_mudar(self):
        await self.entrar()
        r = await self.post(self.url(), {"titulo": "Corrigir o frete", "descricao": "d", "prioridade": "alta", "pontos": [PONTO_FUNCAO], "agente_tipo": ""})
        self.assertEqual(r.status, 200)
        d = await r.json()
        tid = d["item"]["id"]
        self.assertEqual((d["item"]["estado"], d["item"]["agente"]["modelo"], d["contagem"]["nova"]), ("nova", "sonnet", 1))
        lista = await (await self.http.get(self.base + self.url())).json()
        self.assertEqual([t["id"] for t in lista["itens"]], [tid])
        self.assertEqual({a["id"] for a in lista["opcoes"]["agentes"]}, {"critico", "codigo", "mecanico"})
        self.assertIn("revisor", lista["opcoes"]["agentes"][0])
        self.assertEqual((await (await self.http.get(self.base + self.url("?estado=feita"))).json())["itens"], [])
        self.assertEqual((await self.http.get(self.base + self.url("?estado=voando"))).status, 400)
        self.assertEqual((await self.http.get(self.base + self.url("?prioridade=xx"))).status, 400)
        r = await self.post(self.url(f"/{tid}"), {"acao": "estado", "estado": "conferir", "nota": "pronto"})
        self.assertEqual((r.status, (await r.json())["item"]["estado"]), (200, "conferir"))
        r = await self.post(self.url(f"/{tid}"), {"acao": "estado", "estado": "feita"})
        item = (await r.json())["item"]
        self.assertEqual([h["por"] for h in item["historico"]], ["dono", "dono", "dono"])     # a página sempre vale como "dono"
        r = await self.post(self.url(f"/{tid}"), {"acao": "editar", "titulo": "Tarde"})
        self.assertEqual(r.status, 400)                                                         # terminada: não edita

    async def test_dono_nao_consegue_se_passar_pelo_gestor(self):
        await self.entrar()
        tid = (await (await self.post(self.url(), {"titulo": "X"})).json())["item"]["id"]
        await self.post(self.url(f"/{tid}"), {"acao": "estado", "estado": "recebida", "por": "gestor"})
        item = tarefas_gestor.achar(self.slug, tid)
        self.assertEqual(item["historico"][-1]["por"], "dono")

    async def test_erros_da_criacao_e_da_mudanca(self):
        await self.entrar()
        for corpo in [{}, {"titulo": ""}, {"titulo": "x", "prioridade": "agora"}, {"titulo": "x", "agente_tipo": "zzz"}, {"titulo": "x", "pontos": "a"},
                      {"titulo": 5}]:
            self.assertEqual((await self.post(self.url(), corpo)).status, 400, corpo)
        self.assertEqual((await self.post(self.url("/n-nao"), {"acao": "estado", "estado": "feita"})).status, 404)
        self.assertEqual((await self.post(self.url("/n-nao"), {"acao": "voar"})).status, 400)
        self.assertEqual((await self.post(self.url("/..%2Fx"), {"acao": "estado", "estado": "feita"})).status, 400)
        self.assertEqual((await self.post("/api/p/Inexistente/tarefas-gestor", {"titulo": "x"})).status, 404)
        self.assertEqual((await self.http.get(self.base + "/api/p/..%2Fx/tarefas-gestor")).status, 400)

    async def test_pontos_do_mapa_pela_api(self):
        await self.entrar()
        d = await (await self.http.get(self.base + self.url("/pontos"))).json()
        self.assertEqual(d, {"mapa": False, "pontos": []})
        gravar_mapa(self.slug)
        d = await (await self.http.get(self.base + self.url("/pontos?q=pedido"))).json()
        self.assertEqual(d["pontos"][0]["nome"], "criar_pedido")
        d = await (await self.http.get(self.base + self.url("/pontos"))).json()
        self.assertEqual([p["nome"] for p in d["pontos"]], ["Servidor", "Utilitários"])

    async def test_contador_no_cartao_na_visao_e_na_fila(self):
        await self.entrar()
        tid = (await (await self.post(self.url(), {"titulo": "X"})).json())["item"]["id"]
        await self.post(self.url(f"/{tid}"), {"acao": "estado", "estado": "conferir"})
        cartoes = (await (await self.http.get(f"{self.base}/api/projetos")).json())["projetos"]
        self.assertEqual(cartoes[0]["tarefas"]["conferir"], 1)
        visao = await (await self.http.get(f"{self.base}/api/p/{self.slug}/visao")).json()
        self.assertEqual(visao["tarefas"]["abertas"], 1)
        fila = await (await self.http.get(f"{self.base}/api/fila")).json()
        self.assertTrue(any("tarefa(s) a conferir" in i["titulo"] for i in fila["itens"]))

    async def test_arquivos_estaticos_novos_servidos(self):
        await self.entrar()
        for caminho in ["/static/tarefas.js", "/static/tarefas.css"]:
            self.assertEqual((await self.http.get(self.base + caminho)).status, 200, caminho)
        gravar_mapa(self.slug)
        self.assertEqual((await self.http.get(f"{self.base}/mapa/{self.slug}/tarefa.js")).status, 200)


class TesteArmazem(unittest.TestCase):
    def test_gravacao_mantem_formato_v1(self):
        # o arquivo continua {"v": 1, "itens": {...}} depois de uma criação, como o código antigo espera
        amb.garantir_isolamento()
        slug = "C--Falso-ArquivoV1"
        arq = config.pasta_projeto(slug) / "tarefas.json"
        amb.apagar(arq)
        tarefas_gestor.criar(slug, "Qualquer")
        d = armazem.ler_json(arq)
        self.assertEqual(d["v"], 1)
        self.assertEqual(len(d["itens"]), 1)


if __name__ == "__main__":
    unittest.main()
