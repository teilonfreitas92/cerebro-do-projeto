"""Ganchos do Claude Code (receptor, estado ao vivo, instalador do settings.json), statusLine e avisos do Windows.
Tudo em pastas de mentira: o settings.json é CEREBRO_CLAUDE_SETTINGS (isolado em testes/_ambiente.py), nenhum PowerShell real roda."""
import io
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from testes import _ambiente as amb
from cerebro import avisos, config, ganchos_claude, ganchos_eventos, painel, servidor
import cerebro_cli
import cerebro_hook
import cerebro_statusline

SEGREDO = "sk-ant-api03-" + "A" * 40
SEM_ACL = mock.patch.object(config, "_restringir_ao_dono", lambda caminho: None)   # nada de whoami/icacls de verdade


def _limpar_casa():
    for nome in ("hooks_token", "ganchos.json", "avisos.json", "avisos.jsonl", "claude_status.json", "eventos", "copias", "servidor.json"):
        amb.apagar(amb.CASA / nome)
    amb.apagar(ganchos_claude.caminho_settings())
    ganchos_eventos.zerar()
    avisos.zerar()


class TesteIsolamento(unittest.TestCase):
    def test_settings_do_claude_e_de_mentira(self):
        p = ganchos_claude.caminho_settings().resolve()
        p.relative_to(amb.BASE.resolve())            # levanta se estiver fora da pasta de testes
        self.assertNotEqual(p, (Path.home() / ".claude" / "settings.json").resolve())


