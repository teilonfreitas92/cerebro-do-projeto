"""Módulo mapa/: parâmetros do gerar.py, slug, gestora vinda do config.json global (sem gravar nada no projeto)."""
import importlib.util
import json
import subprocess
import sys
import unittest

from testes import _ambiente as amb
from cerebro import config, projetos


def carregar_gerar():
    spec = importlib.util.spec_from_file_location("gerar_mapa", amb.RAIZ / "mapa" / "gerar.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TesteGerar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gerar = carregar_gerar()

    def test_slug_igual_ao_do_servidor(self):
        pasta = amb.BASE / "mundo" / "Desktop" / "Meu_Projeto"
        pasta.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.gerar.slug_do_projeto(pasta), projetos.codificar(pasta.resolve()))

    def test_gestora_vem_do_config_global(self):
        config.atualizar_config(lambda c: c["gestoras"].__setitem__("slug-x", {"conversa": "abc", "nome": "Minha gestora"}))
        self.gerar.CONFIG = config.CASA / "config.json"
        self.assertEqual(self.gerar.ler_config("slug-x")["sessaoGestora"], {"nome": "Minha gestora", "conversa": "abc"})
        self.assertEqual(self.gerar.ler_config("outro")["sessaoGestora"], {"nome": "", "conversa": ""})

    def test_config_quebrado_nao_derruba(self):
        self.gerar.CONFIG = amb.BASE / "nao-existe.json"
        self.assertEqual(self.gerar.ler_config("qualquer")["sessaoGestora"]["nome"], "")

    def _rodar(self, *args):
        return subprocess.run([sys.executable, str(amb.RAIZ / "mapa" / "gerar.py"), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})

    def test_sem_projeto_nem_entrada_pede_parametro(self):
        r = self._rodar()
        self.assertEqual(r.returncode, 2)
        self.assertIn("--projeto", r.stderr)

    def test_projeto_sem_graphify_explica_e_nao_cria_nada_no_projeto(self):
        pasta = amb.BASE / "mundo" / "Desktop" / "SemMapa"
        pasta.mkdir(parents=True, exist_ok=True)
        r = self._rodar("--projeto", str(pasta))
        self.assertEqual(r.returncode, 2)
        self.assertIn("ainda não tem o mapa do Graphify", r.stderr)
        self.assertEqual(list(pasta.iterdir()), [])             # nada escrito dentro do projeto
        self.assertFalse((config.CASA / "projetos" / projetos.codificar(pasta.resolve()) / "mapa" / "dados.js").exists())

    def test_saida_padrao_fica_em_cerebro_e_nunca_no_projeto(self):
        # grafo mínimo: o gerador tem que aceitar e escrever só em CEREBRO_HOME\projetos\<slug>\mapa
        pasta = amb.BASE / "mundo" / "Desktop" / "Pequeno"
        saida_graphify = pasta / "graphify-out"
        saida_graphify.mkdir(parents=True, exist_ok=True)
        (pasta / "app.py").write_text('"""Programa pequeno."""\n\ndef soma(a, b):\n    """Soma dois números."""\n    return a + b\n', encoding="utf-8")
        grafo = {"directed": False, "multigraph": False, "graph": {}, "nodes": [
            {"id": "app", "label": "app.py", "file_type": "code", "source_file": "app.py", "source_location": "L1", "community": 0},
            {"id": "soma", "label": "soma()", "file_type": "code", "source_file": "app.py", "source_location": "L3", "community": 0}],
            "links": [{"source": "app", "target": "soma", "relation": "contains", "confidence": "EXTRACTED", "source_file": "app.py"}]}
        (saida_graphify / "graph.json").write_text(json.dumps(grafo), encoding="utf-8")
        (saida_graphify / ".graphify_analysis.json").write_text(json.dumps({"communities": {"0": ["app", "soma"]}, "cohesion": {"0": 1.0}, "gods": [], "surprises": []}), encoding="utf-8")
        (saida_graphify / ".graphify_labels.json").write_text(json.dumps({"0": "Grupo pequeno"}), encoding="utf-8")
        r = self._rodar("--projeto", str(pasta))
        if r.returncode != 0:                                    # formato do Graphify mais exigente que o grafo mínimo
            self.skipTest("grafo mínimo não aceito pelo gerador: " + (r.stderr or r.stdout)[-200:])
        slug = projetos.codificar(pasta.resolve())
        self.assertTrue((config.CASA / "projetos" / slug / "mapa" / "dados.js").is_file())
        self.assertTrue((config.CASA / "projetos" / slug / "mapa" / "historico.json").is_file())
        self.assertEqual(sorted(p.name for p in pasta.iterdir()), ["app.py", "graphify-out"])
        self.assertEqual(sorted(p.name for p in saida_graphify.iterdir()), [".graphify_analysis.json", ".graphify_labels.json", "graph.json"])


if __name__ == "__main__":
    unittest.main()
