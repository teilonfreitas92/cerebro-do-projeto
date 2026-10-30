"""Terminal de verdade no painel (terminais.py e rotas_terminais.py): só o claude, sessão validada, limite, cauda da tela,
aviso de sessão aberta em outro lugar e o WebSocket de ponta a ponta com um "claude" de mentira num pseudo-terminal real."""
import asyncio
import json
import os
import queue
import sys
import time
import unittest
import uuid
from unittest import mock

from testes import _ambiente as amb  # noqa: F401  (pastas de mentira antes do cerebro)
from cerebro import config, terminais
from testes.test_servidor import Base

ECO = "import sys; print('pronto', flush=True); l = sys.stdin.readline(); print('eco:' + l.strip()[::-1], flush=True)"


class PtyFalso:
    def __init__(self, argv=None, cwd=None, env=None, cols=0, rows=0):
        self.argv, self.cwd, self.env, self.tam = argv, cwd, env, (cols, rows)
        self.saida, self.escrito, self.morto, self.pid = queue.Queue(), [], False, 4242

    def ler(self):
        try:
            return self.saida.get(timeout=0.05)
        except queue.Empty:
            return ""

    def escrever(self, texto):
        self.escrito.append(texto)

    def tamanho(self, cols, rows):
        self.tam = (cols, rows)

    def vivo(self):
        return not self.morto

    def matar(self):
        self.morto = True


def esperar(cond, segundos=5):
    fim = time.time() + segundos
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TesteTerminais(unittest.TestCase):
    def setUp(self):
        terminais.parar_todos()
        self.pasta = str(amb.BASE)
        self.criados = []
        p = mock.patch.object(terminais.shutil, "which", return_value="claude-falso")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(terminais.parar_todos)

    def criar(self, argv, cwd, env, cols, rows):
        pty = PtyFalso(argv, cwd, env, cols, rows)
        self.criados.append(pty)
        return pty

    def test_so_roda_o_claude_e_valida_a_sessao(self):
        t = terminais.abrir("p", self.pasta, criar_pty=self.criar)
        self.assertEqual(self.criados[0].argv, ["claude-falso"])
        self.assertEqual(self.criados[0].cwd, self.pasta)
        s = str(uuid.uuid4())
        terminais.abrir("p", self.pasta, s, criar_pty=self.criar)
        self.assertEqual(self.criados[1].argv, ["claude-falso", "--resume", s])
        for ruim in ["x; calc", "--dangerously-skip-permissions", s + " extra", "../" + s]:
            with self.assertRaises(terminais.ErroTerminal):
                terminais.abrir("p", self.pasta, ruim, criar_pty=self.criar)
        self.assertTrue(terminais.ID_TERMINAL.match(t.id))

    def test_sem_claude_instalado_avisa(self):
        with mock.patch.object(terminais.shutil, "which", return_value=None):
            with self.assertRaisesRegex(terminais.ErroTerminal, "Claude Code"):
                terminais.abrir("p", self.pasta, criar_pty=self.criar)

    def test_ambiente_tira_marcas_de_claude_aninhado(self):
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            terminais.abrir("p", self.pasta, criar_pty=self.criar)
        env = self.criados[0].env
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", env)
        self.assertEqual(env["TERM"], "xterm-256color")

    def test_mesma_sessao_reaproveita_e_limite(self):
        s = str(uuid.uuid4())
        a = terminais.abrir("p", self.pasta, s, criar_pty=self.criar)
        self.assertIs(terminais.abrir("p", self.pasta, s, criar_pty=self.criar), a)
        for _ in range(terminais.LIMITE - 1):
            terminais.abrir("p", self.pasta, criar_pty=self.criar)
        with self.assertRaisesRegex(terminais.ErroTerminal, "terminais abertos"):
            terminais.abrir("p", self.pasta, criar_pty=self.criar)
        self.assertEqual(terminais.ativos(), terminais.LIMITE)

    def test_pasta_inexistente_e_tamanho_limitado(self):
        with self.assertRaises(terminais.ErroTerminal):
            terminais.abrir("p", self.pasta + "/nao-existe", criar_pty=self.criar)
        terminais.abrir("p", self.pasta, cols=99999, rows=-3, criar_pty=self.criar)
        self.assertEqual(self.criados[-1].tam, (400, 5))

    def test_tela_assinantes_cauda_e_fim(self):
        t = terminais.abrir("p", self.pasta, criar_pty=self.criar)
        pty = self.criados[0]
        pty.saida.put("olá ")
        self.assertTrue(esperar(lambda: "olá" in t.assinar(lambda x: None)))
        recebidos = []
        cauda = t.assinar(recebidos.append)
        self.assertEqual(cauda, "olá ")
        pty.saida.put("mundo")
        self.assertTrue(esperar(lambda: recebidos == ["mundo"]))
        with mock.patch.object(terminais, "CAUDA", 10):
            pty.saida.put("x" * 30)
            self.assertTrue(esperar(lambda: len(recebidos) == 2))
            self.assertNotIn("olá", t.assinar(lambda x: None))
        pty.matar()
        self.assertTrue(esperar(lambda: recebidos[-1] is None))
        self.assertFalse(t.resumo()["vivo"])
        self.assertEqual(terminais.ativos(), 0)

    def test_fechar_mata_e_tira_da_lista(self):
        t = terminais.abrir("p", self.pasta, criar_pty=self.criar)
        terminais.abrir("outro", self.pasta, criar_pty=self.criar)
        self.assertEqual([r["slug"] for r in terminais.listar("p")], ["p"])
        self.assertTrue(terminais.fechar(t.id))
        self.assertTrue(self.criados[0].morto)
        self.assertIsNone(terminais.achar(t.id))
        self.assertFalse(terminais.fechar(t.id))
        self.assertIsNone(terminais.achar("../../x"))

    def test_sessao_em_uso(self):
        s = str(uuid.uuid4())
        agora = 1_000_000
        self.assertIn("aberta", terminais.sessao_em_uso("p", s, {s}, agora - 9999, agora))
        self.assertIn("2 minutos", terminais.sessao_em_uso("p", s, set(), agora - 30, agora))
        self.assertEqual(terminais.sessao_em_uso("p", s, set(), agora - 600, agora), "")
        terminais.abrir("p", self.pasta, s, criar_pty=self.criar)       # aberta no próprio Cérebro: não conta como "em uso"
        self.assertEqual(terminais.sessao_em_uso("p", s, {s}, agora - 30, agora), "")


