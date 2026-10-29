import json
import unittest
from pathlib import Path

from testes import _ambiente as amb
from cerebro import config, projetos


def criar_projeto(nome_pasta_real, jsonl_cwd=None, nome_claude=None):
    """Cria a pasta real do projeto (no temporário) e a pasta correspondente em .claude/projects com uma sessão."""
    real = amb.BASE / "mundo" / nome_pasta_real
    real.mkdir(parents=True, exist_ok=True)
    nome = nome_claude or projetos.codificar(real)
    pasta = config.PROJETOS_CLAUDE / nome
    pasta.mkdir(parents=True, exist_ok=True)
    cwd = str(jsonl_cwd if jsonl_cwd is not None else real)
    (pasta / "s1.jsonl").write_text(json.dumps({"type": "queue-operation"}) + "\n" + json.dumps({"type": "user", "cwd": cwd, "message": {}}) + "\n",
                                    encoding="utf-8")
    return real, nome


class TesteDescoberta(unittest.TestCase):
    def setUp(self):
        amb.apagar(config.CASA / "config.json")             # config limpa: nenhum "nunca_entrar" de outro teste
        amb.apagar(config.PROJETOS_CLAUDE)
        amb.apagar(amb.BASE / "mundo")
        config.PROJETOS_CLAUDE.mkdir(parents=True, exist_ok=True)
        self.home_antes = projetos.HOME
        projetos.HOME = amb.BASE / "mundo"          # a "pasta do usuário" do teste
        (amb.BASE / "mundo").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        projetos.HOME = self.home_antes
        projetos.descobrir(forcar=True)

    def test_acha_projeto_normal_pelo_cwd(self):
        real, nome = criar_projeto("Desktop/Loja")
        lista = projetos.descobrir(forcar=True)
        self.assertEqual([p["slug"] for p in lista], [nome])
        self.assertEqual(Path(lista[0]["caminho"]).resolve(), real.resolve())
        self.assertEqual(lista[0]["nome"], "Loja")

    def test_ignora_worktrees_temp_scratch_e_dados(self):
        criar_projeto("Desktop/Bom")
        criar_projeto("Desktop/Loja/.claude/worktrees/zen-perlman", nome_claude="C--Users-ana-Desktop-Loja--claude-worktrees-zen-perlman-545754")
        criar_projeto("AppData/Local/Temp", nome_claude="C--Users-ana-AppData-Local-Temp")
        criar_projeto("AppData/Roaming/Claude/scratch-workspaces/x/scratch-1", nome_claude="C--Users-ana-AppData-Roaming-Claude-scratch-workspaces-x-scratch-1")
        lista = projetos.descobrir(forcar=True)
        self.assertEqual([p["nome"] for p in lista], ["Bom"])

    def test_nunca_entrar_vem_da_configuracao_de_cada_pessoa(self):
        criar_projeto("Desktop/Financeiro")
        criar_projeto("Desktop/robo_financeiro")
        criar_projeto("Desktop/Normal")
        # sem configuração, todo projeto entra
        self.assertEqual(sorted(p["nome"] for p in projetos.descobrir(forcar=True)), ["Financeiro", "Normal", "robo_financeiro"])
        config.atualizar_config(lambda c: c["nunca_entrar"].append("financeiro"))
        self.assertEqual([p["nome"] for p in projetos.descobrir(forcar=True)], ["Normal"])
        with self.assertRaises(ValueError):                    # nem como projeto extra
            projetos.adicionar_extra(str(amb.BASE / "mundo" / "Desktop" / "Financeiro"))

    def test_ignora_a_pasta_do_usuario_inteira(self):
        _, nome = criar_projeto("", nome_claude=projetos.codificar(amb.BASE / "mundo"), jsonl_cwd=amb.BASE / "mundo")
        criar_projeto("Desktop/Ok")
        self.assertEqual([p["nome"] for p in projetos.descobrir(forcar=True)], ["Ok"])

    def test_pasta_que_nao_existe_mais_some(self):
        real, _ = criar_projeto("Desktop/Apagado")
        amb.apagar(real)
        self.assertEqual(projetos.descobrir(forcar=True), [])

    def test_projeto_extra_entra_e_oculto_marca(self):
        real = amb.BASE / "mundo" / "Desktop" / "SemSessoes"
        real.mkdir(parents=True)
        slug = projetos.adicionar_extra(str(real))
        lista = projetos.descobrir(forcar=True)
        self.assertIn(slug, [p["slug"] for p in lista])
        config.atualizar_config(lambda c: c["ocultos"].append(slug))
        lista = projetos.descobrir(forcar=True)
        self.assertTrue(next(p for p in lista if p["slug"] == slug)["oculto"])
        config.atualizar_config(lambda c: c["ocultos"].remove(slug))

    def test_codificacao_igual_a_do_claude_code(self):
        self.assertEqual(projetos.codificar(r"C:\Users\ana\Projetos\Loja"), amb.SLUG_EXEMPLO)

    def test_decodifica_pelo_disco_quando_nao_ha_cwd(self):
        real, nome = criar_projeto("Desktop/Meu_Projeto-x y")
        d = projetos.decodificar_pelo_disco(projetos.codificar(real))
        self.assertEqual(Path(d).resolve(), real.resolve())

    def test_eh_proibido(self):
        cfg = {"nunca_entrar": ["Financeiro", " "]}
        self.assertTrue(projetos.eh_proibido("C--Users-ana-Desktop-financeiro", cfg=cfg))
        self.assertTrue(projetos.eh_proibido("", "c:/x/FINANCEIRO", cfg=cfg))
        self.assertFalse(projetos.eh_proibido(amb.SLUG_EXEMPLO, cfg=cfg))
        self.assertFalse(projetos.eh_proibido("qualquer", cfg={}))


if __name__ == "__main__":
    unittest.main()
