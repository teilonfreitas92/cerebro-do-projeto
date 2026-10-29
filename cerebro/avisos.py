"""Avisos no Windows: notificação nativa (a "torrada" do canto da tela) sem instalar nada.

    avisar(titulo, texto, chave, tipo="geral")  ->  "mostrado" | "repetido" | "nao_perturbe" | "desligado" | "sem_windows" | "falhou"

* Windows: PowerShell com Windows.UI.Notifications (vem com o Windows 10/11), sem janela (CREATE_NO_WINDOW), tempo limite de
  15 s, numa thread (quem chama nunca espera). O texto vai por VARIÁVEL DE AMBIENTE, nunca montado dentro do script, e o
  PowerShell escapa o XML: um texto malicioso não vira comando.
* Anti-repetição: o mesmo 'chave' não repete antes de 'repetir_minutos' (padrão 10).
* "Não perturbe" por horário (ex.: 22:00 até 07:00): o aviso é só registrado.
* O PowerShell é sempre o do sistema, por caminho absoluto (%SystemRoot%/System32/WindowsPowerShell/v1.0/powershell.exe):
  nunca um "powershell.exe" achado na pasta atual. Trava: com CEREBRO_TESTE_HOME, CEREBRO_SEM_AGENDADOR ou CEREBRO_SEM_EFEITOS
  definida (testes, CI, servidor de teste) nenhum PowerShell roda de verdade; o aviso fica só registrado como "falhou".
* Linux/macOS: não mostra nada, só registra (histórico em memória e em ~/.cerebro/avisos.jsonl).
* Preferências em ~/.cerebro/avisos.json (ligar/desligar por tipo, não perturbe). A página: Configurações › "Avisos no Windows".

Gatilhos ligados aos ganchos do Claude Code (ligar_gatilhos): subagente da sessão gestora terminou ("chegou item a conferir"),
Notification (precisa de permissão / esperando você) e sessão que parou depois de trabalhar mais de N minutos. Outros módulos
(backup que falhou, orçamento estourado...) chamam avisar(..., tipo="geral") direto.
"""
import json
import os
import subprocess
import threading
import time
from collections import deque

from . import armazem, config
from .segredos import encurtar

TIPOS = {"subagente_terminou": "Subagente da gestora terminou (chegou item a conferir)",
         "precisa_de_voce": "O Claude Code precisa de você (permissão ou esperando resposta)",
         "sessao_parou": "Uma sessão parou depois de trabalhar um bom tempo",
         "geral": "Outros avisos do Cérebro (backup, orçamento...)"}
PADRAO = {"ligado": True, "tipos": {k: True for k in TIPOS}, "repetir_minutos": 10, "parou_apos_minutos": 5,
          "nao_perturbe": {"ligado": False, "inicio": "22:00", "fim": "07:00"}}
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"   # id do PowerShell: dispensa registrar app

# O script é FIXO; título e texto chegam por variáveis de ambiente e são escapados para XML dentro do próprio PowerShell.
SCRIPT_TOAST = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
    "$t=[System.Security.SecurityElement]::Escape($env:CEREBRO_AVISO_TITULO);"
    "$x=[System.Security.SecurityElement]::Escape($env:CEREBRO_AVISO_TEXTO);"
    "$d=New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$d.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>'+$t+'</text><text>'+$x+'</text></binding></visual></toast>');"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CEREBRO_AVISO_APP).Show("
    "[Windows.UI.Notifications.ToastNotification]::new($d))"
)

_trava = threading.Lock()
_ultimos = {}                  # chave -> quando foi mostrado
_historico = deque(maxlen=50)
_turnos_avisados = deque(maxlen=500)   # (sessão, início do turno) que já avisaram ao parar


def arquivo_prefs():
    return config.CASA / "avisos.json"


def preferencias():
    d = armazem.ler_json(arquivo_prefs(), {}) or {}
    p = json.loads(json.dumps(PADRAO))
    if isinstance(d, dict):
        for k in ("ligado",):
            if isinstance(d.get(k), bool):
                p[k] = d[k]
        for k in ("repetir_minutos", "parou_apos_minutos"):
            if isinstance(d.get(k), int) and not isinstance(d.get(k), bool):
                p[k] = d[k]
        if isinstance(d.get("tipos"), dict):
            p["tipos"].update({k: v for k, v in d["tipos"].items() if k in TIPOS and isinstance(v, bool)})
        if isinstance(d.get("nao_perturbe"), dict):
            p["nao_perturbe"].update({k: v for k, v in d["nao_perturbe"].items() if k in p["nao_perturbe"]})
    return p


