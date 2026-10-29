"""Testes do Cérebro. Importar este pacote já isola o ambiente: CEREBRO_HOME e CEREBRO_CLAUDE passam a apontar para pastas
temporárias ANTES de qualquer módulo do Cérebro ser importado (ver _ambiente.py). Isso protege a pasta .cerebro e a pasta
.claude do dono (as conversas e a memória do Claude Code) de qualquer teste que apague pastas."""
from . import _ambiente  # noqa: F401
