"""Agentes por tipo de tarefa, departamentos do mapa, títulos das sessões, mapa que se atualiza sozinho e vigia de novidades."""
import json
import os
import time
import unittest

from testes import _ambiente as amb
from cerebro import config, mapa_auto, novidades, projetos, propostas, regras_agentes, titulos
from cerebro import departamentos
from testes.test_servidor import Base

REGRAS = config.AGENTES_REGRAS_PADRAO


class TesteRegrasAgentes(unittest.TestCase):
    def test_tipos_padrao(self):
        self.assertEqual({r["id"]: r["modelo"] for r in REGRAS}, {"critico": "opus", "codigo": "sonnet", "mecanico": "haiku"})

    def test_classificacao_por_palavra(self):
        casos = {"Buscar onde fica o botão": "mecanico", "Escrever os testes do módulo": "codigo", "Corrigir bug na tela": "codigo",
                 "Revisão de segurança do login": "critico", "Documentação e resumo": "mecanico", "Coisa sem palavra conhecida": None}
        for descricao, esperado in casos.items():
            r = regras_agentes.classificar(descricao, "general-purpose", REGRAS)
            self.assertEqual(r["id"] if r else None, esperado, descricao)

    def test_critico_ganha_de_codigo(self):
        self.assertEqual(regras_agentes.classificar("Implementar o login com senha", "", REGRAS)["id"], "critico")

    def test_agente_de_leitura_e_mecanico(self):
        self.assertEqual(regras_agentes.classificar("qualquer coisa", "Explore", REGRAS)["id"], "mecanico")

    def test_situacao_do_modelo_usado(self):
        a = regras_agentes.aplicar("Buscar arquivos", "", "claude-haiku-5-5", REGRAS)
        self.assertEqual((a["regra"], a["situacao"], a["modelo_previsto"]), ("mecanico", "conforme", "haiku"))
        self.assertEqual(regras_agentes.aplicar("Buscar arquivos", "", "claude-opus-5-5", REGRAS)["situacao"], "acima")
        self.assertEqual(regras_agentes.aplicar("Revisão de segurança", "", "claude-haiku-5-5", REGRAS)["situacao"], "abaixo")
        self.assertEqual(regras_agentes.aplicar("Buscar arquivos", "", "", REGRAS)["situacao"], "desconhecido")
        self.assertEqual(regras_agentes.aplicar("Coisa estranha", "", "claude-haiku-5-5", REGRAS)["situacao"], "sem_regra")

    def test_validacao_da_tabela(self):
        boa = [{"id": "a", "nome": "A", "modelo": "Haiku", "revisor": "gestor", "palavras": "x, y;z"}]
        self.assertEqual(regras_agentes.validar_regras(boa)[0]["palavras"], ["x", "y", "z"])
        ruins = [[], "texto", [{"id": "A B", "nome": "n", "modelo": "haiku", "revisor": "r", "palavras": []}],
                 [{"id": "a", "nome": "n", "modelo": "gpt", "revisor": "r", "palavras": []}],
                 [{"id": "a", "nome": "", "modelo": "haiku", "revisor": "r", "palavras": []}],
                 boa + boa]
        for r in ruins:
            with self.assertRaises(ValueError):
                regras_agentes.validar_regras(r)

    def test_previa_vai_so_para_a_casa_do_cerebro_e_substitui_a_anterior(self):
        slug = "ProjetoPrevia"
        d = regras_agentes.gerar_previa(slug, "Projeto", REGRAS)
        pasta = config.CASA / "projetos" / slug / "previa_agentes"
        self.assertEqual(d["pasta"], str(pasta))
        self.assertEqual(sorted(p.name for p in pasta.iterdir()), ["cerebro-codigo.md", "cerebro-critico.md", "cerebro-mecanico.md"])
        texto = (pasta / "cerebro-mecanico.md").read_text(encoding="utf-8")
        self.assertIn("model: haiku", texto)
        self.assertIn("gestor confere", texto.lower())
        regras_agentes.gerar_previa(slug, "Projeto", REGRAS[:1])
        self.assertEqual([p.name for p in pasta.iterdir()], ["cerebro-critico.md"])
        self.assertEqual([x["arquivo"] for x in regras_agentes.previa_existente(slug)["arquivos"]], ["cerebro-critico.md"])


