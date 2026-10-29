#!/usr/bin/env python
"""Abre o Cérebro do Projeto no navegador padrão.

Se o servidor ainda não estiver no ar, sobe em segundo plano (sem janela preta) e espera ficar pronto. O link de abertura
leva a chave de acesso (?t=...), que o servidor troca por um cookie e tira da URL.
Fechar a página não derruba o servidor; ele encerra sozinho depois de 30 minutos sem nenhuma página aberta.

    python abrir_cerebro.py            # sobe (se preciso) e abre o navegador
    pythonw abrir_cerebro.py           # o mesmo, sem nenhuma janela (só Windows)
    python abrir_cerebro.py --sem-navegador   # só garante o servidor no ar e imprime o link
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from cerebro import config  # noqa: E402


def no_ar(porta):
    try:
        with urllib.request.urlopen(f"http://{config.HOST}:{porta}/api/saude", timeout=2) as r:
            return bool(json.loads(r.read()).get("cerebro"))
    except Exception:
        return False


def python_do_cerebro():
    """O Python que tem as dependências: o do venv .venv (criado pelo instalar.py) quando existe; senão o que está rodando."""
    venv = AQUI / ".venv"
    candidato = venv / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return candidato if candidato.is_file() else Path(sys.executable)


def subir(porta):
    exe = python_do_cerebro()
    if os.name == "nt" and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"                      # só Windows: sem janela preta
    extra = {"creationflags": 0x08000000 | 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}   # desacoplado
    subprocess.Popen([str(exe), str(AQUI / "cerebro.py"), "--porta", str(porta)], cwd=str(AQUI), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()
    porta = config.ler_config().get("porta") or config.PORTA_PADRAO
    if not no_ar(porta):
        subir(porta)
        for _ in range(60):
            time.sleep(0.5)
            if no_ar(porta):
                break
        else:
            print("O Cérebro não subiu em 30 s. Rode 'python cerebro.py' para ver o erro.", file=sys.stderr)
            return 1
    link = f"http://{config.HOST}:{porta}/?t={config.ler_token()}"
    if a.sem_navegador:
        print(link)
    else:
        webbrowser.open(link)
    return 0


if __name__ == "__main__":
    sys.exit(main())
