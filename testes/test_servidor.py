"""Token, cookie, Host e Origin do servidor, mais as rotas principais com dados de mentira."""
import json
import time
import unittest

from aiohttp import ClientSession, CookieJar
from aiohttp.test_utils import TestServer

from testes import _ambiente as amb
from cerebro import config, projetos, servidor
from testes._ambiente import linha_assistente, linha_usuario


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        amb.apagar(config.PROJETOS_CLAUDE)
        amb.apagar(amb.BASE / "mundo")
        amb.reiniciar_memoria()
        (amb.BASE / "mundo" / "Desktop" / "Falso").mkdir(parents=True)
        self.real = amb.BASE / "mundo" / "Desktop" / "Falso"
        self.slug = projetos.codificar(self.real)
        pasta = config.PROJETOS_CLAUDE / self.slug
        (pasta / "memory").mkdir(parents=True)
        (pasta / "memory" / "MEMORY.md").write_text("- [regra](regra.md) — REGRA de teste\n", encoding="utf-8")
        (pasta / "memory" / "regra.md").write_text("---\nname: regra\ndescription: REGRA 29/10: sempre testar\nmetadata:\n  type: feedback\n---\nCorpo com a palavra zebra e senha=abc12345xyz\n", encoding="utf-8")
        (pasta / "sessA.jsonl").write_text(
            json.dumps({"type": "user", "cwd": str(self.real)}) + "\n" + linha_usuario("Faça o teste")
            + linha_assistente("m1", ts="2026-10-28T12:00:00.000Z", conteudo=[{"type": "text", "text": "feito"}]), encoding="utf-8")
        (self.real / "AGENTS.md").write_text("# regras do projeto\n", encoding="utf-8")
        self.saved_home = projetos.HOME
        projetos.HOME = amb.BASE / "mundo"
        projetos.descobrir(forcar=True)
        import socket
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.porta = sk.getsockname()[1]
        self.app = servidor.criar_app(self.porta, token="t" * 43)
        self.srv = TestServer(self.app, port=self.porta)
        await self.srv.start_server()
        self.base = f"http://127.0.0.1:{self.porta}"
        self.http = ClientSession(cookie_jar=CookieJar(unsafe=True))

    async def asyncTearDown(self):
        await self.http.close()
        await self.srv.close()
        projetos.HOME = self.saved_home
        projetos.descobrir(forcar=True)

    async def entrar(self):
        r = await self.http.get(f"{self.base}/?t={'t' * 43}", allow_redirects=False)
        return r

    async def post(self, caminho, corpo, origem=True):
        h = {"Content-Type": "application/json"}
        if origem:
            h["Origin"] = self.base
        return await self.http.post(self.base + caminho, data=json.dumps(corpo), headers=h)