# ---------------------------------------------------------------------------------------------------------------
# Receptor HTTP
# ---------------------------------------------------------------------------------------------------------------
class TesteReceptor(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _limpar_casa()
        with SEM_ACL:
            self.token = ganchos_eventos.token_hooks()
        self.avisos_falsos = []
        self._exec = avisos._executar
        avisos._executar = lambda t, x: self.avisos_falsos.append((t, x)) or True
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.porta = sk.getsockname()[1]
        self.app = servidor.criar_app(self.porta, token="t" * 43)
        self.srv = TestServer(self.app, port=self.porta)
        await self.srv.start_server()
        self.url = f"http://127.0.0.1:{self.porta}{ganchos_eventos.ROTA}"
        self.http = ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.srv.close()
        avisos._executar = self._exec
        ganchos_eventos.zerar()

    async def enviar(self, corpo, cab=None, token=True):
        h = {"Content-Type": "application/json"}
        if token:
            h[ganchos_eventos.CABECALHO] = self.token
        h.update(cab or {})
        dados = corpo if isinstance(corpo, (bytes, str)) else json.dumps(corpo)
        return await self.http.post(self.url, data=dados, headers=h)

    def evento(self, nome="PreToolUse", **extra):
        base = {"hook_event_name": nome, "session_id": "s-1", "cwd": "C:/Projetos/Falso",
                "transcript_path": "C:/x/.claude/projects/C--Projetos-Falso/s-1.jsonl"}
        base.update(extra)
        return base

    async def test_sem_segredo_ou_segredo_errado_e_recusado(self):
        r = await self.enviar(self.evento(), token=False)
        self.assertEqual(r.status, 401)
        r = await self.enviar(self.evento(), {ganchos_eventos.CABECALHO: "x" * 43}, token=False)
        self.assertEqual(r.status, 401)
        self.assertEqual(ganchos_eventos.recentes(), [])

    async def test_token_da_pagina_nao_serve_para_os_ganchos(self):
        r = await self.enviar(self.evento(), {ganchos_eventos.CABECALHO: "t" * 43}, token=False)
        self.assertEqual(r.status, 401)
        r = await self.http.post(self.url, data=json.dumps(self.evento()), headers={"Content-Type": "application/json", "Cookie": servidor.nome_cookie(self.porta) + "=" + config.valor_cookie("t" * 43)})
        self.assertEqual(r.status, 401)

    async def test_qualquer_origin_e_recusada_mesmo_com_segredo(self):
        for origem in (f"http://127.0.0.1:{self.porta}", "https://site-malicioso.example", "null"):
            r = await self.enviar(self.evento(), {"Origin": origem})
            self.assertEqual(r.status, 403, origem)
        r = await self.enviar(self.evento(), {"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status, 403)
        self.assertEqual(ganchos_eventos.recentes(), [])

    async def test_host_errado_e_recusado(self):
        r = await self.enviar(self.evento(), {"Host": "evil.example"})
        self.assertEqual(r.status, 421)

    async def test_corpo_grande_demais(self):
        grande = json.dumps(self.evento(message="x" * (ganchos_eventos.LIMITE_CORPO + 10)))
        r = await self.enviar(grande)
        self.assertEqual(r.status, 413)
        self.assertEqual(ganchos_eventos.recentes(), [])

    async def test_json_quebrado_e_tolerado(self):
        for corpo in ("{quebrado", "[1,2]", "", json.dumps({"sem_nome": 1})):
            r = await self.enviar(corpo)
            self.assertEqual(r.status, 200, corpo)
            self.assertEqual(await r.json(), {})
        self.assertEqual(ganchos_eventos.recentes(), [])

    async def test_get_nao_e_aceito(self):
        r = await self.http.get(self.url, headers={ganchos_eventos.CABECALHO: self.token})
        self.assertEqual(r.status, 405)

    async def test_evento_valido_vai_para_anel_e_arquivo_mascarado(self):
        ev = self.evento("PreToolUse", tool_name="Bash", tool_input={"command": f"curl -H 'Authorization: Bearer {SEGREDO}' x"},
                         campo_desconhecido={"a": 1}, tool_use_id="tu1")
        r = await self.enviar(ev)
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.json(), {})
        rec = ganchos_eventos.recentes()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["evento"], "PreToolUse")
        self.assertEqual(rec[0]["slug"], "C--Projetos-Falso")
        self.assertNotIn("campo_desconhecido", rec[0])
        arq = ganchos_eventos.pasta_eventos() / f"{date.today().isoformat()}.jsonl"
        texto = arq.read_text(encoding="utf-8")
        self.assertNotIn(SEGREDO, texto)
        self.assertNotIn("campo_desconhecido", texto)
        self.assertIn("Bash", texto)

    async def test_mensagem_com_segredo_e_mascarada(self):
        await self.enviar(self.evento("Notification", message=f"senha: {SEGREDO}", notification_type="permission_prompt"))
        self.assertNotIn(SEGREDO, json.dumps(ganchos_eventos.recentes()))
        self.assertTrue(self.avisos_falsos or avisos.historico())
        self.assertNotIn(SEGREDO, json.dumps(avisos.historico()))

    async def test_ouvinte_devolve_additional_context_so_onde_a_doc_permite(self):
        ganchos_eventos.registrar_ouvinte("UserPromptSubmit", lambda ev: "Tarefa nova do dono: revisar o login.")
        ganchos_eventos.registrar_ouvinte("Stop", lambda ev: "isto nunca volta")
        r = await self.enviar(self.evento("UserPromptSubmit", prompt="oi"))
        d = await r.json()
        self.assertEqual(d["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("revisar o login", d["hookSpecificOutput"]["additionalContext"])
        r = await self.enviar(self.evento("Stop"))
        self.assertEqual(await r.json(), {})

    async def test_ouvinte_com_defeito_nao_quebra(self):
        ganchos_eventos.registrar_ouvinte("*", lambda ev: 1 / 0)
        r = await self.enviar(self.evento("SessionStart", source="startup"))
        self.assertEqual(r.status, 200)
        self.assertEqual(len(ganchos_eventos.recentes()), 1)

    async def test_rotas_da_pagina_continuam_exigindo_cookie(self):
        for c in ("/api/ganchos/estado", "/api/avisos"):
            r = await self.http.get(f"http://127.0.0.1:{self.porta}{c}")
            self.assertEqual(r.status, 401, c)


# ---------------------------------------------------------------------------------------------------------------
# Estado ao vivo e arquivo
# ---------------------------------------------------------------------------------------------------------------
class TesteEstadoAoVivo(unittest.TestCase):
    def setUp(self):
        _limpar_casa()

    def tearDown(self):
        ganchos_eventos.zerar()

    def _arvore(self, mtime):
        return {"sessoes": [{"id": "s-1", "mtime": mtime, "estado": "parado",
                             "subagentes": [{"id": "ag1", "mtime": mtime, "estado": "parado"}, {"id": "ag2", "mtime": mtime, "estado": "trabalhando"}]}]}

    def test_sem_ganchos_nada_muda(self):
        d = ganchos_eventos.aplicar("x", self._arvore(time.time()))
        self.assertEqual(d["fonte"], "arquivos")
        self.assertEqual(d["sessoes"][0]["estado"], "parado")
        self.assertEqual(d["sessoes"][0]["fonte"], "arquivos")

    def test_ganchos_mandam_no_estado(self):
        t = time.time()
        base = {"session_id": "s-1", "cwd": "C:/P"}
        ganchos_eventos.receber({"hook_event_name": "UserPromptSubmit", **base}, t - 30)
        ganchos_eventos.receber({"hook_event_name": "SubagentStart", "agent_id": "ag1", "agent_type": "Explore", **base}, t - 20)
        ganchos_eventos.receber({"hook_event_name": "PreToolUse", "agent_id": "ag1", "tool_name": "Grep", "tool_input": {"pattern": "login"}, **base}, t - 10)
        ganchos_eventos.receber({"hook_event_name": "SubagentStop", "agent_id": "ag2", **base}, t - 5)
        d = ganchos_eventos.aplicar("x", self._arvore(t - 60), agora=t)
        s = d["sessoes"][0]
        self.assertEqual(d["fonte"], "hooks")
        self.assertEqual(s["estado"], "trabalhando")
        sub1, sub2 = s["subagentes"]
        self.assertEqual(sub1["estado"], "trabalhando")
        self.assertEqual(sub1["ferramenta_agora"], {"nome": "Grep", "alvo": "login"})
        self.assertEqual(sub2["estado"], "terminou")
        ganchos_eventos.receber({"hook_event_name": "Notification", "message": "Claude precisa de permissão", **base}, t - 1)
        d = ganchos_eventos.aplicar("x", self._arvore(t - 60), agora=t)
        self.assertTrue(d["sessoes"][0]["espera_dono"])
        ganchos_eventos.receber({"hook_event_name": "Stop", **base}, t)
        d = ganchos_eventos.aplicar("x", self._arvore(t - 60), agora=t)
        self.assertEqual(d["sessoes"][0]["estado"], "parado")
        ganchos_eventos.receber({"hook_event_name": "SessionEnd", "reason": "other", **base}, t)
        self.assertEqual(ganchos_eventos.aplicar("x", self._arvore(t - 60), agora=t)["sessoes"][0]["estado"], "terminou")

    def test_gancho_velho_nao_vence_arquivo_novo(self):
        t = time.time()
        ganchos_eventos.receber({"hook_event_name": "Stop", "session_id": "s-1"}, t - 3600)
        d = ganchos_eventos.aplicar("x", self._arvore(t), agora=t)
        self.assertEqual(d["sessoes"][0]["fonte"], "arquivos")

    def test_rotacao_de_7_dias_pela_trava(self):
        pasta = ganchos_eventos.pasta_eventos()
        pasta.mkdir(parents=True, exist_ok=True)
        hoje = date.today()
        velho, novo = pasta / f"{(hoje - timedelta(days=9)).isoformat()}.jsonl", pasta / f"{(hoje - timedelta(days=2)).isoformat()}.jsonl"
        outro = pasta / "nao-e-data.jsonl"
        for f in (velho, novo, outro):
            f.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(config, "remover", wraps=config.remover) as rem:
            self.assertEqual(ganchos_eventos.girar(hoje), 1)
            rem.assert_called_once()
        self.assertFalse(velho.exists())
        self.assertTrue(novo.exists() and outro.exists())

    def test_sse_acorda_quando_chega_evento(self):
        import asyncio

        async def rodar():
            t0 = time.time()
            espera = asyncio.create_task(ganchos_eventos.esperar_novidade(5))
            await asyncio.sleep(0.05)
            ganchos_eventos.acordar()
            await espera
            return time.time() - t0
        self.assertLess(asyncio.run(rodar()), 2)


# ---------------------------------------------------------------------------------------------------------------
# Instalador: mescla do settings.json
# ---------------------------------------------------------------------------------------------------------------
ORIGINAL = {
    "$schema": "https://json.schemastore.org/claude-code-settings.json",
    "model": "opus",
    "permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(./.env)"]},
    "env": {"MINHA_VAR": "1"},
    "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "powershell -File C:/meu/gancho.ps1"}]}],
              "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "echo oi"}]}]},
    "chave_desconhecida": {"x": [1, 2, 3]},
    "theme": "dark",
}


class TesteInstalador(unittest.TestCase):
    def setUp(self):
        _limpar_casa()
        self.p = ganchos_claude.caminho_settings()
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.texto = json.dumps(ORIGINAL, indent=2) + "\n"
        self.p.write_text(self.texto, encoding="utf-8")
        self.acl = SEM_ACL.start()

    def tearDown(self):
        SEM_ACL.stop()

    def ler(self):
        return json.loads(self.p.read_text(encoding="utf-8"))

    def copias(self):
        pasta = config.CASA / "copias" / "settings"
        return sorted(pasta.glob("*.json")) if pasta.is_dir() else []

    def test_previa_nao_grava_e_mostra_diferenca(self):
        pr = ganchos_claude.previa()
        self.assertTrue(pr["muda"])
        self.assertIn("cerebro_hook", pr["diferenca"])
        self.assertEqual(self.p.read_text(encoding="utf-8"), self.texto)
        self.assertEqual(self.copias(), [])

    def test_sem_confirmar_nada_muda(self):
        with self.assertRaises(ValueError):
            ganchos_claude.instalar()
        with self.assertRaises(ValueError):
            ganchos_claude.remover()
        self.assertEqual(self.p.read_text(encoding="utf-8"), self.texto)

    def test_instalar_preserva_tudo_e_acrescenta_so_o_do_cerebro(self):
        r = ganchos_claude.instalar(confirmar=True)
        self.assertTrue(r["mudou"])
        d = self.ler()
        self.assertEqual(list(d.keys()), list(ORIGINAL.keys()))         # mesma ordem, nada sumiu
        for k in ORIGINAL:
            if k != "hooks":
                self.assertEqual(d[k], ORIGINAL[k])
        self.assertEqual(d["hooks"]["UserPromptSubmit"][0], ORIGINAL["hooks"]["UserPromptSubmit"][0])
        self.assertEqual(d["hooks"]["PostToolUse"], ORIGINAL["hooks"]["PostToolUse"])
        for ev in ganchos_eventos.EVENTOS:
            entradas = [x for g in d["hooks"][ev] for x in g["hooks"] if ganchos_claude.eh_do_cerebro(x) and "--sincrono" not in x["command"]]
            self.assertEqual(len(entradas), 1, ev)
            self.assertEqual(entradas[0]["type"], "command")
            self.assertTrue(entradas[0]["async"])
            self.assertNotIn("\\", entradas[0]["command"])
        # cópia de segurança com o conteúdo original
        cps = self.copias()
        self.assertEqual(len(cps), 1)
        self.assertEqual(cps[0].read_text(encoding="utf-8"), self.texto)
        self.assertEqual(ganchos_claude.estado()["outros_ganchos"], 2)
        self.assertTrue(ganchos_eventos.token_hooks(criar=False))     # o cerebro_hook.py precisa do segredo também no modo comando
        self.assertNotIn(ganchos_eventos.token_hooks(criar=False), self.p.read_text(encoding="utf-8"))

    def test_instalar_duas_vezes_nao_duplica(self):
        ganchos_claude.instalar(confirmar=True)
        depois1 = self.p.read_text(encoding="utf-8")
        r = ganchos_claude.instalar(confirmar=True)
        self.assertFalse(r["mudou"])
        self.assertEqual(self.p.read_text(encoding="utf-8"), depois1)
        self.assertEqual(len(self.copias()), 1)

    def test_remover_tira_so_o_do_cerebro(self):
        ganchos_claude.instalar(confirmar=True)
        r = ganchos_claude.remover(confirmar=True)
        self.assertTrue(r["mudou"])
        self.assertEqual(self.ler(), ORIGINAL)
        self.assertEqual(list(self.ler().keys()), list(ORIGINAL.keys()))
        self.assertEqual(ganchos_claude.estado()["eventos"], [])

    def test_remover_nao_toca_em_gancho_de_outra_pessoa_no_mesmo_grupo(self):
        d = json.loads(self.texto)
        d["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "meu-script.sh"},
                                          {"type": "http", "url": "http://127.0.0.1:9/api/hooks/evento"}]}]
        self.p.write_text(json.dumps(d, indent=2), encoding="utf-8")
        ganchos_claude.remover(confirmar=True)
        self.assertEqual(self.ler()["hooks"]["Stop"], [{"hooks": [{"type": "command", "command": "meu-script.sh"}]}])

    def test_json_invalido_e_recusado_sem_copia_nem_escrita(self):
        quebrado = '{"model": "opus",, }'
        self.p.write_text(quebrado, encoding="utf-8")
        for f in (lambda: ganchos_claude.instalar(confirmar=True), lambda: ganchos_claude.remover(confirmar=True), ganchos_claude.previa):
            with self.assertRaises(ganchos_claude.SettingsInvalido):
                f()
        self.assertEqual(self.p.read_text(encoding="utf-8"), quebrado)
        self.assertEqual(self.copias(), [])
        self.assertFalse(ganchos_claude.estado()["valido"])

    def test_arquivo_ausente_e_criado(self):
        amb.apagar(self.p)
        r = ganchos_claude.instalar(confirmar=True)
        self.assertTrue(r["mudou"])
        self.assertIsNone(r["copia"])
        self.assertIn("hooks", self.ler())
        ganchos_claude.remover(confirmar=True)
        self.assertEqual(self.ler(), {})

    def test_modo_http_usa_a_porta_e_o_segredo_proprio(self):
        config.atualizar_config(lambda c: c.__setitem__("porta", 8199))
        try:
            r = ganchos_claude.instalar(confirmar=True, modo="http")
            tok = ganchos_eventos.token_hooks(criar=False)
            self.assertNotIn(tok, r["diferenca"])                  # a diferença mostrada nunca expõe o segredo
            x = [x for g in self.ler()["hooks"]["Stop"] for x in g["hooks"] if ganchos_claude.eh_do_cerebro(x)][0]
            self.assertEqual(x["url"], "http://127.0.0.1:8199/api/hooks/evento")
            self.assertEqual(x["headers"][ganchos_eventos.CABECALHO], tok)
            self.assertNotEqual(tok, config.ler_token())
            self.assertLessEqual(x["timeout"], 2)
            self.assertFalse(ganchos_claude.estado()["precisa_reinstalar"])
            config.atualizar_config(lambda c: c.__setitem__("porta", 8200))
            self.assertTrue(ganchos_claude.estado()["precisa_reinstalar"])
            ganchos_claude.instalar(confirmar=True, modo="http")    # reinstalar troca a url no lugar, sem duplicar
            urls = [x["url"] for g in self.ler()["hooks"]["Stop"] for x in g["hooks"] if ganchos_claude.eh_do_cerebro(x)]
            self.assertEqual(urls, ["http://127.0.0.1:8200/api/hooks/evento"])
        finally:
            config.atualizar_config(lambda c: c.__setitem__("porta", config.PORTA_PADRAO))

    def test_statusline_existente_precisa_de_decisao(self):
        d = json.loads(self.texto)
        d["statusLine"] = {"type": "command", "command": "~/.claude/minha_barra.sh", "padding": 1}
        self.p.write_text(json.dumps(d, indent=2), encoding="utf-8")
        with self.assertRaises(ganchos_claude.PrecisaDecidir):
            ganchos_claude.instalar(confirmar=True, hooks=False, statusline="instalar")
        self.assertTrue(ganchos_claude.previa(False, statusline="instalar")["precisa_decidir"])
        self.assertEqual(self.ler()["statusLine"]["command"], "~/.claude/minha_barra.sh")
        ganchos_claude.instalar(confirmar=True, hooks=False, statusline="encadear")
        sl = self.ler()["statusLine"]
        self.assertIn("cerebro_statusline", sl["command"])
        self.assertEqual(sl["padding"], 1)
        est = ganchos_claude.ler_estado()
        self.assertEqual(est["statusline_modo"], "encadear")
        self.assertEqual(est["statusline_anterior"]["command"], "~/.claude/minha_barra.sh")
        self.assertEqual(cerebro_statusline.comando_anterior(config.CASA), "~/.claude/minha_barra.sh")
        self.assertTrue(ganchos_claude.estado()["statusline_encadeada"])
        ganchos_claude.instalar(confirmar=True, hooks=False, statusline="instalar")     # repetir não desfaz o encadeamento
        self.assertEqual(ganchos_claude.ler_estado()["statusline_modo"], "encadear")
        ganchos_claude.remover(confirmar=True, hooks=False, statusline=True)
        self.assertEqual(self.ler()["statusLine"], {"type": "command", "command": "~/.claude/minha_barra.sh", "padding": 1})
        self.assertNotIn("statusline_anterior", ganchos_claude.ler_estado())

    def test_statusline_nova_sem_anterior(self):
        ganchos_claude.instalar(confirmar=True, hooks=False, statusline="instalar")
        self.assertIn("cerebro_statusline", self.ler()["statusLine"]["command"])
        self.assertEqual(cerebro_statusline.comando_anterior(config.CASA), "")
        ganchos_claude.remover(confirmar=True, hooks=False, statusline=True)
        self.assertEqual(self.ler(), ORIGINAL)

    def test_cli_exige_confirmar(self):
        with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(cerebro_cli.main(["hooks", "--instalar"]), cerebro_cli.SAIDA_ERRO)
            self.assertIn("--confirmar", err.getvalue())
            self.assertEqual(cerebro_cli.main(["hooks", "--previa"]), cerebro_cli.SAIDA_OK)
        self.assertEqual(self.p.read_text(encoding="utf-8"), self.texto)
        with mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(cerebro_cli.main(["hooks", "--instalar", "--confirmar"]), cerebro_cli.SAIDA_OK)
            self.assertEqual(cerebro_cli.main(["hooks", "--estado"]), cerebro_cli.SAIDA_OK)
            self.assertIn("SessionStart", out.getvalue())
            self.assertEqual(cerebro_cli.main(["hooks", "--remover", "--confirmar"]), cerebro_cli.SAIDA_OK)
        self.assertEqual(self.ler(), ORIGINAL)


