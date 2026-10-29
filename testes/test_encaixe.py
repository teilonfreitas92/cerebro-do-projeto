"""Escrita dentro do projeto (encaixe, agentes, gancho do gitleaks) e instalação de ferramentas.

Tudo em projeto FALSO dentro da pasta temporária dos testes (git init real é ok). Nenhum instalador de verdade roda:
pip/winget/cargo/npm passam por instalador._rodar_processo, trocado aqui por um falso."""
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from testes import _ambiente as amb
from cerebro import config, encaixe, escrita_projeto, ferramentas, gancho, instalador, projetos, sugestoes
from cerebro.escrita_projeto import EscritaRecusada
import cerebro_cli
from testes.test_servidor import Base


def git(raiz, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(raiz), capture_output=True, check=True)


def arvore(raiz):
    """{caminho relativo: bytes} de tudo no projeto (menos o .git, salvo os ganchos)."""
    saida = {}
    for p in Path(raiz).rglob("*"):
        rel = p.relative_to(raiz).as_posix()
        if p.is_file() and (not rel.startswith(".git/") or rel.startswith(".git/hooks/")) and not rel.endswith(".sample"):
            saida[rel] = p.read_bytes()
    return saida


class Mundo(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.p = projetos.achar(self.slug)

    def tearDown(self):
        self.desmontar_mundo()

    def aplicar(self, acao, opcoes=None):
        pv = encaixe.previa(self.p, acao, opcoes)
        return encaixe.aplicar(self.p, acao, True, opcoes, pv["assinatura"])


# ======================================================================================================================
# Trava de caminho
# ======================================================================================================================
class TesteTravaDeCaminho(Mundo):
    def test_recusa_fugas_e_caminhos_estranhos(self):
        raiz = escrita_projeto.conferir_projeto(self.p)
        for rel in ("../fora.md", "a/../../fora.md", "/abs.md", "C:/abs.md", "C:abs.md", "", ".", "a/./b.md", "x:stream", "a\x00b",
                    ".git/config", ".git/hooks/post-commit", "sub/.git/hooks/pre-commit", ".GIT/config"):
            with self.assertRaises(EscritaRecusada, msg=rel):
                escrita_projeto.alvo_seguro(raiz, rel)
        self.assertEqual(escrita_projeto.alvo_seguro(raiz, ".git/hooks/pre-commit"), raiz / ".git" / "hooks" / "pre-commit")
        self.assertEqual(escrita_projeto.alvo_seguro(raiz, "docs\\a.md"), raiz / "docs" / "a.md")

    def _link_para_fora(self, link, alvo):
        try:
            os.symlink(alvo, link, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            try:
                import _winapi
                _winapi.CreateJunction(str(alvo), str(link))
                return True
            except (OSError, ImportError, AttributeError):
                pass
        return False

    def test_recusa_link_que_sai_do_projeto(self):
        fora = amb.BASE / "fora_do_projeto"
        fora.mkdir(exist_ok=True)
        if not self._link_para_fora(self.real / "atalho", fora):
            self.skipTest("este PC não deixa criar link nem junção")
        raiz = escrita_projeto.conferir_projeto(self.p)
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.alvo_seguro(raiz, "atalho/x.md")
        self.assertEqual(list(fora.iterdir()), [])

    def test_projeto_reservado_por_nome_e_recusado(self):
        reservado = amb.BASE / "mundo" / ("T_" + "FOREX")
        reservado.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto({"slug": projetos.codificar(reservado), "caminho": str(reservado), "nome": reservado.name})
        sub = reservado / "sub"
        sub.mkdir(exist_ok=True)
        with self.assertRaises(EscritaRecusada):                     # qualquer pasta dentro dele também
            escrita_projeto.conferir_projeto({"slug": "x", "caminho": str(sub), "nome": "sub"})
        self.assertEqual(list(sub.iterdir()), [])

    def test_oculto_nunca_escrever_worktree_e_pastas_proibidas(self):
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto({**self.p, "oculto": True})
        cfg = config.ler_config()
        cfg["nunca_escrever"] = ["desktop/falso"]
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto(self.p, cfg)
        cfg = config.ler_config()
        cfg["ocultos"] = [self.slug]
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto(self.p, cfg)
        wt = amb.BASE / "mundo" / "wt"
        wt.mkdir(parents=True, exist_ok=True)
        (wt / ".git").write_text("gitdir: ../outro/.git/worktrees/wt\n", encoding="utf-8")
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto({"slug": "wt", "caminho": str(wt), "nome": "wt"})
        for pasta in (config.CASA, config.CLAUDE, Path.home()):
            with self.assertRaises(EscritaRecusada, msg=str(pasta)):
                escrita_projeto.conferir_projeto({"slug": "x", "caminho": str(pasta), "nome": "x"})
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto({"slug": "x", "caminho": str(amb.BASE / "nao_existe"), "nome": "x"})

    def test_sem_confirmar_nada_muda(self):
        antes = arvore(self.real)
        pv = encaixe.previa(self.p, "instrucoes")
        for conf in (False, None, "true", 1):
            with self.assertRaises(EscritaRecusada):
                encaixe.aplicar(self.p, "instrucoes", conf, None, pv["assinatura"])
        with self.assertRaises(EscritaRecusada):
            encaixe.aplicar(self.p, "acao-que-nao-existe", True)
        self.assertEqual(arvore(self.real), antes)


# ======================================================================================================================
# Plano de encaixe: bloco marcado, criar, desfazer
# ======================================================================================================================
class TesteEncaixe(Mundo):
    def test_previa_nao_escreve_nada(self):
        (self.real / "app.py").write_text("x = 1\n", encoding="utf-8")
        (self.real / "requirements.txt").write_text("aiohttp\n", encoding="utf-8")
        antes = arvore(self.real)
        d = encaixe.previa_tudo(self.p)
        self.assertEqual(d["bloqueado"], "")
        self.assertTrue(d["acoes"]["instrucoes"]["aplicavel"])
        self.assertTrue(d["acoes"]["qualidade"]["aplicavel"])
        self.assertTrue(d["acoes"]["dependencias"]["aplicavel"])
        self.assertEqual(arvore(self.real), antes)

    def test_bloco_marcado_no_fim_do_claude_md_e_idempotente(self):
        original = "# Regras do projeto\r\nNão mexer no banco.\r\n"
        (self.real / "CLAUDE.md").write_bytes(original.encode("utf-8"))
        pv = encaixe.previa(self.p, "instrucoes")
        self.assertEqual([(a["rel"], a["tipo"]) for a in pv["arquivos"]], [("CLAUDE.md", "alterar")])
        self.assertIn("+" + encaixe.INICIO, pv["arquivos"][0]["diff"])
        r = encaixe.aplicar(self.p, "instrucoes", True, None, pv["assinatura"])
        self.assertFalse(r["nada_a_fazer"])
        novo = (self.real / "CLAUDE.md").read_bytes().decode("utf-8")
        self.assertTrue(novo.startswith(original))                     # o que existia fica igual, no começo
        self.assertEqual(novo.count(encaixe.INICIO), 1)
        self.assertNotIn("\n", novo.replace("\r\n", ""))               # manteve o fim de linha do arquivo
        r2 = self.aplicar("instrucoes")
        self.assertTrue(r2["nada_a_fazer"])
        self.assertEqual((self.real / "CLAUDE.md").read_bytes().decode("utf-8"), novo)
        copia = Path(r["copia"]) / "antes" / "CLAUDE.md"
        self.assertEqual(copia.read_bytes(), original.encode("utf-8"))
        self.assertTrue(escrita_projeto._dentro(copia, config.CASA / "copias" / "projetos" / self.slug))

    def test_agents_md_quando_nao_ha_claude_md(self):
        (self.real / "AGENTS.md").write_text("# agentes\n", encoding="utf-8")
        self.aplicar("instrucoes")
        self.assertIn(encaixe.INICIO, (self.real / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertFalse((self.real / "CLAUDE.md").exists())

    def test_desfazer_alterado_volta_a_copia(self):
        (self.real / "CLAUDE.md").write_text("original\n", encoding="utf-8")
        self.aplicar("instrucoes")
        r = encaixe.desfazer(self.p, True)                                              # ninguém mexeu depois: desfaz direto
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "original\n")
        guardado = Path(r["pasta_copia"]) / "antes-de-desfazer" / "CLAUDE.md"
        self.assertIn(encaixe.INICIO, guardado.read_text(encoding="utf-8"))
        with self.assertRaises(EscritaRecusada):
            encaixe.desfazer(self.p, True)                                                # não há mais o que desfazer
        with self.assertRaises(EscritaRecusada):
            encaixe.desfazer(self.p, False)

    def test_desfazer_recusa_se_o_dono_mexeu_depois_sem_aceite_da_diferenca(self):
        (self.real / "CLAUDE.md").write_text("original\n", encoding="utf-8")
        self.aplicar("instrucoes")
        (self.real / "CLAUDE.md").write_text("original\nmexido depois\n", encoding="utf-8")       # o dono mexeu depois
        with self.assertRaises(escrita_projeto.DesfazerComMudancas) as ctx:
            encaixe.desfazer(self.p, True)
        self.assertEqual([m["rel"] for m in ctx.exception.mexidos], ["CLAUDE.md"])
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "original\nmexido depois\n")   # nada mudou
        pv = encaixe.previa_desfazer(self.p)
        self.assertEqual([m["rel"] for m in pv["mexidos"]], ["CLAUDE.md"])
        self.assertIn("-mexido depois", pv["mexidos"][0]["diff"])                        # a diferença é mostrada
        with self.assertRaises(escrita_projeto.DesfazerComMudancas):
            encaixe.desfazer(self.p, True, aceitar_mexidos="assinatura-errada")
        (self.real / "CLAUDE.md").write_text("original\nmexido de novo\n", encoding="utf-8")      # mudou depois da prévia
        with self.assertRaises(escrita_projeto.DesfazerComMudancas):
            encaixe.desfazer(self.p, True, aceitar_mexidos=pv["assinatura_mexidos"])
        pv = encaixe.previa_desfazer(self.p)
        r = encaixe.desfazer(self.p, True, aceitar_mexidos=pv["assinatura_mexidos"])
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "original\n")
        guardado = Path(r["pasta_copia"]) / "antes-de-desfazer" / "CLAUDE.md"
        self.assertIn("mexido de novo", guardado.read_text(encoding="utf-8"))          # nada se perde

    def test_arquivo_criado_que_o_dono_editou_tambem_pede_aceite(self):
        self.aplicar("instrucoes")
        (self.real / "CLAUDE.md").write_text("o dono reescreveu tudo\n", encoding="utf-8")
        with self.assertRaises(escrita_projeto.DesfazerComMudancas):
            encaixe.desfazer(self.p, True)
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "o dono reescreveu tudo\n")
        pv = encaixe.previa_desfazer(self.p)
        self.assertIn("-o dono reescreveu tudo", pv["mexidos"][0]["diff"])
        d = encaixe.desfazer(self.p, True, aceitar_mexidos=pv["assinatura_mexidos"])
        self.assertFalse((self.real / "CLAUDE.md").exists())
        self.assertEqual((Path(d["pasta_copia"]) / "removidos" / "CLAUDE.md").read_text(encoding="utf-8"), "o dono reescreveu tudo\n")

    def test_arquivo_criado_e_movido_para_as_copias_ao_desfazer(self):
        r = self.aplicar("instrucoes")
        self.assertEqual(r["feito"][0]["tipo"], "criar")
        self.assertTrue((self.real / "CLAUDE.md").is_file())
        d = encaixe.desfazer(self.p, True)
        self.assertFalse((self.real / "CLAUDE.md").exists())
        movido = Path(d["pasta_copia"]) / "removidos" / "CLAUDE.md"
        self.assertIn(encaixe.INICIO, movido.read_text(encoding="utf-8"))
        hist = escrita_projeto.historico(self.slug)
        self.assertTrue(hist[0]["desfeita"])

    def test_desfazer_so_a_ultima_e_depois_a_anterior(self):
        (self.real / "app.py").write_text("x = 1\n", encoding="utf-8")
        self.aplicar("instrucoes")
        self.aplicar("qualidade")
        encaixe.desfazer(self.p, True)
        self.assertFalse((self.real / "ruff.toml").exists())
        self.assertTrue((self.real / "CLAUDE.md").exists())
        encaixe.desfazer(self.p, True)
        self.assertFalse((self.real / "CLAUDE.md").exists())

    def test_projeto_mudou_depois_da_previa_recusa(self):
        (self.real / "CLAUDE.md").write_text("a\n", encoding="utf-8")
        pv = encaixe.previa(self.p, "instrucoes")
        (self.real / "CLAUDE.md").write_text("b\n", encoding="utf-8")
        with self.assertRaises(EscritaRecusada):
            encaixe.aplicar(self.p, "instrucoes", True, None, pv["assinatura"])
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "b\n")

    def test_lint_e_dependabot_existentes_sao_respeitados(self):
        (self.real / "app.py").write_text("x = 1\n", encoding="utf-8")
        (self.real / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
        (self.real / ".github").mkdir()
        (self.real / ".github" / "dependabot.yml").write_text("version: 2\n", encoding="utf-8")
        for acao in ("qualidade", "dependencias"):
            self.assertTrue(self.aplicar(acao)["nada_a_fazer"])
        self.assertEqual((self.real / "ruff.toml").read_text(encoding="utf-8"), "line-length = 99\n")


# ======================================================================================================================
# Agentes por tipo: cópia para .claude/agents
# ======================================================================================================================
class TesteAgentesCopiar(Mundo):
    def test_copia_cria_e_nao_sobrescreve(self):
        r = self.aplicar("agentes")
        criados = sorted(f["rel"] for f in r["feito"] if f["tipo"] == "criar")
        self.assertEqual(criados, [".claude/agents/cerebro-codigo.md", ".claude/agents/cerebro-critico.md", ".claude/agents/cerebro-mecanico.md"])
        self.assertTrue(self.aplicar("agentes")["nada_a_fazer"])                        # iguais: pula
        meu = self.real / ".claude" / "agents" / "cerebro-codigo.md"
        meu.write_text("---\nname: cerebro-codigo\n---\nmeu agente\n", encoding="utf-8")
        pv = encaixe.previa(self.p, "agentes")
        item = next(a for a in pv["arquivos"] if a["rel"].endswith("cerebro-codigo.md"))
        self.assertEqual(item["tipo"], "pular")
        self.assertIn("meu agente", item["diff"])                                       # mostra a diferença
        self.assertTrue(self.aplicar("agentes")["nada_a_fazer"])
        self.assertEqual(meu.read_text(encoding="utf-8"), "---\nname: cerebro-codigo\n---\nmeu agente\n")
        r = self.aplicar("agentes", {"conflito": "cerebro_md"})
        self.assertEqual([f["rel"] for f in r["feito"] if f["tipo"] == "criar"], [".claude/agents/cerebro-codigo.cerebro.md"])
        self.assertEqual(meu.read_text(encoding="utf-8"), "---\nname: cerebro-codigo\n---\nmeu agente\n")
        with self.assertRaises(EscritaRecusada):
            encaixe.previa(self.p, "agentes", {"conflito": "sobrescrever"})

    def test_agentes_do_projeto_com_outros_nomes_ficam(self):
        (self.real / ".claude" / "agents").mkdir(parents=True)
        (self.real / ".claude" / "agents" / "revisor.md").write_text("x", encoding="utf-8")
        self.aplicar("agentes")
        self.assertEqual((self.real / ".claude" / "agents" / "revisor.md").read_text(encoding="utf-8"), "x")


# ======================================================================================================================
# Gancho pre-commit do gitleaks
# ======================================================================================================================
class TesteGancho(Mundo):
    def setUp(self):
        super().setUp()
        git(self.real, "init", "-q")
        self.gancho = self.real / ".git" / "hooks" / "pre-commit"

    def test_sem_gancho_cria_e_tirar_leva_para_as_copias(self):
        self.assertEqual(gancho.situacao(self.real)["modos"], ["novo"])
        self.aplicar("segredos")
        self.assertIn(gancho.MARCA, self.gancho.read_text(encoding="utf-8"))
        self.assertEqual(gancho.situacao(self.real)["modos"], ["tirar"])
        with self.assertRaises(ValueError):
            encaixe.previa(self.p, "segredos")                                           # já ligado
        r = self.aplicar("segredos-tirar")
        self.assertEqual([f["tipo"] for f in r["feito"]], ["retirar"])
        self.assertFalse(self.gancho.exists())
        self.assertTrue((Path(r["copia"]) / "retirados" / ".git" / "hooks" / "pre-commit").is_file())

    def test_gancho_existente_e_encadeado_e_preservado(self):
        antigo = "#!/bin/sh\necho gancho do projeto\nexit 0\n"
        self.gancho.write_text(antigo, encoding="utf-8")
        s = gancho.situacao(self.real)
        self.assertEqual((s["gancho"], s["modos"]), ("do projeto", ["encadear"]))
        r = self.aplicar("segredos")
        self.assertEqual((self.real / gancho.REL_ANTERIOR).read_text(encoding="utf-8"), antigo)        # o antigo fica ao lado
        novo = self.gancho.read_text(encoding="utf-8")
        self.assertIn(gancho.MARCA, novo)
        self.assertIn("pre-commit.cerebro-anterior", novo)                                           # e é chamado primeiro
        self.assertEqual((Path(r["copia"]) / "antes" / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8"), antigo)
        self.aplicar("segredos-tirar")                                                               # tirar devolve o antigo
        self.assertEqual(self.gancho.read_text(encoding="utf-8"), antigo)
        self.assertFalse((self.real / gancho.REL_ANTERIOR).exists())

    def test_desfazer_o_encadeamento_volta_ao_original(self):
        antigo = "#!/bin/sh\nexit 0\n"
        self.gancho.write_text(antigo, encoding="utf-8")
        self.aplicar("segredos")
        encaixe.desfazer(self.p, True)
        self.assertEqual(self.gancho.read_text(encoding="utf-8"), antigo)
        self.assertFalse((self.real / gancho.REL_ANTERIOR).exists())

    def test_gancho_encadeado_roda_o_antigo_e_respeita_a_falha(self):
        sh = shutil_which("sh")
        if not sh:
            self.skipTest("sem sh neste PC")
        marca = self.real / "rodou.txt"
        self.gancho.write_text(f"#!/bin/sh\necho x > '{marca.as_posix()}'\nexit 3\n", encoding="utf-8")
        os.chmod(self.gancho, 0o755)
        self.aplicar("segredos")
        r = subprocess.run([sh, str(self.gancho)], capture_output=True, cwd=str(self.real), timeout=60)
        self.assertTrue(marca.is_file())
        self.assertEqual(r.returncode, 3)                                              # o antigo falhou: o commit para, como antes

    def test_framework_pre_commit_recebe_bloco_marcado(self):
        cfg_yaml = "repos:\n-   repo: https://example.com/hooks\n    rev: v1\n    hooks:\n    -   id: trailing-whitespace\n"
        (self.real / ".pre-commit-config.yaml").write_text(cfg_yaml, encoding="utf-8")
        self.assertEqual(gancho.situacao(self.real)["modos"], ["config", "novo"])
        self.aplicar("segredos")
        novo = (self.real / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertTrue(novo.startswith(cfg_yaml))
        self.assertIn(gancho.INICIO_YAML, novo)
        self.assertFalse(self.gancho.exists())                                          # nenhum gancho criado no modo config
        self.aplicar("segredos-tirar")
        self.assertEqual((self.real / ".pre-commit-config.yaml").read_text(encoding="utf-8"), cfg_yaml)

    def test_yaml_com_chave_depois_de_repos_nao_e_mexido(self):
        (self.real / ".pre-commit-config.yaml").write_text("repos:\n- repo: local\n  hooks: []\nci:\n  skip: []\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            encaixe.previa(self.p, "segredos", {"modo": "config"})
        self.aplicar("segredos", {"modo": "novo"})                                      # o outro modo continua possível
        self.assertTrue(self.gancho.is_file())

    def test_yaml_grande_e_regravado_inteiro(self):
        # prova da revisão: 4000 repos (~330 KB) eram cortados em 200 KB e 1303 repos sumiam ao regravar
        y = "repos:\n" + "".join(f"- repo: https://x/{i}\n  rev: v1\n  hooks:\n  - id: h{i}   # comentário ç\n" for i in range(4000))
        cfg = self.real / ".pre-commit-config.yaml"
        cfg.write_bytes(y.encode("utf-8"))
        self.assertGreater(len(y.encode("utf-8")), 200_000)
        _, ops = gancho.planejar_ligar(self.real, "config")
        novo = ops[0]["dados"].decode("utf-8")
        self.assertTrue(novo.startswith(y))
        self.assertEqual(novo.count("- repo: https://x/"), 4000)

    def test_yaml_grande_demais_ou_fora_do_utf8_e_recusado_sem_mexer(self):
        cfg = self.real / ".pre-commit-config.yaml"
        base = "repos:\n- repo: https://example.com/hooks\n  rev: v1\n  hooks:\n  - id: x\n"
        enorme = (base + "# " + "a" * (gancho.LIMITE_YAML + 10) + "\n").encode("utf-8")
        latin1 = (base + "  # coment\xe1rio em latin-1\n").encode("latin-1")
        for dados in (enorme, latin1):
            cfg.write_bytes(dados)
            with self.assertRaises(ValueError):
                gancho.planejar_ligar(self.real, "config")
            with self.assertRaises(ValueError):
                encaixe.previa(self.p, "segredos", {"modo": "config"})
            self.assertEqual(cfg.read_bytes(), dados)

    def test_tirar_bloco_de_yaml_que_deixou_de_ser_utf8_e_recusado(self):
        cfg = self.real / ".pre-commit-config.yaml"
        cfg.write_text("repos:\n- repo: https://example.com/hooks\n  rev: v1\n  hooks:\n  - id: x\n", encoding="utf-8")
        self.aplicar("segredos")
        com_latin1 = cfg.read_bytes() + "# depois: a\xe7\xe3o\n".encode("latin-1")
        cfg.write_bytes(com_latin1)
        with self.assertRaises(ValueError):
            gancho.planejar_tirar(self.real)
        self.assertEqual(cfg.read_bytes(), com_latin1)

    def test_hooks_path_e_worktree_sao_recusados(self):
        git(self.real, "config", "core.hooksPath", ".githooks")
        self.assertIn("core.hooksPath", gancho.situacao(self.real)["motivo"])
        with self.assertRaises(ValueError):
            encaixe.previa(self.p, "segredos")
        git(self.real, "config", "--unset", "core.hooksPath")
        (self.real / "x.txt").write_text("x", encoding="utf-8")
        git(self.real, "add", ".")
        git(self.real, "commit", "-q", "-m", "x")
        wt = amb.BASE / "mundo" / "wt-gancho"
        git(self.real, "worktree", "add", "-q", str(wt))
        self.assertTrue(gancho.situacao(wt)["worktree"])
        with self.assertRaises(EscritaRecusada):
            escrita_projeto.conferir_projeto({"slug": "wt", "caminho": str(wt), "nome": "wt"})


def shutil_which(nome):
    import shutil
    achado = shutil.which(nome)
    if achado or os.name != "nt":
        return achado
    for c in (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "sh.exe",):
        if c.is_file():
            return str(c)
    return None


# ======================================================================================================================
# Instalar ferramentas (instalador falso)
# ======================================================================================================================
class Falso:
    def __init__(self, codigo=0, texto="Successfully installed\nsenha=abc12345xyz\n"):
        self.chamadas, self.codigo, self.texto = [], codigo, texto

    def __call__(self, argv, limite):
        self.chamadas.append((list(argv), limite))
        return self.codigo, self.texto, "ok" if self.codigo == 0 else "falha"


class TesteInstalador(Mundo):
    def setUp(self):
        super().setUp()
        self.falso = Falso()
        self.instalada = {"v": False}
        for nome, valor in (("_rodar_processo", self.falso), ("_reconferir", lambda fid, c: {"instalada": self.instalada["v"], "versao": "9.9.9"}),
                            ("_achar", lambda via: {"pip": sys.executable, "cargo": "C:/falso/cargo.exe", "winget": "C:/falso/winget.exe", "npm": None}[via])):
            original = getattr(instalador, nome)
            setattr(instalador, nome, valor)
            self.addCleanup(setattr, instalador, nome, original)

    def test_receitas_fechadas(self):
        for fid in ("gitleaks", "pip-audit", "cargo-deny", "semgrep", "coverage"):
            self.assertIn(fid, instalador.RECEITAS)
        self.assertTrue(set(instalador.RECEITAS) <= {f["id"] for f in ferramentas.CATALOGO})
        for fid in ("nao-existe", "osv-scanner", "eslint", "rm -rf", ""):
            with self.assertRaises(ValueError):
                instalador.previa(fid)
            with self.assertRaises(ValueError):
                instalador.instalar(self.slug, str(self.real), fid, True)
        self.assertEqual(self.falso.chamadas, [])

    def test_previa_mostra_comando_origem_e_nao_roda(self):
        pv = instalador.previa("pip-audit")
        self.assertTrue(pv["disponivel"])
        self.assertEqual(pv["argv"][:4], [sys.executable, "-m", "pip", "install"])
        self.assertEqual(pv["argv"][-1], "pip-audit")
        self.assertIn("PyPI", pv["de_onde"])
        self.assertTrue(pv["tamanho"] and pv["tempo"])
        self.assertEqual(self.falso.chamadas, [])
        self.assertFalse(instalador.previa("lighthouse")["disponivel"])                     # sem npm: sem botão
        self.assertFalse(instalador.disponiveis()["lighthouse"]["disponivel"])

    def test_sem_confirmar_nao_instala(self):
        for conf in (False, None, "sim"):
            with self.assertRaises(ValueError):
                instalador.instalar(self.slug, str(self.real), "coverage", conf)
        self.assertEqual(self.falso.chamadas, [])

    def test_pip_no_python_do_cerebro_com_user_e_historico_mascarado(self):
        self.instalada["v"] = True
        reg = instalador.instalar(self.slug, str(self.real), "coverage", True, esperar=True)
        argv, limite = self.falso.chamadas[0]
        self.assertEqual(argv[:4], [sys.executable, "-m", "pip", "install"])
        if sys.prefix == sys.base_prefix:
            self.assertIn("--user", argv)
        self.assertEqual(argv[-1], "coverage")
        self.assertEqual(reg["resultado"], "ok")
        self.assertIn("9.9.9", reg["resumo"])
        hist = ferramentas.estado_execucoes(self.slug)
        self.assertIsNone(hist["rodando"])
        self.assertEqual(hist["historico"][0]["comando"], "instalar-coverage")
        texto = ferramentas.saida_da_execucao(self.slug, reg["id"])
        self.assertNotIn("abc12345xyz", texto)                                             # saída mascarada
        self.assertIn("Conferência depois: instalada", texto)

    def test_winget_exige_termos_e_usa_escopo_do_usuario(self):
        with self.assertRaises(ValueError):
            instalador.instalar(self.slug, str(self.real), "gitleaks", True)
        self.assertEqual(self.falso.chamadas, [])
        instalador.instalar(self.slug, str(self.real), "gitleaks", True, aceitar_termos=True, esperar=True)
        argv = self.falso.chamadas[0][0]
        self.assertEqual(argv[:5], ["C:/falso/winget.exe", "install", "--id", "Gitleaks.Gitleaks", "--exact"])
        self.assertIn("--scope", argv)
        self.assertEqual(argv[argv.index("--scope") + 1], "user")
        self.assertIn("--accept-source-agreements", argv)

    def test_cargo_e_falha_registrada(self):
        self.falso.codigo = 101
        reg = instalador.instalar(self.slug, str(self.real), "cargo-deny", True, esperar=True)
        self.assertEqual(self.falso.chamadas[0][0], ["C:/falso/cargo.exe", "install", "--locked", "cargo-deny"])
        self.assertEqual(reg["resultado"], "falha")
        self.assertIn("101", reg["resumo"])

    def test_uma_instalacao_por_vez(self):
        instalador._instalando["id"] = "outra"
        self.addCleanup(instalador._instalando.__setitem__, "id", None)
        with self.assertRaises(ValueError):
            instalador.instalar(self.slug, str(self.real), "coverage", True)

    def test_sugestao_de_coverage_entra_so_por_aprovacao(self):
        (self.real / "tests").mkdir()
        (self.real / "tests" / "test_a.py").write_text("", encoding="utf-8")
        ids = {s["id"]: s for s in sugestoes.detectar(self.real)}
        self.assertEqual(ids["coverage-rodar"]["argv"], ["{python}", "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"])
        self.assertEqual(ids["coverage-relatorio"]["argv"], ["{python}", "-m", "coverage", "report"])
        self.assertEqual(ferramentas.comandos_do_projeto(config.ler_config(), self.slug), [])
        sugestoes.aprovar(self.slug, self.real, "coverage-rodar")
        self.assertEqual([c["id"] for c in ferramentas.comandos_do_projeto(config.ler_config(), self.slug)], ["coverage-rodar"])


# ======================================================================================================================
# CLI
# ======================================================================================================================
class TesteCli(Mundo):
    def rodar(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            codigo = cerebro_cli.main(list(args))
        return codigo, out.getvalue(), err.getvalue()

    def test_encaixe_previa_aplicar_e_desfazer(self):
        antes = arvore(self.real)
        codigo, out, _ = self.rodar("encaixe", "Falso", "--previa")
        self.assertEqual(codigo, 0)
        self.assertIn("Nada foi aplicado", out)
        codigo, out, _ = self.rodar("encaixe", "Falso", "--aplicar", "instrucoes")
        self.assertIn("Nada foi aplicado", out)
        self.assertEqual(arvore(self.real), antes)
        codigo, out, _ = self.rodar("encaixe", "Falso", "--aplicar", "instrucoes", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertTrue((self.real / "CLAUDE.md").is_file())
        codigo, out, _ = self.rodar("encaixe", "Falso", "--desfazer")
        self.assertTrue((self.real / "CLAUDE.md").is_file())
        codigo, out, _ = self.rodar("encaixe", "Falso", "--desfazer", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertFalse((self.real / "CLAUDE.md").exists())

    def test_cli_desfazer_com_mudanca_do_dono_mostra_a_diferenca_e_pede_aceite(self):
        self.rodar("encaixe", "Falso", "--aplicar", "instrucoes", "--confirmar")
        (self.real / "CLAUDE.md").write_text("texto do dono\n", encoding="utf-8")
        codigo, out, _ = self.rodar("encaixe", "Falso", "--desfazer", "--confirmar")
        self.assertNotEqual(codigo, 0)
        self.assertIn("-texto do dono", out)                                             # mostrou a diferença
        self.assertEqual((self.real / "CLAUDE.md").read_text(encoding="utf-8"), "texto do dono\n")
        codigo, out, _ = self.rodar("encaixe", "Falso", "--desfazer", "--confirmar", "--mesmo-com-mudancas")
        self.assertEqual(codigo, 0)
        self.assertFalse((self.real / "CLAUDE.md").exists())

    def test_agentes_copiar(self):
        codigo, out, _ = self.rodar("agentes-copiar", "Falso")
        self.assertFalse((self.real / ".claude").exists())
        codigo, out, _ = self.rodar("agentes-copiar", "Falso", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertTrue((self.real / ".claude" / "agents" / "cerebro-critico.md").is_file())

    def test_instalar_ferramenta(self):
        falso = Falso()
        for nome, valor in (("_rodar_processo", falso), ("_reconferir", lambda fid, c: {"instalada": True, "versao": "1.0"}),
                            ("_achar", lambda via: sys.executable if via == "pip" else None)):
            original = getattr(instalador, nome)
            setattr(instalador, nome, valor)
            self.addCleanup(setattr, instalador, nome, original)
        codigo, out, _ = self.rodar("instalar-ferramenta", "Falso", "coverage")
        self.assertIn("Nada foi instalado", out)
        self.assertEqual(falso.chamadas, [])
        codigo, out, _ = self.rodar("instalar-ferramenta", "Falso", "coverage", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(len(falso.chamadas), 1)
        codigo, _, err = self.rodar("instalar-ferramenta", "Falso", "nao-existe", "--confirmar")
        self.assertEqual(codigo, 2)
        self.assertIn("lista fechada", err)


# ======================================================================================================================
# Rotas (com cookie, Origin e JSON, como as outras)
# ======================================================================================================================
class TesteRotasEncaixe(Base):
    async def test_aplicar_exige_confirmar_e_desfazer(self):
        amb.apagar(config.CASA / "projetos" / self.slug / "aplicacoes.json")          # histórico limpo: o mesmo slug é usado por outros testes
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/encaixe")).json()
        self.assertTrue(d["acoes"]["instrucoes"]["aplicavel"])
        pv = await (await self.http.get(f"{self.base}/api/p/{self.slug}/encaixe/previa?acao=instrucoes")).json()
        r = await self.post(f"/api/p/{self.slug}/encaixe/aplicar", {"acao": "instrucoes", "assinatura": pv["assinatura"]})
        self.assertEqual(r.status, 409)
        r = await self.post(f"/api/p/{self.slug}/encaixe/aplicar", {"acao": "instrucoes", "assinatura": pv["assinatura"], "confirmar": True}, origem=False)
        self.assertEqual(r.status, 403)
        self.assertNotIn("cerebro:inicio", (self.real / "AGENTS.md").read_text(encoding="utf-8"))
        r = await self.post(f"/api/p/{self.slug}/encaixe/aplicar", {"acao": "instrucoes", "assinatura": pv["assinatura"], "confirmar": True})
        self.assertEqual(r.status, 200)
        self.assertIn("cerebro:inicio", (self.real / "AGENTS.md").read_text(encoding="utf-8"))
        r = await self.post(f"/api/p/{self.slug}/encaixe/desfazer", {})
        self.assertEqual(r.status, 409)
        agora = (self.real / "AGENTS.md").read_text(encoding="utf-8")
        (self.real / "AGENTS.md").write_text(agora + "linha que o dono escreveu depois\n", encoding="utf-8")
        r = await self.post(f"/api/p/{self.slug}/encaixe/desfazer", {"confirmar": True})
        self.assertEqual(r.status, 409)                                              # o dono mexeu: precisa ver a diferença
        corpo = await r.json()
        self.assertEqual([m["rel"] for m in corpo["mexidos"]], ["AGENTS.md"])
        self.assertIn("linha que o dono escreveu depois", (self.real / "AGENTS.md").read_text(encoding="utf-8"))
        pv = await (await self.http.get(f"{self.base}/api/p/{self.slug}/encaixe/desfazer")).json()
        self.assertIn("-linha que o dono escreveu depois", pv["mexidos"][0]["diff"])
        r = await self.post(f"/api/p/{self.slug}/encaixe/desfazer", {"confirmar": True, "aceitar_mexidos": pv["assinatura_mexidos"]})
        self.assertEqual(r.status, 200)
        self.assertEqual((self.real / "AGENTS.md").read_text(encoding="utf-8"), "# regras do projeto\n")

    async def test_instalar_pela_rota_com_instalador_falso(self):
        falso = Falso()
        for nome, valor in (("_rodar_processo", falso), ("_reconferir", lambda fid, c: {"instalada": True, "versao": "1.0"}),
                            ("_achar", lambda via: sys.executable if via == "pip" else None)):
            original = getattr(instalador, nome)
            setattr(instalador, nome, valor)
            self.addCleanup(setattr, instalador, nome, original)
        await self.entrar()
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas")).json()
        self.assertIn("coverage", d["instalacao"])
        pv = await (await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas/instalar?id=coverage")).json()
        self.assertIn("pip", pv["comando"])
        r = await self.http.get(f"{self.base}/api/p/{self.slug}/ferramentas/instalar?id=nao-existe")
        self.assertEqual(r.status, 404)
        r = await self.post(f"/api/p/{self.slug}/ferramentas/instalar", {"id": "coverage"})
        self.assertEqual(r.status, 409)
        self.assertEqual(falso.chamadas, [])
        r = await self.post(f"/api/p/{self.slug}/ferramentas/instalar", {"id": "coverage", "confirmar": True})
        self.assertEqual(r.status, 200)
        import asyncio
        for _ in range(100):
            if ferramentas.estado_execucoes(self.slug)["rodando"] is None:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(len(falso.chamadas), 1)

    async def test_rotas_exigem_cookie(self):
        for caminho in (f"/api/p/{self.slug}/encaixe", f"/api/p/{self.slug}/ferramentas/instalar?id=coverage"):
            r = await self.http.get(self.base + caminho)
            self.assertEqual(r.status, 401)


if __name__ == "__main__":
    unittest.main()
