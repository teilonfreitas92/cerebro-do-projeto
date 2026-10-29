r"""Testes das TRAVAS de segurança (incidente de 29/10/2026: um teste apagou ~/.claude/projects).

Só usa caminhos FALSOS: pastas que se resolvem fora do ambiente de teste mas que NÃO são as reais do dono
(o 'home' falso fica dentro de BASE de outro teste; nada em a pasta real do dono é tocada).
"""
import tempfile
import unittest
from pathlib import Path

from testes import _ambiente as amb
from cerebro import config


class TesteApagarDosTestes(unittest.TestCase):
    def setUp(self):
        # "mundo de fora": pasta que existe mas NÃO está dentro de BASE (nem é a pasta real do dono)
        self.fora = Path(tempfile.mkdtemp(prefix="cerebro_fora_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.fora, ignore_errors=True))
        (self.fora / ".claude" / "projects" / "proj").mkdir(parents=True)
        (self.fora / ".claude" / "projects" / "proj" / "s.jsonl").write_text("{}", encoding="utf-8")
        (self.fora / "Desktop" / "MeuProjeto").mkdir(parents=True)
        (self.fora / "Desktop" / "MeuProjeto" / "a.py").write_text("x", encoding="utf-8")

    def test_recusa_pasta_dot_claude_falsa(self):
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(self.fora / ".claude")
        self.assertTrue((self.fora / ".claude" / "projects" / "proj" / "s.jsonl").is_file())

    def test_recusa_pasta_de_projeto_falsa(self):
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(self.fora / "Desktop" / "MeuProjeto")
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(self.fora / "Desktop" / "MeuProjeto" / "a.py")
        self.assertTrue((self.fora / "Desktop" / "MeuProjeto" / "a.py").is_file())

    def test_recusa_home_e_o_proprio_home_do_usuario_sem_tocar_em_nada(self):
        # o caminho real só é PASSADO à trava (que recusa antes de qualquer E/S); nada é criado nem lido
        for real in (Path.home() / ".claude", Path.home() / ".claude" / "projects", Path.home() / ".cerebro", Path.home()):
            with self.assertRaises(amb.ApagarRecusado):
                amb.apagar(real)

    def test_recusa_a_propria_base_e_o_pai_dela(self):
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(amb.BASE)
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(amb.BASE.parent)

    def test_recusa_fuga_por_dois_pontos(self):
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(amb.BASE / "mundo" / ".." / ".." / "x")

    def test_apaga_dentro_da_base(self):
        d = amb.BASE / "descartavel" / "sub"
        d.mkdir(parents=True)
        (d / "f.txt").write_text("1", encoding="utf-8")
        amb.apagar(amb.BASE / "descartavel")
        self.assertFalse((amb.BASE / "descartavel").exists())
        amb.apagar(amb.BASE / "nao_existe")          # ausente: sem erro

    def test_a_trava_vale_com_base_falsa(self):
        with self.assertRaises(amb.ApagarRecusado):
            amb.apagar(self.fora / ".claude", base=amb.BASE)


class TesteRemocaoDoApp(unittest.TestCase):
    def setUp(self):
        self.fora = Path(tempfile.mkdtemp(prefix="cerebro_fora_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.fora, ignore_errors=True))

    def test_recusa_fora_da_casa(self):
        arq = self.fora / "a.txt"
        arq.write_text("x", encoding="utf-8")
        with self.assertRaises(config.RemocaoRecusada):
            config.remover(arq)
        with self.assertRaises(config.RemocaoRecusada):
            config.remover(self.fora, pasta=True)
        self.assertTrue(arq.is_file())

    def test_recusa_pastas_do_claude_e_de_projeto(self):
        proj = config.PROJETOS_CLAUDE / "slug"
        proj.mkdir(parents=True, exist_ok=True)
        conversa = proj / "s.jsonl"
        conversa.write_text("{}", encoding="utf-8")
        for alvo, pasta in ((conversa, False), (proj, True), (config.PROJETOS_CLAUDE, True), (config.CLAUDE, True)):
            with self.assertRaises(config.RemocaoRecusada):
                config.remover(alvo, pasta=pasta)
        self.assertTrue(conversa.is_file())

    def test_recusa_a_propria_casa_e_o_home_real(self):
        with self.assertRaises(config.RemocaoRecusada):
            config.remover(config.CASA, pasta=True)
        for real in (Path.home() / ".claude", Path.home() / ".claude" / "projects", Path.home() / ".cerebro"):
            with self.assertRaises(config.RemocaoRecusada):
                config.remover(real, pasta=True)

    def test_apaga_dentro_da_casa(self):
        config.garantir_casa()
        arq = config.CASA / "projetos" / "x" / "f.txt"
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text("x", encoding="utf-8")
        config.remover(arq)
        self.assertFalse(arq.exists())
        config.remover(config.CASA / "projetos" / "x", pasta=True)
        config.remover(config.CASA / "nao_existe.txt")           # ausente: sem erro


if __name__ == "__main__":
    unittest.main()