# ---------------------------------------------------------------------------------------------------------------
# Script do gancho (cerebro_hook.py)
# ---------------------------------------------------------------------------------------------------------------
class TesteScriptGancho(unittest.TestCase):
    def setUp(self):
        _limpar_casa()

    def test_cerebro_fechado_nao_tenta_conectar(self):
        chamado = []
        self.assertEqual(cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', amb.CASA, abrir=lambda *a, **k: chamado.append(1)), "")
        self.assertEqual(chamado, [])

    def test_entrega_com_porta_do_servidor_e_segredo(self):
        amb.CASA.mkdir(parents=True, exist_ok=True)
        (amb.CASA / "servidor.json").write_text(json.dumps({"pid": 1, "porta": 8177}), encoding="utf-8")
        with SEM_ACL:
            tok = ganchos_eventos.token_hooks()
        visto = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def abrir(req, timeout):
            visto.update(url=req.full_url, cab=req.get_header("X-cerebro-hooks"), timeout=timeout, corpo=req.data)
            return Resp(b"{}")
        self.assertEqual(cerebro_hook.entregar(b'{"hook_event_name":"Stop"}', amb.CASA, abrir=abrir), "{}")
        self.assertEqual(visto["url"], "http://127.0.0.1:8177/api/hooks/evento")
        self.assertEqual(visto["cab"], tok)
        self.assertLessEqual(visto["timeout"], 2)

    def test_erro_de_rede_e_engolido(self):
        amb.CASA.mkdir(parents=True, exist_ok=True)
        (amb.CASA / "servidor.json").write_text(json.dumps({"porta": 8177}), encoding="utf-8")
        with SEM_ACL:
            ganchos_eventos.token_hooks()

        def abrir(req, timeout):
            raise OSError("recusado")
        self.assertEqual(cerebro_hook.entregar(b"{}", amb.CASA, abrir=abrir), "")


# ---------------------------------------------------------------------------------------------------------------
# statusLine
# ---------------------------------------------------------------------------------------------------------------
ENTRADA_STATUS = {"session_id": "s", "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
                  "cost": {"total_cost_usd": 1.234, "total_duration_ms": 1}, "workspace": {"current_dir": "C:/segredo/pasta"},
                  "context_window": {"used_percentage": 8, "context_window_size": 200000},
                  "rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": 4102444800},
                                  "seven_day": {"used_percentage": 41.2, "resets_at": 4102444800}}}


