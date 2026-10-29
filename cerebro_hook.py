#!/usr/bin/env python
"""Gancho (hook) do Claude Code -> Cérebro. Minúsculo de propósito: lê o evento (JSON) da entrada padrão e entrega por POST
local em http://127.0.0.1:<porta>/api/hooks/evento, com o segredo de ~/.cerebro/hooks_token no cabeçalho X-Cerebro-Hooks.

* Nunca atrapalha o Claude Code: roda como gancho "async" (o Claude Code não espera), tempo limite de 2 s, qualquer erro
  é engolido e a saída é sempre 0.
* Cérebro fechado (sem ~/.cerebro/servidor.json, ou porta recusando): LIGA o servidor em segundo plano (abrir_cerebro.py
  --sem-navegador, sem janela, no máximo uma tentativa a cada 2 min) e sai; este evento se perde, os próximos chegam.
* A porta vem do servidor.json (a porta EM USO), então mudar a porta em Configurações não exige reinstalar.
* Só imprime algo se o Cérebro devolver um JSON com "hookSpecificOutput" (ponto de extensão; hoje nada é devolvido).
Instalado pelo Cérebro (Configurações › Agentes ao vivo instantâneo, ou: python cerebro_cli.py hooks --instalar --confirmar).

Modo --sincrono (só o grupo SessionStart com matcher "startup|clear|compact", timeout 5 s): logo depois de um /clear (clear_session)
ou de uma compactação da sessão GESTORA, atualiza a corrente (novo id de transcrição no /clear) e imprime additionalContext com
a linha do ~/.cerebro/GESTOR.md + o resumo do último capítulo (cerebro/gestora_troca.py e capitulos.py). Usa só arquivos de
~/.cerebro (não precisa do servidor), desiste sozinho em 4 s e qualquer erro sai 0 sem texto. Não manda o evento ao servidor
(o grupo assíncrono normal já manda).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

LIMITE = 256 * 1024
ESPERA_LIGAR = 120          # segundos entre duas tentativas de ligar o servidor (vários ganchos podem disparar juntos)


def _sem_efeitos():
    return any(os.environ.get(v) for v in ("CEREBRO_TESTE_HOME", "CEREBRO_SEM_EFEITOS", "CEREBRO_SEM_AGENDADOR"))


def ligar_servidor(c, executar=None, agora=None):
    """Sobe o Cérebro em segundo plano (sem janela, desligado deste processo). Só se os ganchos estão configurados (hooks_token)
    e não houve outra tentativa há menos de ESPERA_LIGAR. Devolve True se tentou. Nunca levanta erro."""
    import subprocess
    import time
    try:
        if not (c / "hooks_token").is_file():
            return False
        marca = c / ".ligando"
        agora = agora or time.time()
        try:
            if agora - marca.stat().st_mtime < ESPERA_LIGAR:
                return False
        except OSError:
            pass
        marca.write_text(str(int(agora)), encoding="ascii")
        if executar is None:
            if _sem_efeitos():
                return False
            executar = subprocess.Popen
        raiz = Path(__file__).resolve().parent
        py = Path(sys.executable)
        pyw = py.with_name("pythonw.exe")
        exe = str(pyw if os.name == "nt" and pyw.is_file() else py)
        flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0   # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
        executar([exe, str(raiz / "abrir_cerebro.py"), "--sem-navegador"], cwd=str(raiz), stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        return True
    except Exception:
        return False


def casa():
    return Path(os.environ.get("CEREBRO_HOME") or (Path.home() / ".cerebro"))


def ler_entrada():
    try:
        fonte = sys.stdin.buffer if sys.stdin is not None else None
        if fonte is None:
            return b""
        return fonte.read(LIMITE + 1)
    except (OSError, ValueError, AttributeError):
        return b""


def _abrir_sem_proxy(req, timeout):
    """Conexão direta (nunca passa por proxy configurado no Windows: é tudo local)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def entregar(corpo, c=None, abrir=None, ligar=None):
    """Devolve o texto da resposta ('' se nada). Nunca levanta erro."""
    c = c or casa()
    abrir = abrir or _abrir_sem_proxy
    if not corpo or len(corpo) > LIMITE:
        return ""
    try:
        porta = int(json.loads((c / "servidor.json").read_text(encoding="utf-8"))["porta"])
        token = (c / "hooks_token").read_text(encoding="ascii").strip()
    except (OSError, ValueError, KeyError, TypeError):
        (ligar or ligar_servidor)(c)                # Cérebro fechado: liga (só se os ganchos estão configurados)
        return ""
    if not (1024 <= porta <= 65535) or len(token) < 32:
        return ""
    req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/hooks/evento", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json", "X-Cerebro-Hooks": token})
    try:
        with abrir(req, timeout=2) as r:
            return r.read(64 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return ""                                   # o servidor respondeu (com erro): está no ar
    except Exception:
        # sem resposta: recusou ou estourou o tempo (no Windows, porta fechada em 127.0.0.1 demora ~2 s e vira timeout).
        # O servidor.json ficou para trás: liga. Se ele só estava lento, o abrir_cerebro vê que está no ar e não sobe outro.
        (ligar or ligar_servidor)(c)
        return ""


def sincrono(bruto, c=None):
    """Texto JSON para o SessionStart "clear"/"compact" da sessão gestora, ou '' (nada a dizer). Ver gestora_troca.ao_iniciar_sessao."""
    ev = json.loads(bruto.decode("utf-8", "replace")) if bruto else {}
    if not isinstance(ev, dict) or ev.get("hook_event_name") != "SessionStart" or ev.get("source") not in ("startup", "clear", "compact"):
        return ""
    if c is not None:
        os.environ["CEREBRO_HOME"] = str(c)
    raiz = str(Path(__file__).resolve().parent)
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from cerebro.gestora_troca import ao_iniciar_sessao
    texto = ao_iniciar_sessao(ev)
    if not texto:
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": texto}})          # ASCII: o console do Windows não estraga acento


def main_sincrono():
    import threading
    threading.Timer(4.0, lambda: os._exit(0)).start()          # nunca passa do timeout do Claude Code (5 s)
    try:
        saida = sincrono(ler_entrada())
        if saida and sys.stdout is not None:
            sys.stdout.write(saida)
            sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)


def main():
    if "--sincrono" in sys.argv[1:]:
        return main_sincrono()
    try:
        resposta = entregar(ler_entrada())
        d = json.loads(resposta) if resposta.strip().startswith("{") else {}
        if isinstance(d, dict) and d.get("hookSpecificOutput") and sys.stdout is not None:
            sys.stdout.write(json.dumps(d, ensure_ascii=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
