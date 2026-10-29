#!/usr/bin/env python
"""Prova do instalador num PC limpo (roda no GitHub Actions e também aqui, localmente).

    python testes/ci_instalador.py              # instala de verdade (cria .venv e baixa as dependências: precisa de internet)
    python testes/ci_instalador.py --rapido     # sem .venv e sem baixar nada: usa o Python atual (que já tem o aiohttp)
    python testes/ci_instalador.py --pasta X    # pasta de trabalho (padrão: uma pasta nova dentro de ~/.cerebro-testes)

O que faz, tudo dentro de UMA pasta de trabalho temporária (nunca no ~/.cerebro nem no ~/.claude de verdade):
  1. copia o Cérebro para <trabalho>/projeto e monta um "PC" de mentira: HOME e USERPROFILE apontam para <trabalho>/home
     (com arquivos-isca em .claude e Desktop) e CEREBRO_HOME para <trabalho>/casa;
  2. roda `instalar.py` sem perguntas (--nao --sem-abrir: sem Graphify, sem atalho, sem abrir o navegador);
  3. sobe o servidor (abrir_cerebro.py --sem-navegador, o mesmo caminho do atalho), numa porta livre que NÃO é a 8188
     nem nenhuma das reservadas, espera /api/saude responder, abre o link com a chave e confere que a página vem (200)
     e que sem a chave nada abre (401);
  4. encerra o servidor pelo próprio botão da página (/api/encerrar) e espera ele sumir;
  5. roda `desinstalar.py --sim --apagar-dados` e confere que a casa e o .venv sumiram e que NADA fora deles foi tocado
     (iscas intactas, nenhum arquivo do Cérebro a menos, nada novo na pasta de trabalho além do que se espera).
Sai com 0 se tudo passou e com 1 (e a lista do que falhou) se algo não bateu. Só o que está dentro da pasta de trabalho é
criado; ela é apagada no fim pelas travas de testes/_ambiente.py (apagar), nunca por um rmtree solto.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from testes import _ambiente as amb  # noqa: E402  (isola CEREBRO_HOME/CEREBRO_CLAUDE deste processo e dá a pasta de testes)

HOST = "127.0.0.1"
PORTAS_PROIBIDAS = {80, 443, 8188, 8050, 8060, 8070, 8090, 8091, 8095, 8097, 7980}      # ver docs/referencia.md (Segurança)
SEM_JANELA = 0x08000000 if os.name == "nt" else 0
IGNORAR_NA_COPIA = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", "*.pyc", ".cerebro-testes", ".claude", ".ruff_cache",
                                          "node_modules", "perfil_chrome*", ".instalacao.json", "token", "servidor.json", "config.json",
                                          "graphify-out", "saida", "fotos-temporarias")


class Falha(Exception):
    """Uma conferência não bateu."""


def porta_livre():
    """Uma porta livre de verdade (o sistema escolhe) que não seja nenhuma das proibidas."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind((HOST, 0))
            p = s.getsockname()[1]
        if p not in PORTAS_PROIBIDAS:
            return p
    raise Falha("não achei uma porta livre fora das reservadas")


