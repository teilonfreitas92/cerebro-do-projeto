"""Roda todos os testes com a conferência de isolamento ANTES do primeiro teste.

Uso, na raiz do repositório:  python -m testes.rodar          (equivale a
    python -m unittest discover -s testes -t . -p "test_*.py"  mas imprime e confere as pastas antes)
Se config.CASA ou config.PROJETOS_CLAUDE não estiverem dentro de ~/.cerebro-testes, PARA sem rodar nada.
"""
import sys
import unittest
from pathlib import Path

from testes import _ambiente as amb      # isola o ambiente ANTES de importar o cerebro
from cerebro import config


def main():
    print("config.CASA            =", config.CASA, flush=True)
    print("config.PROJETOS_CLAUDE =", config.PROJETOS_CLAUDE, flush=True)
    raiz = (Path.home() / ".cerebro-testes").resolve()
    for nome, p in (("CASA", config.CASA), ("PROJETOS_CLAUDE", config.PROJETOS_CLAUDE)):
        try:
            Path(p).resolve().relative_to(raiz)
        except ValueError:
            print(f"PARE: config.{nome} fora de {raiz}. Nenhum teste foi rodado.")
            return 2
    suite = unittest.defaultTestLoader.discover("testes", pattern="test_*.py", top_level_dir=str(amb.RAIZ))
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
