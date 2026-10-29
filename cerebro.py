#!/usr/bin/env python
"""Cérebro do Projeto — sobe o servidor local (127.0.0.1:8188 por padrão; só nesta máquina).

    python cerebro.py                 # sobe e fica rodando (encerra sozinho após 30 min sem nenhuma página aberta)
    python cerebro.py --porta 8189
    python cerebro.py --link          # só imprime o link de abertura (com a chave de acesso) e sai
"""
import argparse
import sys

try:
    from cerebro import config, servidor
except ModuleNotFoundError as e:       # faltou instalar as dependências: explica em vez de despejar um erro técnico
    if e.name == "aiohttp":
        sys.exit("Falta instalar as dependências do Cérebro. Rode:  python instalar.py   (ele cuida de tudo)")
    raise


def main():
    ap = argparse.ArgumentParser(description="Cérebro do Projeto — servidor local")
    ap.add_argument("--porta", type=int, default=None, help=f"porta (padrão: a do config.json, {config.PORTA_PADRAO})")
    ap.add_argument("--link", action="store_true", help="imprime o link de abertura e sai")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    porta = a.porta or config.ler_config().get("porta") or config.PORTA_PADRAO
    if a.link:
        print(f"http://{config.HOST}:{porta}/?t={config.ler_token()}")
        return 0
    return servidor.executar(porta)


if __name__ == "__main__":
    sys.exit(main())