class TesteStatusline(unittest.TestCase):
    def setUp(self):
        _limpar_casa()

    def test_stdin_vira_arquivo_com_so_o_util_e_linha_curta(self):
        linha = cerebro_statusline.principal(json.dumps(ENTRADA_STATUS).encode(), amb.CASA)
        d = json.loads((amb.CASA / "claude_status.json").read_text(encoding="utf-8"))
        self.assertEqual(d["rate_limits"]["five_hour"]["used_percentage"], 23.5)
        self.assertEqual(d["model"]["id"], "claude-opus-5-5")
        self.assertNotIn("workspace", json.dumps(d))
        self.assertIn("5h 24%", linha)
        self.assertIn("7d 41%", linha)
        lim = painel.limites()
        self.assertTrue(lim["disponivel"])
        self.assertEqual(lim["cinco_horas"]["percentual"], 23.5)
        self.assertEqual(lim["sete_dias"]["renova_em"], 4102444800)

    def test_mantem_limites_quando_a_sessao_ainda_nao_tem(self):
        cerebro_statusline.principal(json.dumps(ENTRADA_STATUS).encode(), amb.CASA)
        sem = dict(ENTRADA_STATUS)
        sem.pop("rate_limits")
        cerebro_statusline.principal(json.dumps(sem).encode(), amb.CASA)
        d = json.loads((amb.CASA / "claude_status.json").read_text(encoding="utf-8"))
        self.assertEqual(d["rate_limits"]["seven_day"]["used_percentage"], 41.2)

    def test_entrada_quebrada_nao_quebra(self):
        self.assertTrue(cerebro_statusline.principal(b"{nada", amb.CASA))

    def test_encadeamento_passa_a_mesma_entrada_e_mostra_a_saida_antiga(self):
        amb.CASA.mkdir(parents=True, exist_ok=True)
        (amb.CASA / "ganchos.json").write_text(json.dumps({"statusline_modo": "encadear",
                                                           "statusline_anterior": {"type": "command", "command": "minha-barra"}}), encoding="utf-8")
        visto = {}

        def executar(args, input, **k):
            visto.update(args=args, entrada=input, k=k)
            return subprocess.CompletedProcess(args, 0, stdout="MINHA BARRA\n".encode(), stderr=b"")
        entrada = json.dumps(ENTRADA_STATUS).encode()
        self.assertEqual(cerebro_statusline.principal(entrada, amb.CASA, executar), "MINHA BARRA")
        self.assertEqual(visto["entrada"], entrada)
        self.assertEqual(visto["args"][-1], "minha-barra")
        self.assertIsInstance(visto["args"], list)
        self.assertIn("timeout", visto["k"])
        self.assertTrue((amb.CASA / "claude_status.json").is_file())       # grava mesmo encadeado

        def falha(args, input, **k):
            raise subprocess.TimeoutExpired(args, 5)
        self.assertIn("Opus", cerebro_statusline.principal(entrada, amb.CASA, falha))

    def test_nunca_encadeia_consigo_mesmo(self):
        amb.CASA.mkdir(parents=True, exist_ok=True)
        (amb.CASA / "ganchos.json").write_text(json.dumps({"statusline_modo": "encadear",
                                                           "statusline_anterior": {"command": "python cerebro_statusline.py"}}), encoding="utf-8")
        self.assertEqual(cerebro_statusline.comando_anterior(amb.CASA), "")

    def test_script_de_verdade_por_subprocesso(self):
        r = subprocess.run([sys.executable, str(ganchos_claude.SCRIPT_STATUS)], input=json.dumps(ENTRADA_STATUS).encode(),
                           capture_output=True, timeout=30, env=dict(os.environ))
        self.assertEqual(r.returncode, 0)
        self.assertIn("Opus", r.stdout.decode("utf-8"))


