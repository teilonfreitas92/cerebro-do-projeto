#!/bin/sh
# Abre o Cerebro do Projeto (macOS/Linux). Usa o venv criado pelo instalar.py quando existe.
AQUI="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$AQUI/.venv/bin/python" ]; then
  exec "$AQUI/.venv/bin/python" "$AQUI/abrir_cerebro.py" "$@"
fi
exec python3 "$AQUI/abrir_cerebro.py" "$@"