def instantaneo(pasta):
    """{caminho relativo: sha256} de todos os arquivos da pasta (vazio se ela não existir). Para comparar antes e depois."""
    pasta = Path(pasta)
    saida = {}
    if pasta.is_dir():
        for p in sorted(pasta.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                saida[p.relative_to(pasta).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return saida


def diferencas(antes, depois):
    """(sumiram, novos, mudaram) entre dois instantâneos."""
    return (sorted(set(antes) - set(depois)), sorted(set(depois) - set(antes)),
            sorted(k for k in set(antes) & set(depois) if antes[k] != depois[k]))


def conferir(condicao, mensagem, ok_lista):
    if not condicao:
        raise Falha(mensagem)
    ok_lista.append(mensagem)
    print(f"  ok  {mensagem}", flush=True)


def rodar(argv, env, cwd, tempo=900):
    """Roda um comando (sem shell, com tempo limite, sem janela). Devolve (código, saída juntada)."""
    r = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=tempo, stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def python_do_venv(projeto):
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return Path(projeto).joinpath(".venv", *sub)


def esperar(condicao, tempo, passo=0.5):
    fim = time.monotonic() + tempo
    while time.monotonic() < fim:
        try:
            r = condicao()
            if r:
                return r
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(passo)
    return None


def saude(porta):
    with urllib.request.urlopen(f"http://{HOST}:{porta}/api/saude", timeout=3) as r:
        return r.status == 200 and bool(json.loads(r.read()).get("cerebro"))


def ambiente_filho(trabalho, home, casa):
    """Variáveis de ambiente dos processos filhos (instalar, servidor, desinstalar): o "PC de mentira".
    Sem CEREBRO_TESTE_HOME (o instalador roda como de verdade), então outras travas valem: CEREBRO_SEM_AGENDADOR=1 (o
    desinstalar.py --sim chamaria schtasks /Delete nas tarefas DO DONO) e CEREBRO_BACKUP na pasta de trabalho (o desinstalador
    não olha nem guarda nada na pasta de backup de verdade)."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CEREBRO_HOME": str(casa), "CEREBRO_CLAUDE": str(Path(home) / ".claude"),
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1", "PIP_NO_CACHE_DIR": "1",
           "CEREBRO_SEM_AGENDADOR": "1", "CEREBRO_BACKUP": str(Path(trabalho) / "backup")}
    for herdada in ("CEREBRO_TESTE_HOME", "CEREBRO_CLAUDE_SETTINGS"):     # o settings.json é o do HOME de mentira
        env.pop(herdada, None)
    return env


def verificar(trabalho, rapido=False):
    """Roda tudo na pasta de trabalho. Devolve a lista de conferências que passaram; levanta Falha na primeira que não bate."""
    ok = []
    trabalho = Path(trabalho)
    projeto, casa, home, vizinho = trabalho / "projeto", trabalho / "casa", trabalho / "home", trabalho / "vizinho"

    print("1. Montando o PC de mentira", flush=True)
    shutil.copytree(RAIZ, projeto, ignore=IGNORAR_NA_COPIA)
    for rel, texto in ((".claude/projects/C--Exemplo/sessao.jsonl", '{"type":"user"}\n'), (".claude/settings.json", "{}\n"),
                       ("Desktop/anotacao.txt", "não mexa em mim\n"), ("Documents/Cérebro do Projeto.lnk", "isca\n")):
        arq = home / rel
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(texto, encoding="utf-8")
    vizinho.mkdir()
    (vizinho / "sentinela.txt").write_text("fora do Cérebro\n", encoding="utf-8")
    token_real = Path(os.path.expanduser("~")) / ".cerebro" / "token"          # o de verdade: só conferimos que ninguém mexeu nele
    token_real_antes = hashlib.sha256(token_real.read_bytes()).hexdigest() if token_real.is_file() else None
    antes_home, antes_vizinho, antes_projeto = instantaneo(home), instantaneo(vizinho), instantaneo(projeto)
    env = ambiente_filho(trabalho, home, casa)
    conferir(not casa.exists(), "a casa (CEREBRO_HOME) ainda não existe: máquina limpa", ok)

    print("2. Instalando (instalar.py, sem perguntas)", flush=True)
    argv = [sys.executable, "instalar.py", "--nao", "--sem-abrir"] + (["--sem-venv", "--sem-dependencias"] if rapido else [])
    codigo, saida = rodar(argv, env, projeto)
    if codigo != 0:
        raise Falha(f"instalar.py terminou com código {codigo}:\n{saida[-1500:]}")
    conferir(casa.is_dir() and (casa / "projetos").is_dir(), "o instalador criou a casa de dados", ok)
    registro = json.loads((projeto / ".instalacao.json").read_text(encoding="utf-8"))
    conferir("atalho" not in registro, "nenhum atalho foi criado (modo não interativo)", ok)
    if not rapido:
        conferir(python_do_venv(projeto).is_file(), "o .venv foi criado com o Python dele", ok)
    conferir(instantaneo(home) == antes_home, "a instalação não tocou em nada do HOME (.claude, Desktop...)", ok)

    print("3. Subindo o servidor e abrindo a página", flush=True)
    porta = porta_livre()
    conferir(porta not in PORTAS_PROIBIDAS, f"porta {porta} escolhida (livre e fora das proibidas, incluída a 8188)", ok)
    (casa / "config.json").write_text(json.dumps({"porta": porta}), encoding="utf-8")
    python_srv = python_do_venv(projeto) if (not rapido and python_do_venv(projeto).is_file()) else Path(sys.executable)
    try:
        codigo, saida = rodar([str(python_srv), "abrir_cerebro.py", "--sem-navegador"], env, projeto, tempo=120)
        if codigo != 0:
            raise Falha(f"abrir_cerebro.py terminou com código {codigo}:\n{saida[-1500:]}")
        link = saida.strip().splitlines()[-1]
        conferir(link.startswith(f"http://{HOST}:{porta}/?t="), "o link de abertura é local e leva a chave de acesso", ok)
        conferir(bool(esperar(lambda: saude(porta), 60)), "/api/saude respondeu 200 ('o Cérebro está no ar')", ok)
        galeta = http.cookiejar.CookieJar()
        com_chave = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(galeta))
        with com_chave.open(link, timeout=10) as r:
            corpo = r.read().decode("utf-8", "replace")
            conferir(r.status == 200 and "<title>" in corpo, "a página com a chave respondeu 200 (depois do redirecionamento)", ok)
        with com_chave.open(f"http://{HOST}:{porta}/static/app.js", timeout=10) as r:
            conferir(r.status == 200, "os arquivos da página (/static/app.js) vieram", ok)
        with com_chave.open(f"http://{HOST}:{porta}/api/projetos", timeout=10) as r:
            conferir(r.status == 200 and isinstance(json.loads(r.read()), (list, dict)), "a API respondeu com a chave", ok)
        try:
            urllib.request.urlopen(f"http://{HOST}:{porta}/api/projetos", timeout=10)
            semchave = 200
        except urllib.error.HTTPError as e:
            semchave = e.code
        conferir(semchave == 401, "sem a chave a API recusa (401)", ok)
        conferir((casa / "servidor.json").is_file() and (casa / "token").is_file(), "servidor.json e token existem na casa", ok)

        print("4. Encerrando o servidor", flush=True)
        pedido = urllib.request.Request(f"http://{HOST}:{porta}/api/encerrar", data=b"{}", method="POST",
                                        headers={"Content-Type": "application/json", "Origin": f"http://{HOST}:{porta}"})
        with com_chave.open(pedido, timeout=10) as r:
            conferir(r.status == 200, "/api/encerrar aceitou o pedido", ok)

        def sumiu():
            try:
                saude(porta)
            except (OSError, urllib.error.URLError):
                return True
            return False
        conferir(bool(esperar(sumiu, 30)), "o servidor parou de responder", ok)
        conferir(bool(esperar(lambda: not (casa / "servidor.json").exists(), 15)), "servidor.json sumiu sozinho (liberou a instância)", ok)
    finally:
        _derrubar_se_ainda_no_ar(casa)

    print("5. Desinstalando (desinstalar.py, sem perguntas)", flush=True)
    codigo, saida = rodar([sys.executable, "desinstalar.py", "--sim", "--apagar-dados"], env, projeto, tempo=300)
    if codigo != 0:
        raise Falha(f"desinstalar.py terminou com código {codigo}:\n{saida[-1500:]}")
    conferir(not casa.exists(), "a casa de dados sumiu", ok)
    conferir(not (projeto / ".venv").exists(), "o .venv sumiu (ou nunca existiu no modo rápido)", ok)

    print("6. Conferindo que NADA fora disso foi tocado", flush=True)
    sumiram, novos, mudaram = diferencas(antes_home, instantaneo(home))
    conferir(not (sumiram or novos or mudaram), f"o HOME de mentira está igual ao do começo (iscas intactas) {sumiram + novos + mudaram or ''}", ok)
    conferir(instantaneo(vizinho) == antes_vizinho, "a pasta vizinha está intacta", ok)
    sumiram, novos, mudaram = diferencas(antes_projeto, instantaneo(projeto))
    conferir(not sumiram and not mudaram, f"nenhum arquivo do Cérebro foi apagado ou mudado {sumiram + mudaram or ''}", ok)
    conferir(set(novos) <= {".instalacao.json"}, f"único arquivo novo na pasta do Cérebro: .instalacao.json {novos}", ok)
    conferir({p.name for p in trabalho.iterdir()} - {"backup"} == {"projeto", "home", "vizinho"},
             "a pasta de trabalho só tem projeto, home, vizinho (e talvez a pasta de backup de mentira): a casa sumiu", ok)
    conferir(not (trabalho / "backup").exists() or {p.name for p in (trabalho / "backup").iterdir()} <= {"copias", ".cerebro-backup"},
             "a pasta de backup de mentira, se existe, só guarda as cópias da casa", ok)
    token_real_depois = hashlib.sha256(token_real.read_bytes()).hexdigest() if token_real.is_file() else None
    conferir(token_real_antes == token_real_depois, "o token do ~/.cerebro de verdade (se existe) não foi mexido", ok)
    return ok


def _derrubar_se_ainda_no_ar(casa):
    """Rede de segurança (só roda se algo falhou antes): encerra o servidor registrado na casa DESTA verificação."""
    arq = Path(casa) / "servidor.json"
    try:
        pid = json.loads(arq.read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(pid, int) and pid > 0 and pid != os.getpid():
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prova do instalador num PC limpo")
    ap.add_argument("--rapido", action="store_true", help="sem .venv e sem baixar dependências (usa o Python atual)")
    ap.add_argument("--pasta", default=None, help="pasta de trabalho (padrão: nova, dentro de ~/.cerebro-testes; apagada no fim)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    trabalho = Path(a.pasta).resolve() if a.pasta else amb.BASE / "ci_instalador"
    if trabalho.exists() and any(trabalho.iterdir()):
        print(f"A pasta de trabalho {trabalho} já tem coisas; use uma pasta vazia ou nova.", file=sys.stderr)
        return 2
    trabalho.mkdir(parents=True, exist_ok=True)
    print(f"Pasta de trabalho: {trabalho}", flush=True)
    try:
        ok = verificar(trabalho, a.rapido)
    except Falha as e:
        print(f"\nFALHOU: {e}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired as e:
        print(f"\nFALHOU: tempo esgotado em {e.cmd}", file=sys.stderr)
        return 1
    print(f"\nTudo certo: {len(ok)} conferências passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
