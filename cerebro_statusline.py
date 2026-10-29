#!/usr/bin/env python
"""statusLine do Claude Code -> Cérebro. O Claude Code roda este script a cada mensagem nova e manda um JSON pela entrada
padrão (doc oficial: https://code.claude.com/docs/en/statusline). O script:

1. grava ~/.cerebro/claude_status.json (escrita atômica) só com os campos úteis: limites 5 h / 7 dias (percentual e quando
   renova), modelo, custo da sessão, contexto. É desse arquivo que saem os anéis de limite no topo do Cérebro e em Custos;
2. imprime UMA linha curta (modelo · contexto · 5 h · 7 dias · custo);
3. ENCADEAMENTO: se você já tinha uma statusLine e escolheu "encadear" ao instalar, o comando antigo (guardado em
   ~/.cerebro/ganchos.json) roda com a mesma entrada e a saída DELE é a que aparece (a do Cérebro só entra se a dele falhar).

Nunca quebra a barra do Claude Code: qualquer erro vira uma linha simples. Tempo limite do comando antigo: 5 s.
O shell que roda o comando antigo vem SÓ de caminho absoluto do sistema (Git Bash instalado, PowerShell do Windows): a statusLine
roda na pasta da sessão, e um "bash.bat" plantado num repositório nunca é usado. Trava: com CEREBRO_TESTE_HOME,
CEREBRO_SEM_AGENDADOR ou CEREBRO_SEM_EFEITOS definida (testes e CI) o comando antigo nunca roda de verdade.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LIMITE = 512 * 1024


def casa():
    return Path(os.environ.get("CEREBRO_HOME") or (Path.home() / ".cerebro"))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _janela(d):
    if not isinstance(d, dict):
        return None
    p, r = _num(d.get("used_percentage")), _num(d.get("resets_at"))
    if p is None:
        return None
    return {"used_percentage": p, "resets_at": r}


def extrair(dados, anterior=None, agora=None):
    """Só os campos úteis. Se esta sessão ainda não trouxe os limites (chegam depois da 1ª resposta), mantém os últimos
    conhecidos enquanto a janela deles não renovou (os limites são da conta, não da sessão)."""
    agora = agora or time.time()
    dados = dados if isinstance(dados, dict) else {}
    rl = dados.get("rate_limits") if isinstance(dados.get("rate_limits"), dict) else {}
    limites = {}
    for chave in ("five_hour", "seven_day"):
        j = _janela(rl.get(chave))
        if j is None and isinstance(anterior, dict):
            velho = _janela(((anterior.get("rate_limits") or {}).get(chave)))
            if velho and (velho["resets_at"] is None or velho["resets_at"] > agora):
                j = velho
        if j is not None:
            limites[chave] = j
    m = dados.get("model") if isinstance(dados.get("model"), dict) else {}
    cw = dados.get("context_window") if isinstance(dados.get("context_window"), dict) else {}
    custo = dados.get("cost") if isinstance(dados.get("cost"), dict) else {}
    saida = {"atualizado": agora, "rate_limits": limites,
             "model": {"id": str(m.get("id") or "")[:80], "display_name": str(m.get("display_name") or "")[:40]},
             "cost": {"total_cost_usd": _num(custo.get("total_cost_usd"))},
             "context_window": {"used_percentage": _num(cw.get("used_percentage")), "context_window_size": _num(cw.get("context_window_size"))}}
    return saida


def gravar(saida, c=None):
    c = c or casa()
    c.mkdir(parents=True, exist_ok=True)
    alvo = c / "claude_status.json"
    tmp = alvo.with_name(f"claude_status.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, alvo)


def linha(s):
    partes = [s["model"]["display_name"] or s["model"]["id"] or "Claude"]
    ctx = s["context_window"]["used_percentage"]
    if ctx is not None:
        partes.append(f"contexto {ctx:.0f}%")
    for chave, rotulo in (("five_hour", "5h"), ("seven_day", "7d")):
        j = s["rate_limits"].get(chave)
        if j:
            partes.append(f"{rotulo} {j['used_percentage']:.0f}%")
    if s["cost"]["total_cost_usd"] is not None:
        partes.append(f"US$ {s['cost']['total_cost_usd']:.2f}".replace(".", ","))
    return " · ".join(partes)


def comando_anterior(c=None):
    """O comando da statusLine antiga, só quando o dono escolheu encadear (ver cerebro/ganchos_claude.py)."""
    c = c or casa()
    try:
        e = json.loads((c / "ganchos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(e, dict) or e.get("statusline_modo") != "encadear":
        return ""
    ant = e.get("statusline_anterior")
    cmd = ant.get("command") if isinstance(ant, dict) else ""
    return cmd if isinstance(cmd, str) and "cerebro_statusline" not in cmd else ""   # nunca chama a si mesmo


VARIAVEIS_SEM_EFEITOS = ("CEREBRO_TESTE_HOME", "CEREBRO_SEM_AGENDADOR", "CEREBRO_SEM_EFEITOS")


def sem_efeitos():
    """Testes e CI: nada de rodar programa de verdade daqui."""
    return any(os.environ.get(v) for v in VARIAVEIS_SEM_EFEITOS)


def _exe_seguro(caminho):
    """O caminho só serve se for ABSOLUTO, existir e não estiver na pasta atual (a da sessão, que pode ser um repositório baixado)."""
    if not caminho or not os.path.isabs(caminho):
        return None
    p = Path(caminho)
    try:
        if not p.is_file() or p.resolve().parent == Path.cwd().resolve():
            return None
    except OSError:
        return None
    return str(p)


def _no_path(nome):
    """Procura no PATH só em pastas absolutas e nunca na pasta atual (o shutil.which do Windows olha a pasta atual primeiro)."""
    extensoes = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e] if os.name == "nt" else [""]
    for pasta in os.environ.get("PATH", "").split(os.pathsep):
        pasta = pasta.strip().strip('"')
        if not pasta or not os.path.isabs(pasta):
            continue
        for ext in extensoes:
            achado = _exe_seguro(os.path.join(pasta, nome + ext.lower()))
            if achado:
                return achado
    return None


def _git_bash():
    """Git Bash como o Claude Code acha: CLAUDE_CODE_GIT_BASH_PATH, as pastas de instalação do Git, depois o PATH (seguro)."""
    candidatos = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")]
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if os.environ.get(var):
            candidatos.append(os.path.join(os.environ[var], "Git", "bin", "bash.exe"))
    if os.environ.get("LOCALAPPDATA"):
        candidatos.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Git", "bin", "bash.exe"))
    for c in candidatos:
        achado = _exe_seguro(c)
        if achado:
            return achado
    return _no_path("bash")


def _powershell():
    raiz = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return _exe_seguro(os.path.join(raiz, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"))


def _argumentos_shell(cmd):
    """A statusLine antiga é um comando de SHELL (é o formato do Claude Code). Roda como o Claude Code rodaria: no Windows
    pelo Git Bash se existir, senão PowerShell; fora do Windows, /bin/sh. Sempre lista de argumentos, sem cmd.exe, e sempre
    com o caminho absoluto do programa. None se não houver um shell seguro."""
    if os.name == "nt":
        bash = _git_bash()
        if bash:
            return [bash, "-c", cmd]
        ps = _powershell()
        return [ps, "-NoProfile", "-NonInteractive", "-Command", cmd] if ps else None
    return ["/bin/sh", "-c", cmd]


def _executar_de_verdade(argv, **k):
    if sem_efeitos():
        raise OSError("statusLine antiga não roda de verdade em teste/CI")
    return subprocess.run(argv, **k)


def rodar_anterior(cmd, entrada, executar=None):
    executar = executar or _executar_de_verdade
    try:
        argv = _argumentos_shell(cmd)
        if not argv:
            return ""
        r = executar(argv, input=entrada, capture_output=True, timeout=5,
                     creationflags=0x08000000 if os.name == "nt" else 0)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", "replace").rstrip("\r\n")
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def principal(entrada, c=None, executar=None):
    c = c or casa()
    try:
        dados = json.loads(entrada.decode("utf-8", "replace")) if entrada and len(entrada) <= LIMITE else {}
    except ValueError:
        dados = {}
    try:
        anterior = json.loads((c / "claude_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        anterior = None
    s = extrair(dados, anterior)
    try:
        gravar(s, c)
    except OSError:
        pass
    cmd = comando_anterior(c)
    if cmd:
        saida = rodar_anterior(cmd, entrada, executar)
        if saida:
            return saida
    return linha(s)


def main():
    try:
        entrada = sys.stdin.buffer.read(LIMITE + 1) if sys.stdin is not None else b""
    except (OSError, ValueError, AttributeError):
        entrada = b""
    try:
        texto = principal(entrada)
    except Exception:
        texto = "Claude"
    try:
        sys.stdout.buffer.write((texto + "\n").encode("utf-8", "replace"))
        sys.stdout.flush()
    except (OSError, AttributeError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