def _hora_valida(t):
    try:
        h, m = str(t).split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59 and len(h) <= 2 and len(m) == 2
    except ValueError:
        return False


def salvar_preferencias(novo):
    """Valida e grava. Levanta ValueError com mensagem em português se algo estiver errado."""
    if not isinstance(novo, dict):
        raise ValueError("preferências inválidas")
    p = preferencias()
    if "ligado" in novo:
        if not isinstance(novo["ligado"], bool):
            raise ValueError("ligado precisa ser verdadeiro ou falso")
        p["ligado"] = novo["ligado"]
    if "tipos" in novo:
        if not isinstance(novo["tipos"], dict) or not all(k in TIPOS and isinstance(v, bool) for k, v in novo["tipos"].items()):
            raise ValueError("tipos de aviso inválidos")
        p["tipos"].update(novo["tipos"])
    for k, (lo, hi) in (("repetir_minutos", (1, 1440)), ("parou_apos_minutos", (1, 600))):
        if k in novo:
            v = novo[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValueError(f"{k} inválido ({lo} a {hi})")
            p[k] = v
    if "nao_perturbe" in novo:
        n = novo["nao_perturbe"]
        if not isinstance(n, dict) or not isinstance(n.get("ligado", False), bool):
            raise ValueError("não perturbe inválido")
        for k in ("inicio", "fim"):
            if k in n and not _hora_valida(n[k]):
                raise ValueError("horário inválido (use HH:MM)")
        p["nao_perturbe"].update({k: n[k] for k in ("ligado", "inicio", "fim") if k in n})
    armazem.gravar_json(arquivo_prefs(), p)
    return p


def _minutos(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def em_nao_perturbe(prefs, agora=None):
    n = prefs.get("nao_perturbe") or {}
    if not n.get("ligado"):
        return False
    try:
        ini, fim = _minutos(n["inicio"]), _minutos(n["fim"])
    except (KeyError, ValueError):
        return False
    lt = time.localtime(agora or time.time())
    m = lt.tm_hour * 60 + lt.tm_min
    if ini == fim:
        return False
    return ini <= m < fim if ini < fim else (m >= ini or m < fim)        # janela que passa da meia-noite


# ---------------------------------------------------------------------------------------------------------------
# Execução (trocada por um falso nos testes)
# ---------------------------------------------------------------------------------------------------------------
VARIAVEIS_SEM_EFEITOS = ("CEREBRO_TESTE_HOME", "CEREBRO_SEM_AGENDADOR", "CEREBRO_SEM_EFEITOS")


def sem_efeitos():
    """Testes e CI (o ci_instalador define CEREBRO_SEM_AGENDADOR; CEREBRO_SEM_EFEITOS é o nome geral): nada roda de verdade."""
    return any(os.environ.get(v) for v in VARIAVEIS_SEM_EFEITOS)


def caminho_powershell():
    """O PowerShell do Windows por caminho absoluto, ou None. Nunca procura na pasta atual nem no PATH."""
    raiz = os.environ.get("SystemRoot") or os.environ.get("windir") or ""
    if not raiz or not os.path.isabs(raiz):
        return None
    exe = os.path.join(raiz, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return exe if os.path.isfile(exe) else None


def _executar_powershell(titulo, texto):
    """Mostra a notificação. Devolve True se o PowerShell terminou bem. TRAVA: dentro dos testes/CI nunca roda de verdade."""
    if sem_efeitos():
        return False
    exe = caminho_powershell()
    if not exe:
        return False
    env = dict(os.environ, CEREBRO_AVISO_TITULO=titulo, CEREBRO_AVISO_TEXTO=texto, CEREBRO_AVISO_APP=APP_ID)
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                            "-Command", SCRIPT_TOAST], env=env, capture_output=True, timeout=15, creationflags=0x08000000)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_executar = _executar_powershell
_eh_windows = os.name == "nt"
_em_segundo_plano = True       # os testes desligam para conferir na hora


def _registrar(item):
    _historico.append(item)
    try:
        armazem.anexar_jsonl(config.CASA / "avisos.jsonl", item)
    except OSError:
        pass


def avisar(titulo, texto, chave, tipo="geral", agora=None):
    """Mostra um aviso do Windows (ou só registra). Nunca levanta erro e nunca espera o PowerShell."""
    try:
        agora = agora or time.time()
        titulo, texto = encurtar(titulo, 80) or "Cérebro do Projeto", encurtar(texto, 240)
        prefs = preferencias()
        chave = str(chave or titulo)[:200]
        item = {"em": agora, "titulo": titulo, "texto": texto, "tipo": tipo, "chave": chave}
        if not prefs["ligado"] or not prefs["tipos"].get(tipo, True):
            item["resultado"] = "desligado"
        elif em_nao_perturbe(prefs, agora):
            item["resultado"] = "nao_perturbe"
        else:
            with _trava:
                ultimo = _ultimos.get(chave)
                if ultimo and agora - ultimo < prefs["repetir_minutos"] * 60:
                    item["resultado"] = "repetido"
                else:
                    _ultimos[chave] = agora
                    item["resultado"] = "mostrado" if _eh_windows else "sem_windows"
        _registrar(item)
        if item["resultado"] == "mostrado":
            if _em_segundo_plano:
                threading.Thread(target=_executar, args=(titulo, texto), daemon=True, name="cerebro-aviso").start()
            elif not _executar(titulo, texto):
                item["resultado"] = "falhou"
        return item["resultado"]
    except Exception as e:                   # aviso é cortesia: nunca derruba quem chamou
        print(f"Aviso não mostrado: {type(e).__name__}: {e}", flush=True)
        return "falhou"


def historico():
    return list(_historico)[::-1]


def zerar():
    """Só para os testes."""
    with _trava:
        _ultimos.clear()
        _historico.clear()
        _turnos_avisados.clear()


# ---------------------------------------------------------------------------------------------------------------
# Gatilhos ligados aos ganchos do Claude Code
# ---------------------------------------------------------------------------------------------------------------
def _nome_projeto(slug):
    from . import projetos
    try:
        p = projetos.achar(slug) if slug else None
    except Exception:
        p = None
    return p["nome"] if p else "Claude Code"


def _ao_subagente_terminar(ev):
    slug, sid = ev.get("slug"), ev.get("session_id")
    ges = ((config.ler_config().get("gestoras") or {}).get(slug) or {}).get("conversa", "")
    if not sid or sid != ges:
        return None
    avisar("Chegou item a conferir", f"{_nome_projeto(slug)}: um subagente ({ev.get('agent_type') or 'subagente'}) da gestora terminou.",
           f"sub:{ev.get('agent_id') or sid}", tipo="subagente_terminou")
    return None


def _ao_notificar(ev):
    msg = ev.get("message") or "O Claude Code está esperando você."
    avisar(ev.get("title") or "O Claude Code precisa de você", f"{_nome_projeto(ev.get('slug'))}: {msg}",
           f"notif:{ev.get('session_id')}:{ev.get('notification_type') or ''}", tipo="precisa_de_voce")
    return None


def _ao_parar(ev):
    from . import ganchos_eventos
    s = ganchos_eventos.sessao(ev.get("session_id")) or {}
    # o resumo da sessão já foi atualizado para "parado" com este Stop; o início do turno é o último UserPromptSubmit
    inicio = s.get("inicio_turno")
    marca = (ev.get("session_id"), inicio)
    if not inicio or marca in _turnos_avisados:
        return None
    minutos = (ev["em"] - inicio) / 60
    if minutos >= preferencias()["parou_apos_minutos"]:
        _turnos_avisados.append(marca)
        avisar("Sessão terminou o trabalho", f"{_nome_projeto(ev.get('slug'))}: parou depois de {int(minutos)} min. Sua vez.",
               f"stop:{ev.get('session_id')}:{int(inicio)}", tipo="sessao_parou")
    return None


def ligar_gatilhos():
    """Registra os gatilhos como ouvintes dos ganchos (pode chamar mais de uma vez: não duplica)."""
    from . import ganchos_eventos
    ganchos_eventos.registrar_ouvinte("SubagentStop", _ao_subagente_terminar)
    ganchos_eventos.registrar_ouvinte("Notification", _ao_notificar)
    ganchos_eventos.registrar_ouvinte("Stop", _ao_parar)
