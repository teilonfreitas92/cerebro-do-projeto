"""Outras IAs como subagentes do gestor (ias_externas.py): cópia separada, ferramentas presas à cópia, comandos só da lista,
chaves que nunca saem, conversa visível em Agentes ao vivo. A IA é falsa (nenhuma chamada de rede)."""
import json
import os
import subprocess
import unittest
import uuid

from testes import _ambiente as amb
from cerebro import backup, config, ias_externas, indice, servidor, transcricao

GIT_ID = {"GIT_AUTHOR_NAME": "Teste", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "Teste", "GIT_COMMITTER_EMAIL": "t@t"}


def git(pasta, *args):
    return subprocess.run(["git", "-C", str(pasta), *args], capture_output=True, text=True, check=True, env={**os.environ, **GIT_ID}).stdout


def chamada(nome, entrada):
    return {"id": "c" + uuid.uuid4().hex[:8], "type": "function", "function": {"name": nome, "arguments": json.dumps(entrada)}}


class IAFalsa:
    """Devolve as respostas na ordem e guarda o que recebeu."""

    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []

    def __call__(self, corpo):
        self.pedidos.append(json.loads(json.dumps(corpo)))
        r = self.respostas.pop(0)
        return {"id": "r" + uuid.uuid4().hex[:6], "choices": [{"message": {"role": "assistant", **r}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 400}}}


