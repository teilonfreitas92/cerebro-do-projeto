@echo off
rem Abre o Cerebro do Projeto (sobe o servidor se preciso). Sem janela preta. So Windows.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0abrir_cerebro.py"
) else (
  start "" pythonw "%~dp0abrir_cerebro.py"
)
