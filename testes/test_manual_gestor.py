"""Manual do gestor: GESTOR.md curto e sem dado pessoal, regerado só quando muda, recado uma vez por versão por sessão, e o
bloco no CLAUDE.local.md (idempotente, reversível, recusa arquivo rastreado, .git/info/exclude). Tudo em pasta temporária."""
import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import config, escrita_projeto, ligacoes, manual_gestor, manual_projeto
from cerebro.escrita_projeto import EscritaRecusada
from testes.test_portatil import EMAIL, EMAIL_OK, USUARIOS_OK, _proibidos

import cerebro_cli  # noqa: E402  (testes já pôs a raiz no sys.path)


class Base(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        for f in ("GESTOR.md", "gestor_manual.json"):
            amb.apagar(config.CASA / f)

    def tearDown(self):
        self.desmontar_mundo()


class TesteGestorMd(Base):
    def test_menos_de_1500_tokens(self):
        r = manual_gestor.gerar()
        texto = Path(r["caminho"]).read_text(encoding="utf-8")
        self.assertLessEqual(len(texto) / 4, manual_gestor.LIMITE_TOKENS)
        self.assertLessEqual(r["tokens"], manual_gestor.LIMITE_TOKENS)
        for trecho in ("gestora limpar", "clear_session", '"self"', "NÃO limpe", "compacta sozinho", "capítulo", "nunca é trocada",
                       "Qualidade acima de economia", "| tipo | modelo |", "decisao", "tarefas <projeto> --novas"):
            self.assertIn(trecho, texto)
        for fora in ("start_session", "delete_session", "gestora preparar"):        # troca por sessão nova não é o padrão
            self.assertNotIn(fora, texto.split("## O que mudou")[0])
        self.assertRegex(texto.splitlines()[0], r"^<!-- cerebro:gestor versao=\S+ hash=[0-9a-f]{12}")

    def test_sem_dado_pessoal(self):
        with mock.patch.object(manual_gestor, "RAIZ", Path.home() / "Programas" / "Cerebro"):
            texto = manual_gestor.montar()
        self.assertIn("~/Programas/Cerebro", texto)                   # pasta do usuário vira ~
        for rx in _proibidos():
            self.assertIsNone(rx.search(texto), rx.pattern)
        for m in EMAIL.finditer(texto):
            self.assertTrue(m.group(0).lower().endswith(EMAIL_OK), m.group(0))
        for m in re.finditer(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"']+)", texto):
            self.assertIn(m.group(1).lower(), USUARIOS_OK)

    def test_regera_so_quando_muda_e_faixa_some_com_um_clique(self):
        self.assertTrue(manual_gestor.gerar()["mudou"])
        self.assertFalse(manual_gestor.gerar()["mudou"])
        e = manual_gestor.estado()
        self.assertTrue(e["mostrar_faixa"])
        self.assertFalse(manual_gestor.marcar_visto()["mostrar_faixa"])
        config.atualizar_config(lambda c: c["agentes_regras"][0].update(nome="Outro nome"))    # conteúdo mudou: refaz, sem faixa nova
        self.assertTrue(manual_gestor.gerar()["mudou"])
        self.assertFalse(manual_gestor.estado()["mostrar_faixa"])
        antes = manual_gestor.__version__
        with mock.patch.object(manual_gestor, "__version__", "9.9.9"):                        # versão nova: faixa de novo
            self.assertEqual(manual_gestor.gerar()["versao_anterior"], antes)
            self.assertTrue(manual_gestor.estado()["mostrar_faixa"])

    def test_mudancas_vem_do_changelog(self):
        m = manual_gestor.mudancas_do_changelog()
        self.assertTrue(m)
        self.assertNotIn("Para o gestor", " ".join(m))

    def test_recado_uma_vez_por_versao_por_sessao(self):
        manual_gestor.gerar()
        ev = {"evento": "UserPromptSubmit", "slug": self.slug, "session_id": amb.GESTORA_ID}
        r = ligacoes._aviso_manual(ev)
        self.assertTrue(r.startswith("Cérebro atualizado para "))
        self.assertIn("GESTOR.md", r)
        self.assertIsNone(ligacoes._aviso_manual(ev))                                         # mesma versão, mesma sessão
        self.assertIsNone(ligacoes._aviso_manual({**ev, "session_id": "outra-sessao"}))       # não é a gestora
        with mock.patch.object(manual_gestor, "__version__", "9.9.9"):
            manual_gestor.gerar()
            self.assertIn("9.9.9", ligacoes._aviso_manual(ev))
            self.assertIsNone(ligacoes._aviso_manual(ev))

    def test_cli_gerar(self):
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(cerebro_cli.main(["manual", "--gerar"]), 0)
        self.assertIn("GESTOR.md", s.getvalue())


class TesteClaudeLocal(Base):
    def setUp(self):
        super().setUp()
        self.p = {"slug": self.slug, "nome": "Falso", "caminho": str(self.real), "oculto": False}
        self.arq = self.real / "CLAUDE.local.md"

    def git(self, rastreado=False, ignorado=False):
        (self.real / ".git" / "info").mkdir(parents=True, exist_ok=True)

        def falso(raiz, args):
            if args[0] == "ls-files":
                return 0 if rastreado else 1
            return 0 if ignorado else 1
        return mock.patch.object(manual_projeto, "rodar_git", side_effect=falso)

    def test_sem_git_cria_so_o_bloco_e_desfaz_tirando_so_o_bloco(self):
        r = manual_projeto.aplicar(self.p, "instalar", confirmar=True)
        self.assertFalse(r["nada_a_fazer"])
        txt = self.arq.read_text(encoding="utf-8")
        self.assertEqual(txt.count(manual_projeto.INICIO), 1)
        self.assertIn("GESTOR.md", txt)
        self.assertTrue(manual_projeto.aplicar(self.p, "instalar", confirmar=True)["nada_a_fazer"])      # idempotente
        manual_projeto.aplicar(self.p, "remover", confirmar=True)
        self.assertFalse(self.arq.exists())                                    # só tinha o bloco: foi para as cópias
        self.assertTrue(list(escrita_projeto.pasta_copias(self.slug).rglob("CLAUDE.local.md")))

    def test_arquivo_existente_volta_igual(self):
        original = "# minhas notas\r\nlinha 2\r\n"
        self.arq.write_bytes(original.encode("utf-8"))
        manual_projeto.aplicar(self.p, "instalar", confirmar=True)
        self.assertTrue(self.arq.read_text(encoding="utf-8").startswith("# minhas notas"))
        manual_projeto.aplicar(self.p, "remover", confirmar=True)
        self.assertEqual(self.arq.read_bytes().decode("utf-8"), original)

    def test_recusa_arquivo_rastreado_pelo_git(self):
        with self.git(rastreado=True):
            with self.assertRaises(EscritaRecusada):
                manual_projeto.previa(self.p, "instalar")
            with self.assertRaises(EscritaRecusada):
                manual_projeto.aplicar(self.p, "instalar", confirmar=True)
        self.assertFalse(self.arq.exists())

    def test_nao_ignorado_acrescenta_no_exclude_e_mostra_na_previa(self):
        exclude = self.real / ".git" / "info" / "exclude"
        with self.git(ignorado=False):
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text("# padrão do git\n", encoding="utf-8")
            pv = manual_projeto.previa(self.p, "instalar")
            self.assertEqual([a["rel"] for a in pv["arquivos"]], ["CLAUDE.local.md", ".git/info/exclude"])
            self.assertIn("+CLAUDE.local.md", pv["arquivos"][1]["diff"])
            manual_projeto.aplicar(self.p, "instalar", confirmar=True, assinatura=pv["assinatura"])
            linhas = exclude.read_text(encoding="utf-8").splitlines()
            self.assertEqual(linhas[0], "# padrão do git")
            self.assertIn("CLAUDE.local.md", linhas)
            manual_projeto.aplicar(self.p, "remover", confirmar=True)
            self.assertEqual(exclude.read_text(encoding="utf-8"), "# padrão do git\n")     # a linha do Cérebro sai junto

    def test_ja_ignorado_nao_mexe_no_exclude(self):
        with self.git(ignorado=True):
            pv = manual_projeto.previa(self.p, "instalar")
        self.assertEqual([a["rel"] for a in pv["arquivos"]], ["CLAUDE.local.md"])

    def test_sem_confirmar_ou_previa_velha_nao_grava(self):
        with self.assertRaises(EscritaRecusada):
            manual_projeto.aplicar(self.p, "instalar")
        pv = manual_projeto.previa(self.p, "instalar")
        self.arq.write_text("mudou depois da prévia\n", encoding="utf-8")
        with self.assertRaises(EscritaRecusada):
            manual_projeto.aplicar(self.p, "instalar", confirmar=True, assinatura=pv["assinatura"])

    def test_trava_so_libera_info_exclude_dentro_do_git(self):
        (self.real / ".git" / "info").mkdir(parents=True, exist_ok=True)
        escrita_projeto.alvo_seguro(self.real, ".git/info/exclude")
        for rel in (".git/config", ".git/info/attributes", ".git/info/exclude/../config"):
            with self.assertRaises(EscritaRecusada):
                escrita_projeto.alvo_seguro(self.real, rel)

    def test_desinstalar_oferece_tirar_so_o_bloco(self):
        self.arq.write_text("notas\n", encoding="utf-8")
        manual_projeto.aplicar(self.p, "instalar", confirmar=True)
        with mock.patch.object(manual_projeto.projetos, "descobrir", return_value=[self.p]):
            ditos = []
            feitos = manual_projeto.desinstalar_passo(lambda t: True, ditos.append)
        self.assertEqual(feitos, ["Falso"])
        self.assertEqual(self.arq.read_text(encoding="utf-8"), "notas\n")

    def test_cli_previa_e_instalar(self):
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(cerebro_cli.main(["manual", self.slug, "--previa"]), 0)
            self.assertFalse(self.arq.exists())
            self.assertEqual(cerebro_cli.main(["manual", self.slug, "--instalar"]), 2)       # sem --confirmar
            self.assertEqual(cerebro_cli.main(["manual", self.slug, "--instalar", "--confirmar"]), 0)
        self.assertIn("CLAUDE.local.md", s.getvalue())
        self.assertTrue(manual_projeto.instalado(self.p))


if __name__ == "__main__":
    unittest.main()