# ---------------------------------------------------------------------------------------------------------------
# Avisos no Windows
# ---------------------------------------------------------------------------------------------------------------
class TesteAvisos(unittest.TestCase):
    def setUp(self):
        _limpar_casa()
        self.mostrados = []
        self.salvo = (avisos._executar, avisos._em_segundo_plano, avisos._eh_windows)
        avisos._executar = lambda t, x: self.mostrados.append((t, x)) or True
        avisos._em_segundo_plano = False
        avisos._eh_windows = True

    def tearDown(self):
        avisos._executar, avisos._em_segundo_plano, avisos._eh_windows = self.salvo
        ganchos_eventos.zerar()

    def test_mostra_e_nao_repete(self):
        t = 1_800_000_000
        self.assertEqual(avisos.avisar("Oi", "texto", "k1", agora=t), "mostrado")
        self.assertEqual(avisos.avisar("Oi", "texto", "k1", agora=t + 60), "repetido")
        self.assertEqual(avisos.avisar("Oi", "outro", "k2", agora=t + 60), "mostrado")
        self.assertEqual(avisos.avisar("Oi", "texto", "k1", agora=t + 11 * 60), "mostrado")
        self.assertEqual(len(self.mostrados), 3)

    def test_mascara_o_texto(self):
        avisos.avisar("Título", f"chave {SEGREDO}", "k")
        self.assertNotIn(SEGREDO, self.mostrados[0][1])

    def test_desligado_por_tipo_e_geral(self):
        avisos.salvar_preferencias({"tipos": {"sessao_parou": False}})
        self.assertEqual(avisos.avisar("a", "b", "k", tipo="sessao_parou"), "desligado")
        self.assertEqual(avisos.avisar("a", "b", "k2", tipo="geral"), "mostrado")
        avisos.salvar_preferencias({"ligado": False})
        self.assertEqual(avisos.avisar("a", "b", "k3"), "desligado")
        with self.assertRaises(ValueError):
            avisos.salvar_preferencias({"nao_perturbe": {"inicio": "25:00"}})
        with self.assertRaises(ValueError):
            avisos.salvar_preferencias({"tipos": {"inventado": True}})

    def test_nao_perturbe_que_passa_da_meia_noite(self):
        p = {"nao_perturbe": {"ligado": True, "inicio": "22:00", "fim": "07:00"}}

        def em(h, m):
            lt = time.localtime()
            return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
        self.assertTrue(avisos.em_nao_perturbe(p, em(23, 30)))
        self.assertTrue(avisos.em_nao_perturbe(p, em(6, 59)))
        self.assertFalse(avisos.em_nao_perturbe(p, em(12, 0)))
        avisos.salvar_preferencias(p)
        self.assertEqual(avisos.avisar("a", "b", "k", agora=em(23, 0)), "nao_perturbe")
        self.assertEqual(self.mostrados, [])

    def test_fora_do_windows_so_registra(self):
        avisos._eh_windows = False
        self.assertEqual(avisos.avisar("a", "b", "k"), "sem_windows")
        self.assertEqual(self.mostrados, [])
        self.assertEqual(avisos.historico()[0]["resultado"], "sem_windows")

    def test_powershell_de_verdade_nunca_roda_nos_testes(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("PowerShell real chamado")):
            self.assertFalse(avisos._executar_powershell("a", "b"))

    @unittest.skipUnless(os.name == "nt", "a notificação usa o PowerShell do Windows (fora dele não há powershell.exe)")
    def test_powershell_recebe_texto_por_variavel_e_sem_janela(self):
        visto = {}

        def falso(args, **k):
            visto.update(args=args, k=k)
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.dict(os.environ, {"CEREBRO_TESTE_HOME": ""}), mock.patch.object(subprocess, "run", falso):
            self.assertTrue(avisos._executar_powershell("Título'; rm -rf", "<texto & mau>"))
        self.assertTrue(os.path.isabs(visto["args"][0]))                    # sempre o PowerShell do sistema, por caminho absoluto
        self.assertTrue(visto["args"][0].lower().endswith("powershell.exe"))
        self.assertNotIn("rm -rf", " ".join(visto["args"]))           # o texto nunca entra no comando
        self.assertEqual(visto["k"]["env"]["CEREBRO_AVISO_TITULO"], "Título'; rm -rf")
        self.assertEqual(visto["k"]["creationflags"], 0x08000000)
        self.assertIn("timeout", visto["k"])

    def test_gatilhos_dos_ganchos(self):
        avisos.ligar_gatilhos()
        ges = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        slug = "C--Projetos-Falso"
        config.atualizar_config(lambda c: c["gestoras"].__setitem__(slug, {"conversa": ges, "nome": "G"}))
        try:
            tp = f"C:/x/.claude/projects/{slug}/{ges}.jsonl"
            ganchos_eventos.receber({"hook_event_name": "SubagentStop", "session_id": "outra", "agent_id": "a0", "transcript_path": tp})
            self.assertEqual(self.mostrados, [])                               # só a sessão gestora avisa
            ganchos_eventos.receber({"hook_event_name": "SubagentStop", "session_id": ges, "agent_id": "a1", "agent_type": "Explore", "transcript_path": tp})
            self.assertIn("conferir", self.mostrados[-1][0])
            ganchos_eventos.receber({"hook_event_name": "Notification", "session_id": ges, "message": "Claude precisa de permissão", "transcript_path": tp})
            self.assertIn("permissão", self.mostrados[-1][1])
            t = time.time()
            ganchos_eventos.receber({"hook_event_name": "UserPromptSubmit", "session_id": "s9", "cwd": "C:/P"}, t - 120)
            ganchos_eventos.receber({"hook_event_name": "Stop", "session_id": "s9", "cwd": "C:/P"}, t)
            self.assertEqual(len(self.mostrados), 2)                            # 2 min < 5 min: sem aviso
            ganchos_eventos.receber({"hook_event_name": "UserPromptSubmit", "session_id": "s9", "cwd": "C:/P"}, t - 600)
            ganchos_eventos.receber({"hook_event_name": "Stop", "session_id": "s9", "cwd": "C:/P"}, t)
            self.assertIn("10 min", self.mostrados[-1][1])
            ganchos_eventos.receber({"hook_event_name": "Stop", "session_id": "s9", "cwd": "C:/P"}, t + 1)
            self.assertEqual(len(self.mostrados), 3)                            # o mesmo turno não avisa duas vezes
        finally:
            config.atualizar_config(lambda c: c["gestoras"].pop(slug, None))