class TesteAgentesNaTela(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.criar_subagente("a1a2a3a4a5", "Buscar arquivos de configuração", modelo="claude-haiku-5-5")
        self.criar_subagente("b1b2b3b4b5", "Revisão de segurança do login", modelo="claude-haiku-5-5")

    def tearDown(self):
        self.desmontar_mundo()

    def test_agentes_ao_vivo_mostram_a_regra_aplicada_a_cada_um(self):
        from cerebro import agentes, indice
        indice.indexar_projeto(self.slug)
        cfg = config.ler_config()
        dados = agentes.montar(self.slug, cfg["precos"], cfg["gestoras"][self.slug]["conversa"], todas=True, cfg=cfg)
        subs = {s["descricao"]: s for ses in dados["sessoes"] for s in ses["subagentes"]}
        self.assertEqual(subs["Buscar arquivos de configuração"]["regra"]["situacao"], "conforme")
        self.assertEqual(subs["Revisão de segurança do login"]["regra"]["regra"], "critico")
        self.assertEqual(subs["Revisão de segurança do login"]["regra"]["situacao"], "abaixo")


class TesteDepartamentos(unittest.TestCase):
    def test_validar_e_normalizar(self):
        conf = {"modo": "regras", "deptos": [{"nome": "Servidor", "cor": "#FF0000", "caminhos": "server.py, api/"}, {"nome": "Tela", "caminhos": ["public/"]}]}
        v = departamentos.validar(conf)
        self.assertEqual(v["deptos"][0]["cor"], "#ff0000")
        self.assertEqual(v["deptos"][0]["caminhos"], ["server.py", "api/"])
        self.assertTrue(v["deptos"][1]["cor"].startswith("#"))             # cor automática
        self.assertEqual(v["padrao"], "Outros")

    def test_invalidos(self):
        ruins = [None, {"modo": "outro"}, {"modo": "regras", "deptos": []}, {"modo": "regras", "deptos": [{"nome": "A", "cor": "vermelho", "caminhos": []}]},
                 {"modo": "regras", "deptos": [{"nome": "A", "caminhos": []}, {"nome": "a", "caminhos": []}]}]
        for r in ruins:
            with self.assertRaises(ValueError):
                departamentos.validar(r)

    def test_esquema_pelo_caminho(self):
        e = departamentos.deptos.esquema_regras({"modo": "regras", "deptos": [
            {"nome": "Servidor", "cor": "#111111", "caminhos": ["server.py", "api/"]}, {"nome": "Testes", "cor": "#222222", "caminhos": ["*.test.js", "testes/"]}]})
        self.assertEqual(e.nomes[e.indice("api/rotas.py")], "Servidor")
        self.assertEqual(e.nomes[e.indice("web/a.test.js")], "Testes")
        self.assertEqual(e.nomes[e.indice("coisa/outra.txt")], "Outros")
        self.assertEqual(e.nomes[e.indice("Server.py")], "Servidor")           # sem diferenciar maiúsculas

    def test_esquema_automatico_por_pastas(self):
        e = departamentos.deptos.esquema_pastas(["a/x.py", "a/y.py", "b/z.py", "raiz.txt"])
        self.assertEqual(set(e.nomes), {"a", "b", "Raiz"})

    def test_padroes_do_config(self):
        cfg = config.ler_config()
        self.assertEqual(departamentos.do_projeto(cfg, amb.SLUG_EXEMPLO), {"modo": "pastas"})       # sem entrada: uma cor por pasta de topo
        self.assertEqual(departamentos.do_projeto(cfg, "OutroProjeto"), {"modo": "pastas"})

    def test_salvar_e_voltar_ao_automatico(self):
        departamentos.salvar("ProjX", {"modo": "regras", "deptos": [{"nome": "A", "caminhos": ["a/"]}]})
        self.assertEqual(departamentos.do_projeto(config.ler_config(), "ProjX")["modo"], "regras")
        departamentos.salvar("ProjX", None)
        self.assertEqual(departamentos.do_projeto(config.ler_config(), "ProjX")["modo"], "pastas")
        with self.assertRaises(ValueError):
            departamentos.salvar("ProjX", {"modo": "regras", "deptos": "lixo"})


class TesteTitulos(unittest.TestCase):
    def setUp(self):
        self.pasta = amb.BASE / "app_sessoes"
        self.pasta.mkdir(exist_ok=True)
        self.antes = os.environ.get("CEREBRO_APPDATA")
        os.environ["CEREBRO_APPDATA"] = str(self.pasta)
        titulos._cache.update(t=0.0, arquivos={}, mapa={})

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("CEREBRO_APPDATA", None)
        else:
            os.environ["CEREBRO_APPDATA"] = self.antes
        titulos._cache.update(t=0.0, arquivos={}, mapa={})

    def app(self, sessao, titulo, resumo=""):
        (self.pasta / f"local_{sessao}.json").write_text(json.dumps(
            {"cliSessionId": sessao, "title": titulo, "titleSource": "user", "postTurnSummary": {"status_detail": resumo}}), encoding="utf-8")
        titulos._cache.update(t=0.0)

    def test_rotulos_de_organizacao_nao_sao_titulo(self):
        for r in ("### Loja ###", "### Loja (fork)", "***", "=== x ===", "", "Untitled"):
            self.assertTrue(titulos.eh_rotulo(r), r)
        self.assertFalse(titulos.eh_rotulo("Corrigir o login"))

    def test_titulo_do_app_vence(self):
        self.app("s1", "Ajustar o painel", "Ajustei o painel. Depois testei.")
        t = titulos.escolher("x", "s1", {"titulo": "Outro"})
        self.assertEqual((t["titulo"], t["fonte"]), ("Ajustar o painel", "app"))

    def test_rotulo_cai_para_o_resumo_do_app_e_depois_para_a_primeira_mensagem(self):
        self.app("s2", "### Loja ###", "Refiz o formulário de login. Falta testar.")
        t = titulos.escolher("x", "s2", {"titulo": "### Loja ###"})
        self.assertEqual((t["titulo"], t["fonte"]), ("Refiz o formulário de login. Falta testar.", "resumo do app"))
        t = titulos.escolher("x", "sem-app", {"titulo": "### x ###", "primeira": "Preciso de uma tela nova de relatórios"})
        self.assertEqual(t["fonte"], "primeira mensagem")
        self.assertEqual(t["original"], "### x ###")

    def test_apelido_da_gestora_no_lugar_do_rotulo(self):
        self.app("g1", "### Loja ###")
        cfg = {"gestoras": {"slugx": {"conversa": "g1", "nome": "Gestora principal (arquitetura)"}}}
        t = titulos.titulo_da_sessao("slugx", "g1", {}, "", cfg)
        self.assertEqual(t["titulo"], "Gestora principal (arquitetura)")
        self.assertEqual(t["original"], "### Loja ###")
        self.assertNotEqual(titulos.titulo_da_sessao("slugx", "outra", {"primeira": "Oi tudo bem"}, "", cfg)["titulo"], "Gestora principal (arquitetura)")

    def test_sem_nada_usa_o_identificador_e_pasta_ausente_nao_quebra(self):
        os.environ["CEREBRO_APPDATA"] = str(amb.BASE / "nao_existe")
        self.assertEqual(titulos.escolher("x", "abcdef123456", {})["fonte"], "identificador")


class TesteMapaAutomatico(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        mapa_auto._estado.clear()
        self.graph = self.real / "graphify-out" / "graph.json"
        self.graph.parent.mkdir()
        self.graph.write_text("{}", encoding="utf-8")
        self.dados = config.CASA / "projetos" / self.slug / "mapa" / "dados.js"
        self.chamadas = []

    def tearDown(self):
        self.desmontar_mundo()

    def fabrica(self, ok=True):
        def gerar(caminho):
            self.chamadas.append(caminho)
            if ok:
                self.dados.parent.mkdir(parents=True, exist_ok=True)
                self.dados.write_text("x", encoding="utf-8")
            return ok, "" if ok else "deu erro"
        return gerar

    def idade(self, arq, segundos):
        t = time.time() - segundos
        os.utime(arq, (t, t))

    def test_sem_pagina_gera_ao_abrir(self):
        self.idade(self.graph, 60)
        self.assertEqual(mapa_auto.motivo_para_gerar(str(self.real), self.slug), "sem página")
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [self.slug])
        self.assertEqual(len(self.chamadas), 1)

    def test_em_dia_nao_gera(self):
        self.idade(self.graph, 120)
        mapa_auto.varrer(gerar_fn=self.fabrica())
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [])
        self.assertEqual(len(self.chamadas), 1)

    def test_graph_mais_novo_que_a_pagina_gera_de_novo(self):
        self.idade(self.graph, 120)
        mapa_auto.varrer(gerar_fn=self.fabrica())
        self.idade(self.dados, 100)
        self.idade(self.graph, 30)
        self.assertEqual(mapa_auto.motivo_para_gerar(str(self.real), self.slug), "mapa novo")
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [self.slug])
        self.assertEqual(len(self.chamadas), 2)

    def test_graph_sendo_escrito_espera_estabilizar(self):
        self.assertEqual(mapa_auto.motivo_para_gerar(str(self.real), self.slug), "")          # acabou de ser escrito
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [])
        self.assertEqual(self.chamadas, [])

    def test_falha_tenta_de_novo_com_espera_crescente_e_mostra_o_erro(self):
        self.idade(self.graph, 60)
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica(ok=False)), [])
        e = mapa_auto.estado(self.slug)
        self.assertEqual(e["falhas"], 1)
        self.assertIn("deu erro", e["ultimo_erro"])
        self.assertIsNotNone(e["proxima_tentativa_em"])
        mapa_auto.varrer(gerar_fn=self.fabrica())                      # ainda dentro da espera: não tenta
        self.assertEqual(len(self.chamadas), 1)
        mapa_auto.varrer(agora=time.time() + 3600, gerar_fn=self.fabrica())
        self.assertEqual(len(self.chamadas), 2)
        self.assertEqual(mapa_auto.estado(self.slug)["falhas"], 0)

    def test_desligado_na_configuracao_nao_gera_mas_forcar_gera(self):
        self.idade(self.graph, 60)
        config.atualizar_config(lambda c: c["rotinas"].__setitem__("mapa_automatico", False))
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [])
        self.assertEqual(mapa_auto.varrer(forcar=True, gerar_fn=self.fabrica()), [self.slug])

    def test_projeto_sem_graphify_e_ignorado(self):
        self.graph.unlink()
        self.assertEqual(mapa_auto.varrer(gerar_fn=self.fabrica()), [])

    def test_estado_do_mapa_mostra_defasagem_para_o_commit(self):
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=str(self.real), check=True)
        (self.real / "a.txt").write_text("a", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(self.real), check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], cwd=str(self.real), check=True, capture_output=True)
        projetos._git_cache.clear()
        self.idade(self.graph, 3600)                                   # mapa de 1 h atrás, commit de agora
        est = projetos.estado_mapa(str(self.real), self.slug)
        self.assertTrue(est["defasado"])
        os.utime(self.graph, None)
        self.assertFalse(projetos.estado_mapa(str(self.real), self.slug)["defasado"])


