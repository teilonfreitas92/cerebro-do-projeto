#!/usr/bin/env python
"""Sobe o Cérebro do Projeto com dados FICTÍCIOS, para você ver como ele funciona sem usar nenhum dado seu.

    python demo/rodar_demo.py               # gera a demonstração (na primeira vez) e sobe o servidor; Ctrl+C para parar
    python demo/rodar_demo.py --refazer     # apaga e gera a demonstração de novo
    python demo/rodar_demo.py --abrir       # também abre o navegador
    python demo/rodar_demo.py --so-gerar    # só gera os dados e sai

Tudo fica em demo/saida (ou na pasta de --destino): a "~/.cerebro" e as "conversas do Claude Code" da demonstração são só dali.
O seu ~/.cerebro e o seu ~/.claude não são usados nem alterados.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))


def python_do_cerebro():
    venv = RAIZ / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return str(venv) if venv.is_file() else sys.executable


def porta_livre(preferida):
    for p in [preferida] + list(range(preferida + 1, preferida + 30)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("Não achei uma porta livre.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Demonstração do Cérebro do Projeto (dados fictícios)")
    ap.add_argument("--destino", default=str(AQUI / "saida"))
    ap.add_argument("--porta", type=int, default=8190)
    ap.add_argument("--refazer", action="store_true")
    ap.add_argument("--abrir", action="store_true")
    ap.add_argument("--so-gerar", action="store_true")
    a = ap.parse_args(argv)
    destino = Path(a.destino).resolve()
    py = python_do_cerebro()
    if a.refazer or not (destino / "casa" / "config.json").is_file():
        print("Gerando os dados fictícios da demonstração (uns 30 segundos)…", flush=True)
        r = subprocess.run([py, str(AQUI / "gerar_demo.py"), "--destino", str(destino)])
        if r.returncode != 0:
            return r.returncode
    if a.so_gerar:
        return 0
    env = {**os.environ, "CEREBRO_HOME": str(destino / "casa"), "CEREBRO_CLAUDE": str(destino / "claude"), "PYTHONUTF8": "1",
           "CEREBRO_BACKUP": str(destino / "backup"), "CEREBRO_DEMO": "1"}   # backup e Agendador nunca os de verdade
    porta = porta_livre(a.porta)
    servidor = subprocess.Popen([py, str(RAIZ / "cerebro.py"), "--porta", str(porta)], env=env, cwd=str(RAIZ))
    try:
        for _ in range(60):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=1):
                    break
            except OSError:
                continue
        token = (destino / "casa" / "token").read_text(encoding="ascii").strip()
        link = f"http://127.0.0.1:{porta}/?t={token}"
        print(f"\nDemonstração no ar (dados FICTÍCIOS). Abra:\n  {link}\n\nCtrl+C para parar.", flush=True)
        if a.abrir:
            webbrowser.open(link)
        servidor.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if servidor.poll() is None:
            servidor.terminate()
            try:
                servidor.wait(10)
            except subprocess.TimeoutExpired:
                servidor.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