@unittest.skipUnless(terminais.python_ok(), "sem pywinpty neste Python")
class TestePtyReal(unittest.TestCase):
    def test_pseudo_terminal_de_verdade_le_e_escreve(self):
        pty = terminais.abrir_pty([sys.executable, "-c", ECO], str(amb.BASE), dict(os.environ), 100, 30)
        try:
            saida = []
            fim = time.time() + 20
            while time.time() < fim and "pronto" not in "".join(saida):
                saida.append(pty.ler())
            pty.escrever("abc\r")
            while time.time() < fim and "eco:cba" not in "".join(saida):
                parte = pty.ler()
                if not parte and not pty.vivo():
                    break
                saida.append(parte)
            self.assertIn("eco:cba", "".join(saida))
        finally:
            pty.matar()


class TesteRotasTerminais(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        terminais.parar_todos()
        self.addCleanup(terminais.parar_todos)
        p1 = mock.patch.object(terminais, "comando_claude", lambda sessao=None: [sys.executable, "-c", ECO])
        p2 = mock.patch("cerebro.agentes.claude_agents", return_value=[])
        p1.start(), p2.start()
        self.addCleanup(p1.stop), self.addCleanup(p2.stop)
        await self.entrar()

    async def test_abrir_exige_origem_e_ws_exige_origem(self):
        r = await self.post(f"/api/p/{self.slug}/terminais", {}, origem=False)
        self.assertEqual(r.status, 403)
        r = await self.http.get(self.base + "/api/terminais/0123456789ab/ws")
        self.assertEqual(r.status, 403)

    @unittest.skipUnless(terminais.python_ok(), "sem pywinpty neste Python")
    async def test_websocket_de_ponta_a_ponta(self):
        r = await self.post(f"/api/p/{self.slug}/terminais", {"cols": 100, "rows": 30})
        self.assertEqual(r.status, 200, await r.text())
        t = await r.json()
        self.assertEqual(t["slug"], self.slug)
        lista = await (await self.http.get(f"{self.base}/api/p/{self.slug}/terminais")).json()
        self.assertEqual([x["id"] for x in lista["terminais"]], [t["id"]])
        ws = await self.http.ws_connect(f"{self.base}/api/terminais/{t['id']}/ws", headers={"Origin": self.base})
        tela = ""

        async def ate(texto):
            nonlocal tela
            while texto not in tela:
                m = json.loads((await asyncio.wait_for(ws.receive(), 20)).data)
                if m["t"] == "fim":
                    return m
                tela += m["d"]

        await ate("pronto")
        await ws.send_str(json.dumps({"t": "r", "c": 90, "l": 20}))
        await ws.send_str(json.dumps({"t": "e", "d": "abc\r"}))
        await ate("eco:cba")
        self.assertIn("eco:cba", tela)
        await ws.close()
        r = await self.post(f"/api/terminais/{t['id']}/fechar", {})
        self.assertEqual(r.status, 200)
        self.assertEqual(terminais.listar(self.slug), [])

    async def test_sessao_aberta_em_outro_lugar_pede_confirmacao(self):
        s = str(uuid.uuid4())
        pasta = config.PROJETOS_CLAUDE / self.slug
        (pasta / (s + ".jsonl")).write_text(json.dumps({"type": "user", "cwd": str(self.real)}) + "\n", encoding="utf-8")
        from cerebro import indice
        indice.listar_arquivos(self.slug)
        with mock.patch.object(terminais, "abrir", return_value=None) as abrir:
            r = await self.post(f"/api/p/{self.slug}/terminais", {"sessao": s})
            self.assertEqual(r.status, 409)
            self.assertTrue((await r.json())["em_uso"])
            abrir.assert_not_called()
        r = await self.post(f"/api/p/{self.slug}/terminais", {"sessao": "nao-e-uuid"})
        self.assertEqual(r.status, 400)
        r = await self.post(f"/api/p/{self.slug}/terminais", {"sessao": str(uuid.uuid4())})
        self.assertEqual(r.status, 400)                   # sessão que não é deste projeto


if __name__ == "__main__":
    unittest.main()