class TesteNovidades(unittest.TestCase):
    def setUp(self):
        amb.apagar(config.CASA / "novidades.json")
        amb.apagar(config.CASA / "projetos" / propostas.ESCOPO_CEREBRO)
        self.cfg = config.ler_config()

    def rede(self, tags):
        chamadas = []

        def buscar(url):
            chamadas.append(url)
            repo = url.split("/repos/")[1].split("/releases")[0].split("/tags")[0]
            tag = tags.get(repo)
            if tag is None:
                return 404, None
            if "/releases/latest" in url:
                return 200, {"tag_name": tag, "name": tag, "published_at": "2026-10-20T10:00:00Z", "body": "## Novo\n* coisa **boa**",
                             "html_url": f"https://github.com/{repo}/releases/tag/{tag}"}
            return 200, [{"name": tag}]
        buscar.chamadas = chamadas
        return buscar

    def test_so_get_em_paginas_publicas_do_github(self):
        self.assertTrue(novidades.url_permitida("https://api.github.com/repos/anthropics/claude-code/releases/latest"))
        for ruim in ("http://api.github.com/x", "https://evil.com/x", "https://api.github.com.evil.com/x", "https://user:senha@api.github.com/x",
                     "file:///c:/x", "ftp://api.github.com/x"):
            self.assertFalse(novidades.url_permitida(ruim), ruim)
        with self.assertRaises(ValueError):
            novidades.buscar_json("https://evil.com/x")

    def test_primeira_vez_e_ponto_de_partida_e_depois_vira_novidade(self):
        r = novidades.procurar(self.cfg, buscar=self.rede({"anthropics/claude-code": "v2.1.0", "safishamsi/graphify": "v0.3.0"}), agora=1000.0)
        self.assertEqual(r["novas"], [])
        self.assertFalse(any(f["novo"] for f in r["fontes"]))
        r = novidades.procurar(self.cfg, buscar=self.rede({"anthropics/claude-code": "v2.2.0", "safishamsi/graphify": "v0.3.0"}), agora=2000.0)
        novos = [f["id"] for f in r["fontes"] if f["novo"]]
        self.assertEqual(novos, ["claude-code"])
        self.assertTrue(any("v2.2.0" in p["titulo"] for p in r["propostas"]))
        novidades.marcar_visto("claude-code")
        self.assertFalse(any(f["novo"] for f in novidades.montar(self.cfg)["fontes"]))

    def test_sem_rede_avisa_e_nao_quebra(self):
        def sem_rede(url):
            raise OSError("sem conexão")
        r = novidades.procurar(self.cfg, buscar=sem_rede, agora=1000.0)
        self.assertTrue(r["sem_rede"])
        self.assertTrue(r["erros"])
        self.assertEqual(r["novas"], [])
        self.assertTrue(novidades.montar(self.cfg)["sem_rede"])

    def test_resposta_estranha_da_api_nao_derruba(self):
        r = novidades.procurar(self.cfg, buscar=lambda url: (200, ["lixo", 1, None]), agora=1000.0)
        self.assertTrue(r["erros"])

    def test_limite_da_api_publica_explica(self):
        r = novidades.procurar(self.cfg, buscar=lambda url: (403, None), agora=1000.0)
        self.assertTrue(any("limite" in e for e in r["erros"]))

    def test_so_consulta_as_fontes_do_config_e_nao_manda_nada_do_projeto(self):
        buscar = self.rede({"anthropics/claude-code": "v1.0.0"})
        novidades.procurar(self.cfg, buscar=buscar, agora=1000.0)
        for url in buscar.chamadas:
            self.assertTrue(url.startswith("https://api.github.com/repos/"), url)
            self.assertNotIn("?", url.replace("?per_page=1", ""))
        cfg = {**self.cfg, "fontes_novidades": [{"id": "ruim", "repo": "não é repo"}, {"id": "x y", "repo": "a/b"}]}
        self.assertEqual(novidades.fontes_validas(cfg), [])

    def test_comparar_versao(self):
        self.assertEqual(novidades.comparar_versao("ruff 0.17.1", "0.18.0"), "desatualizada")
        self.assertEqual(novidades.comparar_versao("v2.3.0", "v2.3.0"), "atualizada")
        self.assertEqual(novidades.comparar_versao("", "1.0"), "")

    def test_proxima_busca_vem_do_intervalo(self):
        self.assertIsNone(novidades.montar(self.cfg)["proxima_em"])
        novidades.procurar(self.cfg, buscar=self.rede({}), agora=1000.0)
        m = novidades.montar(self.cfg)
        self.assertEqual(m["proxima_em"], 1000.0 + m["intervalo_dias"] * 86400)