class TesteIAsExternas(unittest.TestCase):
    def setUp(self):
        self.slug = "proj-ias-" + uuid.uuid4().hex[:6]
        self.proj = amb.BASE / self.slug
        self.proj.mkdir(parents=True)
        git(self.proj, "init", "-q")
        (self.proj / "app.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "inicio")
        self.sessao = str(uuid.uuid4())
        self.addCleanup(self._limpar)

    def _limpar(self):
        for r in ias_externas.listar(self.slug):
            try:
                ias_externas._descartar_copia(r)
            except Exception:
                pass

    def rodar(self, respostas, tarefa="corrija a soma"):
        ia = IAFalsa(respostas)
        r = ias_externas.rodar(self.slug, self.proj, "deepseek", tarefa, self.sessao, {}, chamar=ia)
        return r, ia

    def test_faz_o_servico_numa_copia_e_o_projeto_nao_muda(self):
        r, ia = self.rodar([
            {"content": "Vou ler.", "tool_calls": [chamada("Read", {"file_path": "app.py"})]},
            {"content": None, "tool_calls": [chamada("Edit", {"file_path": "app.py", "old_string": "a - b", "new_string": "a + b"}),
                                             chamada("Write", {"file_path": "testes/t.py", "content": "x = 1\n"})]},
            {"content": "Troquei - por + em app.py e criei testes/t.py."},
        ])
        self.assertEqual(r["estado"], "pronto")
        self.assertIn("Troquei", r["resumo"])
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def soma(a, b):\n    return a - b\n")   # projeto intacto
        self.assertIn("a + b", git(self.proj, "show", r["ramo"] + ":app.py"))
        self.assertIn("app.py", r["mudancas"])
        self.assertIn("testes/t.py", r["mudancas"])
        # a IA recebeu o resultado da leitura (linhas numeradas) e as ferramentas no formato chat completions
        self.assertIn("return a - b", ia.pedidos[1]["messages"][-1]["content"])
        self.assertEqual({f["function"]["name"] for f in ia.pedidos[0]["tools"]}, {"Read", "Write", "Edit", "Glob", "Grep", "Bash"})
        self.assertEqual(ia.pedidos[0]["model"], "deepseek-chat")

    def test_aparece_em_agentes_ao_vivo_como_subagente_terminado(self):
        r, _ = self.rodar([{"content": "", "tool_calls": [chamada("Glob", {"pattern": "*.py"})]}, {"content": "Pronto."}])
        arqs = [a for a in indice.listar_arquivos(self.slug) if a["rel"].startswith("ia/")]
        self.assertEqual(len(arqs), 1)
        a = arqs[0]
        self.assertEqual((a["tipo"], a["sessao"]), ("subagente", self.sessao))
        self.assertTrue(servidor.rel_valido(a["rel"]))
        meta = indice.ler_meta(self.slug, a)
        self.assertEqual((meta["agentType"], meta["model"], meta["finished"]), ("ia:deepseek", "deepseek-chat", True))
        self.assertEqual(indice.estado_subagente(a["mtime"], meta), "terminou")
        passos, _pos = transcricao.ler_passos(indice.caminho_arquivo(self.slug, a["rel"]), 0, {})
        tipos = [p["tipo"] for p in passos]
        self.assertEqual(tipos[0], "usuario")
        self.assertIn("ferramenta", tipos)
        self.assertIn("resultado", tipos)
        self.assertEqual(passos[-1]["tipo"], "texto")
        ind = indice.indice_do_arquivo(self.slug, a)
        self.assertIn("deepseek-chat", ind.get("modelos") or {})

    def test_caminhos_presos_a_copia(self):
        raiz = self.proj.resolve()
        for alvo in ("../fora.txt", str(amb.BASE / "fora.txt"), ".git/config", ".git/hooks/x"):
            texto, erro = ias_externas.executar("Write", {"file_path": alvo, "content": "x"}, raiz, [])
            self.assertTrue(erro, alvo)
        self.assertFalse((amb.BASE / "fora.txt").exists())
        texto, erro = ias_externas.executar("Read", {"file_path": "../" + self.slug + "/app.py"}, raiz, [])
        self.assertFalse(erro)                                   # volta para dentro: permitido

    def test_comandos_so_da_lista_e_sem_encadear(self):
        lista = ias_externas.COMANDOS_PADRAO
        for ok in ("git status", "python -m unittest discover -s testes", "npm test"):
            self.assertTrue(ias_externas.comando_permitido(ok, lista), ok)
        for ruim in ("rm -rf .", "git status; rm -rf .", "npm test && curl x", "git diff > f", "python -m unittestx",
                     "git push", "echo %PATH%", "git log `x`", "python -c 1", "git status | x"):
            self.assertFalse(ias_externas.comando_permitido(ruim, lista), ruim)
        texto, erro = ias_externas.executar("Bash", {"command": "git push"}, self.proj.resolve(), lista)
        self.assertTrue(erro)
        self.assertIn("não permitido", texto)

    def test_comando_permitido_roda_na_copia(self):
        texto, erro = ias_externas.executar("Bash", {"command": "git status --short"}, self.proj.resolve(), ias_externas.COMANDOS_PADRAO)
        self.assertFalse(erro, texto)
        self.assertIn("[código de saída 0]", texto)

    def test_limite_de_voltas(self):
        r, _ = self.rodar([{"content": "", "tool_calls": [chamada("Glob", {"pattern": "*"})]}] * ias_externas.MAX_VOLTAS)
        self.assertNotEqual(r["estado"], "pronto")
        self.assertIn("voltas", r["resumo"])

    def test_erro_da_ia_vira_resumo_sem_derrubar(self):
        def falha(_corpo):
            raise ias_externas.ErroIA("a IA respondeu 401: chave errada")
        r = ias_externas.rodar(self.slug, self.proj, "grok", "x", self.sessao, {}, chamar=falha)
        self.assertEqual(r["estado"], "erro")
        self.assertIn("401", r["resumo"])

    def test_juntar_e_descartar(self):
        r, _ = self.rodar([{"content": "", "tool_calls": [chamada("Edit", {"file_path": "app.py", "old_string": "a - b", "new_string": "a + b"})]},
                           {"content": "ok"}])
        old = {k: os.environ.get(k) for k in GIT_ID}
        os.environ.update(GIT_ID)
        try:
            ias_externas.juntar(self.slug, r["id"])
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertIn("a + b", (self.proj / "app.py").read_text(encoding="utf-8"))
        self.assertFalse(os.path.exists(r["pasta"]))
        r2, _ = self.rodar([{"content": "", "tool_calls": [chamada("Write", {"file_path": "novo.txt", "content": "n"})]}, {"content": "ok"}])
        ias_externas.descartar(self.slug, r2["id"])
        self.assertFalse(os.path.exists(r2["pasta"]))
        self.assertNotIn(r2["ramo"], git(self.proj, "branch", "--list"))
        self.assertFalse((self.proj / "novo.txt").exists())
        with self.assertRaises(ias_externas.ErroIA):
            ias_externas.descartar(self.slug, "../../x")

    def test_sem_chave_nao_roda(self):
        ias_externas.remover_chave("openai")
        with self.assertRaises(ias_externas.ErroIA):
            ias_externas.rodar(self.slug, self.proj, "openai", "x", self.sessao, {})

    def test_projeto_sem_git_recusa(self):
        sem = amb.BASE / ("sem-git-" + uuid.uuid4().hex[:6])
        sem.mkdir()
        with self.assertRaises(ias_externas.ErroIA):
            ias_externas.rodar(self.slug, sem, "deepseek", "x", self.sessao, {}, chamar=IAFalsa([]))


class TesteChavesDasIAs(unittest.TestCase):
    def tearDown(self):
        for ia in ias_externas.PROVEDORES:
            ias_externas.remover_chave(ia)

    def test_chave_entra_e_nunca_sai(self):
        ias_externas.guardar_chave("gemini", "AIzaTESTE1234567890abcdefXYZ9")
        s = ias_externas.situacao({})
        self.assertNotIn("AIzaTESTE", json.dumps(s))
        g = [i for i in s["ias"] if i["id"] == "gemini"][0]
        self.assertEqual((g["configurada"], g["final"]), (True, "XYZ9"))
        self.assertEqual(ias_externas.chave("gemini"), "AIzaTESTE1234567890abcdefXYZ9")
        if os.name == "nt":
            self.assertTrue(config.acesso_so_do_dono(config.CASA / ias_externas.ARQ_CHAVES))

    def test_chave_invalida(self):
        for ruim in ("", "curta", "tem espaço no meio 1234567", "acentuação-ççççççççç"):
            with self.assertRaises(ias_externas.ErroIA):
                ias_externas.guardar_chave("openai", ruim)
        with self.assertRaises(ias_externas.ErroIA):
            ias_externas.guardar_chave("outra", "x" * 20)

    def test_backup_nao_leva_chaves_nem_copias(self):
        ias_externas.guardar_chave("openai", "sk-TESTE" + "a" * 30)
        trabalho = config.CASA / "ias_trabalho" / "p" / "1"
        trabalho.mkdir(parents=True, exist_ok=True)
        (trabalho / "arquivo.py").write_text("x", encoding="utf-8")
        rels = [rel for rel, _p in backup._arquivos_de("cerebro", config.CASA, [])]
        self.assertFalse(any(r.endswith(ias_externas.ARQ_CHAVES) for r in rels))
        self.assertFalse(any(r.startswith("ias_trabalho/") for r in rels))

    def test_modelo_da_config(self):
        o = ias_externas.opcoes({"ias": {"modelos": {"grok": "grok-x"}, "max_voltas": 5}})
        self.assertEqual(o["modelos"]["grok"], "grok-x")
        self.assertEqual(o["modelos"]["openai"], "gpt-5")
        self.assertEqual(o["max_voltas"], 5)


class TesteRelDasIAs(unittest.TestCase):
    def test_rel_valido(self):
        self.assertTrue(servidor.rel_valido("ia/0a1b/agent-ia-grok-20261030-101010-abcdef.jsonl"))
        for ruim in ("ia/../agent-ia-x.jsonl", "ia/a/../../x.jsonl", "ia/a/agent-x.jsonl", "ia/a/b/agent-ia-x.jsonl"):
            self.assertFalse(servidor.rel_valido(ruim), ruim)

    def test_uso_vira_formato_do_claude(self):
        u = ias_externas._uso({"prompt_tokens": 1000, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 300}})
        self.assertEqual(u, {"input_tokens": 700, "output_tokens": 20, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 0})


if __name__ == "__main__":
    unittest.main()