# ---------------------------------------------------------------------------------------------------------------
# Revisão da 1.3: "é do Cérebro" exato (item 5) e gravação sem sobra nem corrida (item 17)
# ---------------------------------------------------------------------------------------------------------------
class TesteEntradaExata(unittest.TestCase):
    def setUp(self):
        _limpar_casa()
        self.p = ganchos_claude.caminho_settings()
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.acl = SEM_ACL.start()

    def tearDown(self):
        SEM_ACL.stop()

    def gravar(self, dados):
        self.p.write_text(json.dumps(dados, indent=2) + "\n", encoding="utf-8")

    def ler(self):
        return json.loads(self.p.read_text(encoding="utf-8"))

    def test_so_o_argumento_sincrono_do_cerebro_conta(self):
        script = str(ganchos_claude.SCRIPT_HOOK).replace("\\", "/")
        self.assertTrue(ganchos_claude.eh_do_cerebro({"type": "command", "command": f"python {script} --sincrono"}))
        self.assertFalse(ganchos_claude.eh_do_cerebro({"type": "command", "command": f"python {script} --outro"}))
        self.assertFalse(ganchos_claude.eh_do_cerebro({"type": "command", "command": "python outro.py --sincrono"}))

    def test_gancho_de_outra_ferramenta_com_nome_parecido_fica(self):
        alheios = [{"type": "http", "url": "https://minha-ci.example.com/api/hooks/claude-stop"},
                   {"type": "http", "url": "http://127.0.0.1:9000/api/hooks/evento-da-ci"},
                   {"type": "http", "url": "http://192.168.0.5:8188/api/hooks/evento"},
                   {"type": "command", "command": "python C:/outra/ferramenta/cerebro_hook.py"},
                   {"type": "command", "command": "bash ~/scripts/cerebro_hook_wrapper.sh"},
                   {"type": "command", "command": f"python {ganchos_claude.SCRIPT_HOOK.as_posix()} --outro-arg"}]
        d = {"hooks": {"Stop": [{"hooks": list(alheios)}]}}
        self.assertEqual(ganchos_claude.tirar_hooks(d), d)                  # a prova da revisão: nada some
        for h in alheios:
            self.assertFalse(ganchos_claude.eh_do_cerebro(h), h)
        self.gravar(d)
        ganchos_claude.instalar(confirmar=True)
        ganchos_claude.remover(confirmar=True)
        self.assertEqual(self.ler(), d)
        self.assertEqual(ganchos_claude.estado()["eventos"], [])

    def test_entradas_ja_instaladas_pela_1_3_continuam_reconhecidas(self):
        script = ganchos_claude.SCRIPT_HOOK.as_posix()
        antigas = [ganchos_claude.entrada_hook(),
                   {"type": "command", "command": f"C:/Python311/pythonw.exe {script}", "async": True},     # outro Python
                   {"type": "command", "command": f'"C:/Program Files/Python/python.exe" "{script}"', "async": True},
                   {"type": "command", "command": f"python {str(ganchos_claude.SCRIPT_HOOK)}"},
                   {"type": "http", "url": "http://127.0.0.1:8177/api/hooks/evento", "timeout": 2},
                   {"type": "http", "url": "http://localhost:8188/api/hooks/evento"}]
        for h in antigas:
            self.assertTrue(ganchos_claude.eh_do_cerebro(h), h)
        self.gravar({"hooks": {"Stop": [{"hooks": antigas + [{"type": "command", "command": "meu.sh"}]}]}})
        ganchos_claude.remover(confirmar=True)
        self.assertEqual(self.ler(), {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "meu.sh"}]}]}})

    def test_statusline_de_outra_ferramenta_com_nome_parecido_nao_e_do_cerebro(self):
        alheia = {"type": "command", "command": "bash ~/bin/cerebro_statusline_turbo.sh"}
        self.assertFalse(ganchos_claude.statusline_do_cerebro(alheia))
        self.assertFalse(ganchos_claude.statusline_do_cerebro({"type": "command", "command": "python C:/outro/cerebro_statusline.py"}))
        self.gravar({"statusLine": alheia})
        with self.assertRaises(ganchos_claude.PrecisaDecidir):              # antes: achava que já era a do Cérebro
            ganchos_claude.instalar(confirmar=True, hooks=False, statusline="instalar")
        ganchos_claude.remover(confirmar=True, hooks=False, statusline=True)
        self.assertEqual(self.ler(), {"statusLine": alheia})
        antiga = {"type": "command", "command": f"C:/Python311/python.exe {ganchos_claude.SCRIPT_STATUS.as_posix()}"}
        self.assertTrue(ganchos_claude.statusline_do_cerebro(antiga))

    def temporarios(self):
        return [x.name for x in self.p.parent.iterdir() if x.name.endswith(".tmp")]

    def test_json_quebrado_nao_deixa_temporario_no_claude(self):
        self.gravar({"model": "opus"})
        with self.assertRaises(ValueError):
            ganchos_claude._gravar_atomico("{quebrado")
        self.assertEqual(self.temporarios(), [])
        self.assertEqual(self.ler(), {"model": "opus"})

    def test_troca_que_falha_nao_deixa_temporario_no_claude(self):
        self.gravar({"model": "opus"})
        real, alvo = os.replace, self.p

        def replace(a, b):
            if Path(b) == alvo:
                raise PermissionError("arquivo em uso pelo Claude Code")
            return real(a, b)
        with mock.patch.object(ganchos_claude.os, "replace", replace), self.assertRaises(PermissionError):
            ganchos_claude.instalar(confirmar=True)
        self.assertEqual(self.temporarios(), [])
        self.assertEqual(self.ler(), {"model": "opus"})

    def test_settings_que_muda_no_meio_nao_e_sobrescrito(self):
        self.gravar({"model": "opus"})
        do_claude = '{\n  "model": "sonnet",\n  "novo": true\n}\n'
        copia_real = ganchos_claude._copia_de_seguranca

        def copia_e_claude_grava(original):                                  # o Claude Code grava enquanto o Cérebro prepara
            r = copia_real(original)
            self.p.write_text(do_claude, encoding="utf-8")
            return r
        with mock.patch.object(ganchos_claude, "_copia_de_seguranca", copia_e_claude_grava), \
                self.assertRaises(ganchos_claude.SettingsMudou):
            ganchos_claude.instalar(confirmar=True)
        self.assertEqual(self.p.read_text(encoding="utf-8"), do_claude)       # nada do que o Claude Code gravou se perdeu
        self.assertEqual(self.temporarios(), [])


if __name__ == "__main__":
    unittest.main()