class TesteSeguranca(Base):
    async def test_sem_cookie_tudo_e_negado(self):
        for caminho in ["/", "/api/projetos", "/api/config", f"/api/p/{self.slug}/visao", "/static/app.js", f"/mapa/{self.slug}/"]:
            r = await self.http.get(self.base + caminho)
            self.assertEqual(r.status, 401, caminho)

    async def test_saude_e_publica_mas_nao_vaza_nada(self):
        r = await self.http.get(self.base + "/api/saude")
        self.assertEqual(r.status, 200)
        self.assertEqual(set((await r.json()).keys()), {"cerebro", "versao"})

    async def test_token_errado_nao_entra(self):
        r = await self.http.get(f"{self.base}/?t=errado", allow_redirects=False)
        self.assertEqual(r.status, 401)
        self.assertNotIn("Set-Cookie", r.headers)

    async def test_token_certo_vira_cookie_seguro_e_some_da_url(self):
        r = await self.entrar()
        self.assertEqual(r.status, 302)
        self.assertEqual(r.headers["Location"], "/")
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("t" * 43, cookie)             # o cookie não é o token
        r = await self.http.get(self.base + "/")
        self.assertEqual(r.status, 200)
        self.assertIn("Cérebro do Projeto", await r.text())
        r = await self.http.get(self.base + "/api/projetos")
        self.assertEqual(r.status, 200)

    async def test_cabecalhos_de_seguranca(self):
        await self.entrar()
        r = await self.http.get(self.base + "/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    async def test_host_estranho_e_recusado(self):
        await self.entrar()
        for host in ["evil.com", f"evil.com:{self.porta}", f"127.0.0.1.evil.com:{self.porta}", "127.0.0.1:1"]:
            r = await self.http.get(self.base + "/api/projetos", headers={"Host": host})
            self.assertEqual(r.status, 421, host)
        r = await self.http.get(self.base + "/api/projetos", headers={"Host": f"localhost:{self.porta}"})
        self.assertEqual(r.status, 200)

    async def test_origin_de_outro_site_e_recusada(self):
        await self.entrar()
        r = await self.http.get(self.base + "/api/projetos", headers={"Origin": "http://evil.com"})
        self.assertEqual(r.status, 403)
        r = await self.http.get(self.base + "/api/projetos", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)

    async def test_post_exige_origin_e_json(self):
        await self.entrar()
        r = await self.post("/api/config", {"tema": "claro"}, origem=False)
        self.assertEqual(r.status, 403)
        r = await self.http.post(self.base + "/api/config", data="tema=claro", headers={"Origin": self.base})
        self.assertEqual(r.status, 415)
        r = await self.http.post(self.base + "/api/config", data="{}", headers={"Origin": "http://evil.com", "Content-Type": "application/json"})
        self.assertEqual(r.status, 403)
        r = await self.post("/api/config", {"tema": "claro"})
        self.assertEqual(r.status, 200)
        await self.post("/api/config", {"tema": "escuro"})

    async def test_so_escuta_em_127_0_0_1(self):
        self.assertEqual(config.HOST, "127.0.0.1")
        self.assertEqual(self.srv.host, "127.0.0.1")
        import inspect
        self.assertNotIn("0.0.0.0", inspect.getsource(servidor))

    def test_portas_reservadas(self):
        self.assertEqual(config.PORTAS_SEMPRE_PROIBIDAS, {80, 443})
        self.assertEqual(config.portas_proibidas(), {80, 443})
        config.atualizar_config(lambda c: c.__setitem__("portas_reservadas", [8090, 7980]))
        self.addCleanup(config.atualizar_config, lambda c: c.__setitem__("portas_reservadas", []))
        for p in (80, 443, 8090, 7980):
            self.assertIn(p, config.portas_proibidas())
        self.assertNotIn(config.PORTA_PADRAO, config.portas_proibidas())
        self.assertEqual(servidor.executar(8090), 2)

    async def test_porta_reservada_na_configuracao(self):
        await self.entrar()
        config.atualizar_config(lambda c: c.__setitem__("portas_reservadas", [8090]))
        self.addCleanup(config.atualizar_config, lambda c: c.__setitem__("portas_reservadas", []))
        r = await self.post("/api/config", {"porta": 8090})
        self.assertEqual(r.status, 400)
        r = await self.post("/api/config", {"porta": 8189})
        self.assertEqual(r.status, 200)
        await self.post("/api/config", {"porta": 8188})

    async def test_arquivos_fora_da_lista_nao_servem(self):
        await self.entrar()
        for caminho in ["/static/..%2Fcerebro%2Fconfig.py", "/static/servidor.py", "/static/../cerebro.py", f"/mapa/{self.slug}/gerar.py",
                        f"/mapa/{self.slug}/..%2F..%2Fconfig.json", f"/mapa/{self.slug}/.estado.json.gz"]:
            r = await self.http.get(self.base + caminho)
            self.assertIn(r.status, (400, 404), caminho)

    async def test_passos_recusa_caminho_estranho(self):
        await self.entrar()
        for arq in ["../../token", "..\\..\\token", "sessA.json", "/etc/passwd", "a/b/c.jsonl", "sessA/subagents/../../x.jsonl"]:
            r = await self.http.get(f"{self.base}/api/p/{self.slug}/passos", params={"arquivo": arq})
            self.assertIn(r.status, (400, 404), arq)

    async def test_slug_invalido_ou_desconhecido(self):
        await self.entrar()
        r = await self.http.get(self.base + "/api/p/nao-existe/visao")
        self.assertEqual(r.status, 404)
        r = await self.http.get(self.base + "/api/p/..%2F..%2Fx/visao")
        self.assertIn(r.status, (400, 404))


class TesteRotas(Base):
    async def test_projetos_e_cartao(self):
        await self.entrar()
        d = await (await self.http.get(self.base + "/api/projetos")).json()
        p = next(x for x in d["projetos"] if x["slug"] == self.slug)
        self.assertEqual(p["nome"], "Falso")
        self.assertEqual(p["sessoes_total"], 1)
        self.assertFalse(p["mapa"]["graphify"])

    async def test_gestora_valida_sessao_do_projeto(self):
        await self.entrar()
        r = await self.post(f"/api/p/{self.slug}/gestora", {"conversa": "sessA"})
        self.assertEqual(r.status, 400)                                   # não é um UUID
        r = await self.post(f"/api/p/{self.slug}/gestora", {"conversa": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(r.status, 404)                                   # UUID de sessão que não existe aqui
        uid = "11111111-2222-3333-4444-555555555555"
        (config.PROJETOS_CLAUDE / self.slug / f"{uid}.jsonl").write_text(linha_usuario("sou a gestora"), encoding="utf-8")
        r = await self.post(f"/api/p/{self.slug}/gestora", {"conversa": uid})
        self.assertEqual(r.status, 200)
        self.assertEqual(config.ler_config()["gestoras"][self.slug]["conversa"], uid)
        ges = await (await self.http.get(f"{self.base}/mapa/{self.slug}/gestora.json")).json()
        self.assertEqual(ges["conversa"], uid)
        r = await self.post(f"/api/p/{self.slug}/gestora", {"conversa": ""})
        self.assertNotIn(self.slug, config.ler_config()["gestoras"])

    async def test_memoria_lista_busca_e_mascara(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/memoria")).json()
        nomes = {i["arquivo"] for i in d["itens"]}
        self.assertTrue({"MEMORY.md", "regra.md", "AGENTS.md"} <= nomes)
        regra = next(i for i in d["itens"] if i["arquivo"] == "regra.md")
        self.assertTrue(regra["regra"])
        self.assertEqual(regra["tipo"], "feedback")
        self.assertGreater(d["contexto_fixo"]["total_tokens"], 0)
        b = await (await self.http.get(f"{self.base}/api/p/{self.slug}/memoria", params={"q": "zebra"})).json()
        self.assertEqual(len(b["busca"]), 1)
        txt = (await (await self.http.get(f"{self.base}/api/p/{self.slug}/memoria/arquivo", params={"id": "mem/regra.md"})).json())["texto"]
        self.assertIn("zebra", txt)
        self.assertNotIn("abc12345xyz", txt)                              # senha mascarada
        for id_ in ["mem/../../token", "mem/x.txt", "proj/../token", "global/x"]:
            r = await self.http.get(f"{self.base}/api/p/{self.slug}/memoria/arquivo", params={"id": id_})
            self.assertEqual(r.status, 404, id_)

    async def test_decisoes_da_memoria_nao_incluem_o_indice(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/decisoes")).json()
        titulos = [x["titulo"] for x in d["dos_arquivos"]]
        self.assertIn("regra", titulos)
        self.assertNotIn("MEMORY.md", titulos)

    async def test_custos_e_sessoes(self):
        await self.entrar()
        for _ in range(30):
            d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/custos")).json()
            if not d["indexando"] and d["total"]["mensagens"]:
                break
            time.sleep(0.2)
        self.assertEqual(d["total"]["mensagens"], 1)
        self.assertGreater(d["total"]["custo"], 0)
        s = await (await self.http.get(f"{self.base}/api/p/{self.slug}/sessoes")).json()
        self.assertEqual(len(s["sessoes"]), 1)
        self.assertEqual(s["sessoes"][0]["primeira"], "Faça o teste")

    async def test_preco_invalido_e_recusado(self):
        await self.entrar()
        for precos in [{"claude-x": {"entrada": -1, "saida": 1, "cache_leitura": 1, "cache_escrita_5m": 1, "cache_escrita_1h": 1}},
                       {"claude-x": {"entrada": "caro"}}, "texto", {"../x": {}}]:
            r = await self.post("/api/config", {"precos": precos})
            self.assertEqual(r.status, 400, str(precos))

    async def test_mapa_sem_graphify(self):
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/mapa/estado")).json()
        self.assertFalse(d["graphify"])
        self.assertFalse(d["gerado"])
        r = await self.post(f"/api/p/{self.slug}/mapa/gerar", {})
        self.assertEqual(r.status, 409)                                   # sem graphify-out: não gera nada
        r = await self.http.get(f"{self.base}/mapa/{self.slug}/")
        self.assertEqual(r.status, 404)

    async def test_mapa_servido_quando_existe(self):
        await self.entrar()
        pasta = config.CASA / "projetos" / self.slug / "mapa"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "dados.js").write_text("window.CEREBRO = {};", encoding="utf-8")
        (pasta / "historico.json").write_text("[]", encoding="utf-8")
        r = await self.http.get(f"{self.base}/mapa/{self.slug}/")
        self.assertEqual(r.status, 200)
        self.assertIn("dados.js", await r.text())
        for nome in ["dados.js", "historico.json", "cerebro.js", "cerebro.css", "gestora.json"]:
            r = await self.http.get(f"{self.base}/mapa/{self.slug}/{nome}")
            self.assertEqual(r.status, 200, nome)

    async def test_ocultar_projeto_some_do_painel(self):
        await self.entrar()
        await self.post("/api/config", {"ocultos": [self.slug]})
        d = await (await self.http.get(self.base + "/api/projetos")).json()
        self.assertNotIn(self.slug, [p["slug"] for p in d["projetos"]])
        d = await (await self.http.get(self.base + "/api/projetos?ocultos=1")).json()
        self.assertIn(self.slug, [p["slug"] for p in d["projetos"]])
        await self.post("/api/config", {"ocultos": []})

    async def test_agentes_lista_sessao_e_subagente(self):
        pasta = config.PROJETOS_CLAUDE / self.slug
        (pasta / "sessA" / "subagents").mkdir(parents=True)
        (pasta / "sessA" / "subagents" / "agent-zz1.jsonl").write_text(linha_assistente("s1", ts="2026-10-28T12:00:00.000Z"), encoding="utf-8")
        (pasta / "sessA" / "subagents" / "agent-zz1.meta.json").write_text(json.dumps({"description": "Faz X", "finished": True, "model": "sonnet"}))
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/agentes", params={"todas": "1"})).json()
        self.assertEqual(len(d["sessoes"]), 1)
        sub = d["sessoes"][0]["subagentes"]
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0]["descricao"], "Faz X")
        self.assertEqual(sub[0]["estado"], "terminou")

    async def test_stream_de_passos_entrega_o_historico_e_o_novo(self):
        await self.entrar()
        r = await self.http.get(f"{self.base}/api/p/{self.slug}/passos", params={"arquivo": "sessA.jsonl"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"].split(";")[0], "text/event-stream")
        primeiro = json.loads((await r.content.readline()).decode().removeprefix("data: "))
        self.assertEqual(primeiro["tipo"], "inicio")
        self.assertTrue(any(p["tipo"] == "texto" and p["texto"] == "feito" for p in primeiro["passos"]))
        with open(config.PROJETOS_CLAUDE / self.slug / "sessA.jsonl", "ab") as f:
            f.write(linha_assistente("m2", conteudo=[{"type": "text", "text": "novo passo ao vivo"}]).encode())
        await r.content.readline()                                         # linha em branco do evento anterior
        novo = json.loads((await asyncio_wait(r.content.readline())).decode().removeprefix("data: "))
        self.assertEqual(novo["passos"][0]["texto"], "novo passo ao vivo")
        r.close()


class TesteEncerramento(unittest.IsolatedAsyncioTestCase):
    """O servidor encerra sozinho depois de N minutos sem página aberta; página aberta (ping ou SSE) segura."""

    async def _rodar_vigia(self, ultimo_ping_ha_s, sse):
        import asyncio
        from unittest import mock
        app = servidor.criar_app(8188, token="t" * 43)
        app[servidor.K_ESTADO].update(ultimo_ping=time.time() - ultimo_ping_ha_s, sse_ativos=sse)
        with mock.patch.object(config, "ler_config", return_value={"sem_pagina_minutos": 30}):
            tarefa = asyncio.create_task(servidor._vigia(app, 0.02))
            await asyncio.sleep(0.2)
            tarefa.cancel()
        return app[servidor.K_PARAR].is_set()

    async def test_encerra_sem_pagina_ha_mais_de_30_minutos(self):
        self.assertTrue(await self._rodar_vigia(31 * 60, 0))

    async def test_nao_encerra_com_ping_recente(self):
        self.assertFalse(await self._rodar_vigia(5 * 60, 0))

    async def test_nao_encerra_com_fluxo_aberto(self):
        self.assertFalse(await self._rodar_vigia(3 * 3600, 1))


async def asyncio_wait(coro, tempo=8):
    import asyncio
    return await asyncio.wait_for(coro, tempo)


if __name__ == "__main__":
    unittest.main()
