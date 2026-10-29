"""Revisão da 1.3, itens 6 e 16: programas externos só por caminho absoluto do sistema (nunca um executável plantado na pasta
atual) e trava de teste/CI (CEREBRO_TESTE_HOME, CEREBRO_SEM_AGENDADOR, CEREBRO_SEM_EFEITOS) no instalador de ferramentas, na
statusLine encadeada e nos avisos do Windows. Nenhum programa de verdade roda: subprocess é sempre trocado por um falso."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import avisos, instalador
import cerebro_statusline

NO_WINDOWS = unittest.skipUnless(os.name == "nt", "busca de executável do Windows")
SEM_TRAVA = {"CEREBRO_TESTE_HOME": "", "CEREBRO_SEM_AGENDADOR": "", "CEREBRO_SEM_EFEITOS": ""}
TRAVAS = ({"CEREBRO_TESTE_HOME": "x"}, {"CEREBRO_TESTE_HOME": "", "CEREBRO_SEM_AGENDADOR": "1"},
          {"CEREBRO_TESTE_HOME": "", "CEREBRO_SEM_EFEITOS": "1"})


def _proibido(*a, **k):
    raise AssertionError("programa de verdade chamado")


class PastaFalsa(unittest.TestCase):
    """Uma pasta "repositório baixado" com executáveis plantados (vira a pasta atual) e uma pasta "do sistema" com os de verdade."""

    def setUp(self):
        self.base = amb.BASE / f"travas_{self.id().rsplit('.', 1)[-1]}"
        amb.apagar(self.base)
        self.repo = self.base / "repo_baixado"
        self.sistema = self.base / "sistema"
        for p in (self.repo, self.sistema):
            p.mkdir(parents=True)
        self.addCleanup(amb.apagar, self.base)
        antes = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, antes)

    def plantar(self, pasta, *nomes):
        for n in nomes:
            alvo = pasta / n
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text("@echo plantado\n", encoding="utf-8")
        return pasta


# ---------------------------------------------------------------------------------------------------------------
# statusLine encadeada
# ---------------------------------------------------------------------------------------------------------------
@NO_WINDOWS
class TesteShellDaStatusline(PastaFalsa):
    def ambiente(self, **extra):
        env = {"PATH": f".{os.pathsep}{self.sistema / 'vazio'}", "PATHEXT": ".COM;.EXE;.BAT;.CMD", "CLAUDE_CODE_GIT_BASH_PATH": "",
               "ProgramFiles": str(self.sistema / "pf"), "ProgramW6432": "", "ProgramFiles(x86)": "", "LOCALAPPDATA": "",
               "SystemRoot": str(self.sistema / "win"), "windir": ""}
        env.update(extra)
        return mock.patch.dict(os.environ, env)

    def test_bash_plantado_na_pasta_da_sessao_nunca_e_usado(self):
        self.plantar(self.repo, "bash.bat", "bash.exe", "bash.cmd")
        self.plantar(self.sistema, "pf/Git/bin/bash.exe")
        with self.ambiente():
            argv = cerebro_statusline._argumentos_shell("echo oi")
        self.assertEqual(Path(argv[0]), self.sistema / "pf" / "Git" / "bin" / "bash.exe")
        self.assertEqual(argv[1:], ["-c", "echo oi"])

    def test_sem_git_bash_usa_o_powershell_do_sistema_por_caminho_absoluto(self):
        self.plantar(self.repo, "bash.bat", "powershell.exe")
        self.plantar(self.sistema, "win/System32/WindowsPowerShell/v1.0/powershell.exe")
        with self.ambiente():
            argv = cerebro_statusline._argumentos_shell("echo oi")
        self.assertTrue(os.path.isabs(argv[0]))
        self.assertEqual(Path(argv[0]), self.sistema / "win" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")

    def test_caminhos_relativos_sao_recusados(self):
        self.plantar(self.repo, "bash.exe", "Git/bin/bash.exe")
        with self.ambiente(CLAUDE_CODE_GIT_BASH_PATH="bash.exe", ProgramFiles=".", SystemRoot="."):
            self.assertIsNone(cerebro_statusline._argumentos_shell("echo oi"))
            self.assertEqual(cerebro_statusline.rodar_anterior("echo oi", b"{}", _proibido), "")

    def test_bash_no_path_so_em_pasta_absoluta_fora_da_pasta_atual(self):
        self.plantar(self.repo, "bash.exe")
        self.plantar(self.sistema, "bin/bash.exe")
        with self.ambiente(PATH=os.pathsep.join([".", str(self.repo), "relativa", str(self.sistema / "bin")])):
            argv = cerebro_statusline._argumentos_shell("x")
        self.assertEqual(Path(argv[0]), self.sistema / "bin" / "bash.exe")


class TesteTravaDaStatusline(unittest.TestCase):
    def test_comando_antigo_nunca_roda_de_verdade_em_teste_ou_ci(self):
        vazou = [sys.executable, "-c", "print('VAZOU')"]                # inofensivo, se a trava falhar
        for trava in TRAVAS:
            with self.subTest(trava=trava), mock.patch.dict(os.environ, trava), \
                    mock.patch.object(cerebro_statusline, "_argumentos_shell", lambda cmd: vazou), \
                    mock.patch.object(subprocess, "run", _proibido):
                self.assertEqual(cerebro_statusline.rodar_anterior("minha-barra", b"{}"), "")

    def test_executar_falso_continua_funcionando(self):
        r = subprocess.CompletedProcess([], 0, stdout=b"MINHA\n")
        self.assertEqual(cerebro_statusline.rodar_anterior("minha-barra", b"{}", lambda *a, **k: r), "MINHA")


# ---------------------------------------------------------------------------------------------------------------
# Avisos do Windows
# ---------------------------------------------------------------------------------------------------------------
class TesteAvisosPowershell(PastaFalsa):
    def test_powershell_plantado_na_pasta_atual_nunca_e_usado(self):
        self.plantar(self.repo, "powershell.exe")
        with mock.patch.dict(os.environ, {**SEM_TRAVA, "SystemRoot": str(self.sistema / "win"), "windir": ""}), \
                mock.patch.object(subprocess, "run", _proibido):
            self.assertIsNone(avisos.caminho_powershell())
            self.assertFalse(avisos._executar_powershell("a", "b"))
        with mock.patch.dict(os.environ, {**SEM_TRAVA, "SystemRoot": ".", "windir": ""}):
            self.assertIsNone(avisos.caminho_powershell())                      # raiz relativa: recusada

    def test_usa_o_caminho_absoluto_do_sistema(self):
        exe = self.sistema / "win" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        self.plantar(self.sistema, "win/System32/WindowsPowerShell/v1.0/powershell.exe")
        visto = {}

        def falso(args, **k):
            visto["args"] = args
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.dict(os.environ, {**SEM_TRAVA, "SystemRoot": str(self.sistema / "win")}), mock.patch.object(subprocess, "run", falso):
            self.assertTrue(avisos._executar_powershell("a", "b"))
        self.assertEqual(Path(visto["args"][0]), exe)

    def test_trava_de_ci_tambem_vale(self):
        for trava in TRAVAS:
            with self.subTest(trava=trava), mock.patch.dict(os.environ, trava), mock.patch.object(subprocess, "run", _proibido):
                self.assertFalse(avisos._executar_powershell("a", "b"))


# ---------------------------------------------------------------------------------------------------------------
# Instalador de ferramentas
# ---------------------------------------------------------------------------------------------------------------
class TesteInstaladorTravas(PastaFalsa):
    def test_rodar_processo_nunca_roda_em_teste_ou_ci(self):
        for trava in TRAVAS:
            with self.subTest(trava=trava), mock.patch.dict(os.environ, trava), mock.patch.object(subprocess, "Popen", _proibido):
                with self.assertRaises(ValueError):
                    instalador._rodar_processo([sys.executable, "-m", "pip", "--version"], 10)

    def test_programa_sem_caminho_absoluto_e_recusado(self):
        with mock.patch.dict(os.environ, SEM_TRAVA), mock.patch.object(subprocess, "Popen", _proibido):
            for argv in (["npm", "install", "-g", "x"], ["./npm.cmd", "install"], []):
                with self.assertRaises(ValueError):
                    instalador._rodar_processo(argv, 10)

    @NO_WINDOWS
    def test_instalador_plantado_na_pasta_atual_nunca_e_achado(self):
        self.plantar(self.repo, "npm.cmd", "winget.exe", "cargo.exe")
        self.plantar(self.sistema, "node/npm.cmd")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", "relativa", str(self.repo), str(self.sistema / "node")]),
                                          "PATHEXT": ".COM;.EXE;.BAT;.CMD"}), \
                mock.patch.object(Path, "home", classmethod(lambda cls: self.sistema / "casa")):
            self.assertEqual(Path(instalador._achar("npm")), self.sistema / "node" / "npm.cmd")
            self.assertIsNone(instalador._achar("winget"))
            self.assertIsNone(instalador._achar("cargo"))
            self.assertFalse(instalador.disponiveis()["gitleaks"]["disponivel"])

    @NO_WINDOWS
    def test_cargo_na_pasta_conhecida(self):
        self.plantar(self.sistema, "casa/.cargo/bin/cargo.exe")
        with mock.patch.dict(os.environ, {"PATH": "."}), mock.patch.object(Path, "home", classmethod(lambda cls: self.sistema / "casa")):
            self.assertEqual(Path(instalador._achar("cargo")), self.sistema / "casa" / ".cargo" / "bin" / "cargo.exe")


if __name__ == "__main__":
    unittest.main()
