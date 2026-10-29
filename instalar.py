#!/usr/bin/env python
"""Instalador do Cérebro do Projeto: um passo só, com o Python do sistema.

    python instalar.py            # instala perguntando o que for opcional
    python instalar.py --sim      # aceita as perguntas com o padrão "sim" (inclui instalar o Graphify)
    python instalar.py --nao      # responde "não" a todas as perguntas opcionais (só o essencial)

O que ele faz (e explica cada passo na tela):
  1. confere o Python (3.11 ou mais novo);
  2. cria o ambiente .venv dentro da pasta do Cérebro e instala as dependências (requirements.txt, versões fixas);
  3. oferece instalar o Graphify (opcional; o desenhista do mapa do código);
  4. cria a pasta de dados ~/.cerebro;
  5. pergunta se cria o atalho "Cérebro do Projeto" na área de trabalho (Windows; no macOS/Linux mostra como fazer);
  6. abre o painel.
Pode rodar de novo quando quiser: cada passo confere o que já existe e não repete nem estraga nada.
Só mexe na pasta do Cérebro, em ~/.cerebro e (se você deixar) no atalho da área de trabalho. Nunca mexe em ~/.claude nem nos seus projetos.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from cerebro import __version__, config  # noqa: E402  (só biblioteca padrão: roda antes de instalar as dependências)

PYTHON_MINIMO = (3, 11)
NOME_ATALHO = "Cérebro do Projeto.lnk"
ARQ_REGISTRO = ".instalacao.json"            # o que o instalador criou (o desinstalar.py lê); fica fora do git


def python_do_venv(pasta_venv):
    return Path(pasta_venv) / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def pythonw_do_venv(pasta_venv):
    p = Path(pasta_venv) / "Scripts" / "pythonw.exe"
    return p if p.is_file() else python_do_venv(pasta_venv)


def pasta_da_area_de_trabalho(executar=None):
    """Área de trabalho do usuário (no Windows pode estar no OneDrive: pergunta ao próprio Windows)."""
    if os.name == "nt":
        try:
            r = (executar or subprocess.run)(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                                             capture_output=True, text=True, timeout=20, creationflags=0x08000000)
            p = (r.stdout or "").strip()
            if p and Path(p).is_dir():
                return Path(p)
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Desktop"


class Instalador:
    def __init__(self, raiz=RAIZ, entrada=input, saida=print, executar=None, sim=False, nao=False):
        self.raiz = Path(raiz)
        self.entrada, self.saida, self.sim, self.nao = entrada, saida, sim, nao
        self.executar = executar or self._executar_de_verdade
        self.registro = {}

    # ---------- utilidades ----------
    def _executar_de_verdade(self, argv, **kw):
        return subprocess.run(argv, **kw)

    def dizer(self, texto=""):
        self.saida(texto)

    def passo(self, n, total, titulo, explicacao):
        self.dizer(f"\n[{n}/{total}] {titulo}")
        self.dizer(f"      {explicacao}")

    def perguntar(self, texto, padrao_sim=True):
        if self.sim:
            self.dizer(f"      {texto} -> sim (--sim)")
            return True
        if self.nao:
            self.dizer(f"      {texto} -> não (--nao)")
            return False
        marca = "[S/n]" if padrao_sim else "[s/N]"
        try:
            r = self.entrada(f"      {texto} {marca} ").strip().lower()
        except EOFError:
            r = ""
        return padrao_sim if not r else r[0] in ("s", "y")

    def rodar(self, argv, **kw):
        r = self.executar(argv, **kw)
        return getattr(r, "returncode", 0) == 0

    # ---------- passos ----------
    def conferir_python(self):
        if sys.version_info < PYTHON_MINIMO:
            self.dizer(f"      O Python é {sys.version.split()[0]}, mas o Cérebro precisa do {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} ou mais novo.")
            self.dizer("      Baixe em https://www.python.org/downloads/ e rode este instalador de novo.")
            return False
        self.dizer(f"      Python {sys.version.split()[0]}: ok.")
        return True

    def criar_venv(self, com_pip=True):
        pasta = self.raiz / ".venv"
        if python_do_venv(pasta).is_file():
            self.dizer("      O ambiente .venv já existe: vou só conferir as dependências.")
        else:
            self.dizer("      Criando o ambiente .venv (uma cópia isolada do Python só para o Cérebro)…")
            venv.create(str(pasta), with_pip=com_pip, clear=False)
        self.registro["venv"] = ".venv"
        return pasta

    def instalar_dependencias(self, pasta_venv, usar_venv=True):
        req = self.raiz / "requirements.txt"
        if usar_venv:
            argv = [str(python_do_venv(pasta_venv)), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)]
        else:
            argv = [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", "-r", str(req)]
        self.dizer("      Instalando as dependências (requirements.txt, versões fixas)…")
        ok = self.rodar(argv, cwd=str(self.raiz))
        self.dizer("      Dependências prontas." if ok else "      Não consegui instalar as dependências. Veja a mensagem acima e tente de novo.")
        return ok

    def oferecer_graphify(self):
        self.dizer("      O Graphify desenha o mapa do código (aba Mapa). É opcional: sem ele o resto funciona.")
        if shutil.which("graphify"):
            self.dizer("      O Graphify já está instalado: nada a fazer.")
            return True
        if not self.perguntar("Instalar o Graphify agora?", padrao_sim=False):
            self.dizer("      Ok, sem Graphify. Depois você instala com:  uv tool install graphifyy   (ou: pip install graphifyy)")
            return False
        if shutil.which("uv"):
            self.dizer("      Rodando:  uv tool install graphifyy")
            return self.rodar(["uv", "tool", "install", "graphifyy"])
        self.dizer("      Rodando:  pip install --user graphifyy")
        return self.rodar([sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", "graphifyy"])

    def criar_casa(self):
        config.garantir_casa()
        self.dizer(f"      Pasta de dados: {config.CASA}  (config, mapas, decisões; nada dentro dos seus projetos).")
        return config.CASA

    def oferecer_ganchos(self):
        """Ganchos do Claude Code (recomendado). Mexe no settings.json SÓ com o sim da pessoa NA HORA, depois de mostrar a
        diferença: nem --sim responde por ela. Cópia de segurança antes, mescla sem apagar, desliga com um clique."""
        from cerebro import ganchos_claude
        self.dizer("      Os ganchos fazem o Claude Code avisar o Cérebro na hora: agentes ao vivo, tarefas para a gestora, capítulos")
        self.dizer("      da conversa gestora e a limpeza dela na mesma sessão quando o contexto enche.")
        depois = "Depois: python cerebro_cli.py hooks --previa  e  hooks --instalar --confirmar  (ou Configurações no painel)."
        if self.sim or self.nao:
            self.dizer("      Pulado: mexer no settings.json do Claude Code só com o seu sim na hora. " + depois)
            return False
        try:
            if ganchos_claude.estado().get("eventos"):
                self.dizer("      Os ganchos do Cérebro já estão ligados.")
                return True
            p = ganchos_claude.previa(True, "comando", None)
        except Exception as e:
            self.dizer(f"      Não consegui ler o settings.json ({type(e).__name__}: {e}). {depois}")
            return False
        self.dizer(f"      O que muda em {ganchos_claude.caminho_settings()} (cópia de segurança antes; nada do que existe é apagado;")
        self.dizer("      para desligar: Configurações › Agentes ao vivo instantâneo › Desligar, ou hooks --remover --confirmar):")
        for linha in (p.get("diferenca") or "").splitlines()[:80]:
            self.dizer("        " + linha)
        try:
            r = self.entrada("      Ligar os ganchos agora (recomendado)? [s/n] ").strip().lower()
        except EOFError:
            r = ""
        if not r or r[0] not in ("s", "y"):
            self.dizer("      Ok, ganchos desligados. " + depois)
            return False
        try:
            res = ganchos_claude.instalar(True, True, "comando", None)
        except Exception as e:
            self.dizer(f"      Não liguei os ganchos ({type(e).__name__}: {e}). {depois}")
            return False
        self.dizer("      Ganchos ligados." + (f" Cópia de segurança: {res['copia']}" if res.get("copia") else ""))
        return True

    def criar_atalho(self, pasta_venv, area=None):
        """Atalho 'Cérebro do Projeto' na área de trabalho. Só Windows (.lnk); no macOS/Linux só mostra a instrução."""
        if os.name != "nt":
            self.dizer("      Neste sistema o atalho não é criado automaticamente. Para abrir o Cérebro:")
            self.dizer(f"        {self.raiz / 'abrir_cerebro.sh'}")
            self.dizer("      (no macOS você pode arrastar esse arquivo para o Dock; no Linux, criar um lançador .desktop apontando para ele).")
            return None
        area = Path(area) if area else pasta_da_area_de_trabalho(self.executar if self.executar != self._executar_de_verdade else None)
        lnk = area / NOME_ATALHO
        env = {**os.environ, "CEREBRO_LNK": str(lnk), "CEREBRO_ALVO": str(pythonw_do_venv(pasta_venv)),
               "CEREBRO_ARGS": f'"{self.raiz / "abrir_cerebro.py"}"', "CEREBRO_PASTA": str(self.raiz)}
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CEREBRO_LNK);$s.TargetPath=$env:CEREBRO_ALVO;"
              "$s.Arguments=$env:CEREBRO_ARGS;$s.WorkingDirectory=$env:CEREBRO_PASTA;$s.Description='Cérebro do Projeto';$s.Save()")
        existia = lnk.exists()
        ok = self.rodar(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, timeout=30, creationflags=0x08000000)
        if ok:
            self.registro["atalho"] = str(lnk)
            self.dizer(f"      Atalho {'atualizado' if existia else 'criado'}: {lnk}")
            return lnk
        self.dizer("      Não consegui criar o atalho (sem problema: abra com abrir_cerebro.bat).")
        return None

    def abrir_painel(self, pasta_venv):
        py = python_do_venv(pasta_venv) if python_do_venv(pasta_venv).is_file() else Path(sys.executable)
        self.dizer("      Abrindo o painel no navegador…")
        return self.rodar([str(py), str(self.raiz / "abrir_cerebro.py")], cwd=str(self.raiz))

    def gravar_registro(self):
        try:
            (self.raiz / ARQ_REGISTRO).write_text(json.dumps({"versao": __version__, **self.registro}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


def main(argv=None, entrada=input, saida=print, executar=None, raiz=RAIZ, area=None, com_pip=True):
    ap = argparse.ArgumentParser(description="Instala o Cérebro do Projeto")
    ap.add_argument("--sim", action="store_true", help="responde sim às perguntas (inclui o Graphify)")
    ap.add_argument("--nao", action="store_true", help="responde não às perguntas opcionais")
    ap.add_argument("--sem-venv", action="store_true", help="instala as dependências no usuário (pip --user) em vez de criar o .venv")
    ap.add_argument("--sem-dependencias", action="store_true", help="não instala as dependências (para testes)")
    ap.add_argument("--sem-abrir", action="store_true", help="não abre o painel no fim")
    a = ap.parse_args(argv)
    ins = Instalador(raiz, entrada, saida, executar, a.sim, a.nao)
    ins.dizer(f"Instalador do Cérebro do Projeto {__version__}")
    total = 6
    ins.passo(1, total, "Conferindo o Python", "O Cérebro precisa do Python 3.11 ou mais novo.")
    if not ins.conferir_python():
        return 1
    ins.passo(2, total, "Ambiente e dependências",
              "Crio um ambiente .venv só para o Cérebro (não mexe no seu Python) e instalo nele o que o Cérebro usa.")
    if a.sem_venv:
        pasta = Path(raiz) / ".venv"
        ok = True if a.sem_dependencias else ins.instalar_dependencias(pasta, usar_venv=False)
    else:
        try:
            pasta = ins.criar_venv(com_pip)
        except Exception as e:
            ins.dizer(f"      Não consegui criar o .venv ({type(e).__name__}: {e}). Tente:  python instalar.py --sem-venv")
            return 1
        ok = True if a.sem_dependencias else ins.instalar_dependencias(pasta)
    if not ok:
        return 1
    ins.passo(3, total, "Graphify (opcional)", "Sem ele o mapa do código não é desenhado; todo o resto funciona.")
    ins.oferecer_graphify()
    ins.passo(4, total, "Pasta de dados", "Crio ~/.cerebro, onde o Cérebro guarda a configuração e tudo o que aprende. Nada vai para dentro dos seus projetos.")
    ins.criar_casa()
    ins.dizer("\n[+] Ganchos do Claude Code (recomendado)")
    ins.oferecer_ganchos()
    ins.passo(5, total, "Atalho na área de trabalho", "Um clique no atalho abre o painel (sobe o servidor se for preciso).")
    if os.name != "nt" or ins.perguntar('Criar o atalho "Cérebro do Projeto" na área de trabalho?'):
        ins.criar_atalho(pasta, area)
    else:
        ins.dizer("      Ok, sem atalho. Para abrir: abrir_cerebro.bat (ou python abrir_cerebro.py).")
    ins.gravar_registro()
    ins.passo(6, total, "Abrindo o painel", "Na primeira vez, o painel mostra a faixa \"Primeiro uso\" para configurar seus projetos.")
    if not a.sem_abrir and ins.perguntar("Abrir o painel agora?"):
        ins.abrir_painel(pasta)
    ins.dizer("\nPronto! O Cérebro está instalado. Para abrir depois: o atalho, abrir_cerebro.bat (Windows) ou abrir_cerebro.sh (macOS/Linux).")
    ins.dizer("Para desinstalar: python desinstalar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