class TesteRotasAgentes(Base):
    async def test_previa_de_agentes_e_configuracao(self):
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/agentes/previa", {})
        self.assertEqual(r.status, 200)
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/agentes/previa")).json()
        self.assertEqual(len(d["previa"]["arquivos"]), 3)
        self.assertFalse((self.real / ".claude").exists())                # nada é escrito no projeto
        r = await self.post("/api/config", {"agentes_regras": [{"id": "x", "nome": "X", "modelo": "gpt", "revisor": "r", "palavras": []}]})
        self.assertEqual(r.status, 400)
        r = await self.post("/api/config", {"agentes_regras": [{"id": "x", "nome": "X", "modelo": "haiku", "revisor": "r", "palavras": ["xis"]}]})
        self.assertEqual(r.status, 200)
        self.assertEqual([x["id"] for x in config.ler_config()["agentes_regras"]], ["x"])

    async def test_departamentos_pela_api(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/departamentos")).json()
        self.assertEqual(d["atual"]["modo"], "pastas")
        r = await self.post(f"/api/p/{self.slug}/departamentos", {"conf": {"modo": "regras", "deptos": [{"nome": "Tudo", "caminhos": ["a/"]}]}})
        self.assertEqual(r.status, 200)
        r = await self.post(f"/api/p/{self.slug}/departamentos", {"conf": {"modo": "regras", "deptos": [{"nome": "Ruim", "cor": "azul", "caminhos": []}]}})
        self.assertEqual(r.status, 400)

    async def test_novidades_pela_api_sem_rede_nao_quebra(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/novidades")).json()
        self.assertTrue(d["fontes"])
        antigo = novidades.buscar_json
        novidades.buscar_json = lambda url, timeout=8: (_ for _ in ()).throw(OSError("sem rede"))
        try:
            r = await self.post("/api/novidades/procurar", {})
        finally:
            novidades.buscar_json = antigo
        self.assertEqual(r.status, 200)
        self.assertTrue((await r.json())["sem_rede"])


if __name__ == "__main__":
    unittest.main()


class TesteRevisaoECritica(unittest.TestCase):
    """Visto num projeto real em 29/10/2026: "Revisão independente" não casava com a regra crítica (só "revisar"/"revisão final")."""
    def test_revisao_vai_para_a_regra_critica(self):
        from cerebro import config, regras_agentes
        regras = config.CONFIG_PADRAO["agentes_regras"]
        for d in ("Revisão independente", "revisao de seguranca", "Revisa o PR"):
            self.assertEqual(regras_agentes.classificar(d, "general-purpose", regras)["id"], "critico", d)
