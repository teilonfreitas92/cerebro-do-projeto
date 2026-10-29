r"""Rotinas que rodam sozinhas no Windows: tarefas do Agendador de Tarefas criadas, consultadas e removidas pelo Cérebro.

Regras (de segurança):
  * Só mexe em tarefas com nome "CerebroDoProjeto\<rotina>" (pasta própria no Agendador). Nunca cria, consulta ou remove
    tarefa fora desse prefixo: o nome é montado aqui a partir de uma lista fechada de rotinas e conferido de novo antes de
    qualquer comando.
  * Usuário atual, SEM senha (LogonType InteractiveToken: roda quando você está conectado) e SEM privilégio elevado
    (RunLevel LeastPrivilege).
  * Roda o pythonw (sem janela) da .venv do Cérebro, se existir (ver instalar.py), senão o pythonw ao lado do Python atual,
    com "cerebro_cli.py rotina <nome>".
  * schtasks sempre com argumentos em LISTA (sem shell), tempo limite e sem janela (CREATE_NO_WINDOW).

Por que XML (/XML) e não só argumentos do schtasks: os argumentos do schtasks não ligam "StartWhenAvailable" (rodar assim
que der, se o PC estava desligado no horário), "não parar na bateria", "uma execução por vez", o limite de tempo nem o
gatilho "ao fazer logon" junto do diário na MESMA tarefa. O XML é gerado aqui (valores escapados), gravado em
~/.cerebro/rotinas/<rotina>.xml (UTF-16, como o schtasks exige) e passado com /XML; o nome vai em /TN.

Os testes trocam EXECUTAR por um Agendador falso (testes/_ambiente.py); a função de verdade se recusa a rodar quando
CEREBRO_TESTE_HOME está definido (trava dupla: teste nunca toca o Agendador real). Também se recusa com CEREBRO_SEM_AGENDADOR=1
(a prova do instalador, testes/ci_instalador.py, define) e quando CEREBRO_HOME aponta para outra pasta que não ~/.cerebro (uma
2ª cópia, a demonstração ou a prova: as tarefas do Agendador são do PC inteiro e rodariam com os dados da casa principal).
O schtasks é chamado pelo caminho completo (%SystemRoot%\System32\schtasks.exe), nunca pelo nome solto: um schtasks.exe
plantado na pasta atual não roda. O desinstalador só remove tarefa cujo XML aponta para o cerebro_cli.py DESTA instalação.
"""
import csv
import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import config

PASTA = "CerebroDoProjeto"
PREFIXO = PASTA + "\\"
ROTINAS = ("backup", "analise", "novidades", "mapa")
NOME_VALIDO = re.compile(r"^\\?CerebroDoProjeto\\(backup|analise|novidades|mapa)$")
RAIZ = Path(__file__).resolve().parent.parent
CLI = RAIZ / "cerebro_cli.py"
SEM_JANELA = 0x08000000

DESCRICOES = {
    "backup": "Cérebro do Projeto: cópia de segurança diária das conversas e da memória do Claude Code",
    "analise": "Cérebro do Projeto: análise sem IA dos projetos visíveis (só propõe)",
    "novidades": "Cérebro do Projeto: procura novidades das ferramentas (só leitura na internet)",
    "mapa": "Cérebro do Projeto: refaz a página do mapa dos projetos que já têm graph.json (sem IA)",
}
# Padrões de cada rotina no Windows (config.json > rotinas_windows): horário e intervalo.
PADROES = {
    "backup": {"hora": "12:30"},                  # todo dia + ao fazer logon (pula se o de hoje já existe)
    "analise": {"hora": "13:00", "dias": 7},
    "novidades": {"hora": "13:10", "dias": 3},
    "mapa": {"hora": "09:00", "horas": 6},        # a cada N horas
}


class AgendadorErro(Exception):
    """O Agendador recusou ou o pedido está fora do permitido."""


def disponivel():
    return os.name == "nt"


def nome_tarefa(rotina):
    if rotina not in ROTINAS:
        raise AgendadorErro(f"rotina desconhecida: {rotina!r} (use {', '.join(ROTINAS)})")
    nome = PREFIXO + rotina
    _conferir_nome(nome)
    return nome


def _conferir_nome(nome):
    """Trava: nenhum comando sai daqui com um nome fora de CerebroDoProjeto\\<rotina conhecida>."""
    if not NOME_VALIDO.match(nome or ""):
        raise AgendadorErro(f"recusado: {nome!r} não é uma tarefa do Cérebro")
    return nome


def caminho_schtasks():
    """%SystemRoot%\\System32\\schtasks.exe (caminho completo). SystemRoot ausente ou relativo: C:\\Windows."""
    raiz = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    if not raiz or not Path(raiz).is_absolute():
        raiz = r"C:\Windows"
    return str(Path(raiz) / "System32" / "schtasks.exe")


def motivo_sem_agendador():
    """Por que o Agendador REAL não pode ser usado neste processo (None = pode). Travas: testes, demonstração,
    CEREBRO_SEM_AGENDADOR e CEREBRO_HOME diferente de ~/.cerebro (outra cópia/prova: a tarefa é do PC inteiro)."""
    if os.environ.get("CEREBRO_TESTE_HOME"):
        return "os testes não podem usar o Agendador de Tarefas real"
    if os.environ.get("CEREBRO_DEMO"):
        return "na demonstração o Agendador do Windows não é usado (a tarefa rodaria com os seus dados de verdade)"
    if os.environ.get("CEREBRO_SEM_AGENDADOR", "").strip() not in ("", "0"):
        return "o Agendador do Windows está desligado aqui (CEREBRO_SEM_AGENDADOR)"
    casa = os.environ.get("CEREBRO_HOME")
    if casa:
        try:
            outra = Path(casa).resolve() != (Path.home() / ".cerebro").resolve()
        except OSError:
            outra = True
        if outra:
            return ("esta cópia do Cérebro usa outra pasta de dados (CEREBRO_HOME): o Agendador do Windows só é usado pela "
                    "instalação principal (~/.cerebro)")
    return None


def _executar_de_verdade(argv, timeout=30):
    motivo = motivo_sem_agendador()
    if motivo:
        raise AgendadorErro(motivo)
    if not disponivel():
        raise AgendadorErro("o agendamento só existe no Windows")
    if not Path(argv[0]).is_absolute():
        raise AgendadorErro(f"recusado: {argv[0]!r} não é um caminho completo")
    return subprocess.run(argv, capture_output=True, text=True, encoding="oem", errors="replace", timeout=timeout,
                          creationflags=SEM_JANELA, stdin=subprocess.DEVNULL)


EXECUTAR = _executar_de_verdade


def _schtasks(*args):
    """Roda o schtasks (caminho completo) com argumentos em lista. Confere que todo /TN vai com nome do prefixo."""
    argv = [caminho_schtasks(), *args]
    for i, a in enumerate(argv[:-1]):
        if a.upper() == "/TN":
            _conferir_nome(argv[i + 1])
    try:
        return EXECUTAR(argv, timeout=30)
    except subprocess.TimeoutExpired:
        raise AgendadorErro("o Agendador de Tarefas não respondeu a tempo") from None
    except OSError as e:
        raise AgendadorErro(f"não consegui chamar o schtasks: {e}") from None


def python_das_rotinas(raiz=RAIZ):
    """pythonw da .venv do Cérebro (sem janela) > pythonw ao lado do Python atual > o Python atual."""
    venv = Path(raiz) / ".venv" / "Scripts" / "pythonw.exe"
    if venv.is_file():
        return venv
    ao_lado = Path(sys.executable).with_name("pythonw.exe")
    return ao_lado if ao_lado.is_file() else Path(sys.executable)


def _usuario():
    dom, usu = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{dom}\\{usu}" if dom and usu else usu


def parametros(rotina, cfg=None):
    cfg = cfg if cfg is not None else config.ler_config()
    p = dict(PADROES[rotina])
    gravado = ((cfg.get("rotinas_windows") or {}).get(rotina) or {})
    p.update({k: v for k, v in gravado.items() if k in p})
    return p


def validar_parametros(rotina, p):
    """Confere horário (HH:MM) e intervalos. Devolve o dicionário limpo ou levanta ValueError."""
    limpo = {}
    hora = str(p.get("hora", PADROES[rotina]["hora"]))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
        raise ValueError("horário inválido (use HH:MM, por exemplo 12:30)")
    limpo["hora"] = hora
    if "dias" in PADROES[rotina]:
        v = p.get("dias", PADROES[rotina]["dias"])
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 365:
            raise ValueError("intervalo inválido (1 a 365 dias)")
        limpo["dias"] = v
    if "horas" in PADROES[rotina]:
        v = p.get("horas", PADROES[rotina]["horas"])
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 23:
            raise ValueError("intervalo inválido (1 a 23 horas)")
        limpo["horas"] = v
    return limpo


def montar_xml(rotina, p, python=None, cli=CLI, usuario=None, agora=None):
    """XML da tarefa (Task Scheduler 1.2). Valores escapados; nada vem de fora além do horário/intervalo já validados."""
    p = validar_parametros(rotina, p)
    agora = agora or time.time()
    inicio = time.strftime("%Y-%m-%d", time.localtime(agora)) + f"T{p['hora']}:00"
    usuario = _usuario() if usuario is None else usuario
    python = str(python or python_das_rotinas())
    tag_usuario = f"<UserId>{escape(usuario)}</UserId>" if usuario else ""
    repeticao = ""
    if "horas" in p:
        repeticao = (f"<Repetition><Interval>PT{p['horas']}H</Interval><Duration>P1D</Duration>"
                     "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>")
    gatilhos = (f"<CalendarTrigger>{repeticao}<StartBoundary>{inicio}</StartBoundary><Enabled>true</Enabled>"
                f"<ScheduleByDay><DaysInterval>{p.get('dias', 1)}</DaysInterval></ScheduleByDay></CalendarTrigger>")
    if rotina == "backup":     # PC desligado no horário: StartWhenAvailable cobre; o logon é a segunda chance (a rotina pula se já fez hoje)
        gatilhos += f"<LogonTrigger><Enabled>true</Enabled>{tag_usuario}<Delay>PT5M</Delay></LogonTrigger>"
    limite = "PT2H" if rotina in ("backup", "analise") else "PT30M"
    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f"<RegistrationInfo><Author>Cérebro do Projeto</Author><Description>{escape(DESCRICOES[rotina])}</Description></RegistrationInfo>"
            f"<Triggers>{gatilhos}</Triggers>"
            f'<Principals><Principal id="Author">{tag_usuario}<LogonType>InteractiveToken</LogonType>'
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
            "<AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>"
            "<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>"
            "<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>"
            "<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>"
            f"<RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>{limite}</ExecutionTimeLimit>"
            "<Priority>7</Priority></Settings>"
            f'<Actions Context="Author"><Exec><Command>{escape(python)}</Command>'
            f"<Arguments>{escape(chr(34) + str(cli) + chr(34) + ' rotina ' + rotina)}</Arguments>"
            f"<WorkingDirectory>{escape(str(Path(cli).parent))}</WorkingDirectory></Exec></Actions></Task>")


def ligar(rotina, p=None):
    """Cria (ou atualiza) a tarefa da rotina. Devolve o estado. Chamado pelo clique em "Ligar no Windows" ou pela CLI."""
    nome = nome_tarefa(rotina)
    p = validar_parametros(rotina, p if p is not None else parametros(rotina))
    pasta = Path(config.CASA) / "rotinas"
    pasta.mkdir(parents=True, exist_ok=True)
    xml = pasta / f"{rotina}.xml"
    xml.write_text(montar_xml(rotina, p), encoding="utf-16")
    r = _schtasks("/Create", "/TN", nome, "/XML", str(xml), "/F")
    if r.returncode != 0:
        raise AgendadorErro("o Agendador recusou a tarefa: " + ((r.stderr or "") + (r.stdout or "")).strip()[:300])
    config.atualizar_config(lambda c: c.setdefault("rotinas_windows", {}).__setitem__(rotina, p))
    return estado(rotina)


def desligar(rotina):
    """Remove a tarefa da rotina (só a do prefixo). Tarefa que não existe = nada a fazer."""
    nome = nome_tarefa(rotina)
    if not estado(rotina)["ligada"]:
        return False
    r = _schtasks("/Delete", "/TN", nome, "/F")
    if r.returncode != 0:
        raise AgendadorErro("o Agendador não removeu a tarefa: " + ((r.stderr or "") + (r.stdout or "")).strip()[:300])
    return True


def _linhas_csv(texto):
    try:
        return [l for l in csv.reader(io.StringIO(texto or "")) if l]
    except csv.Error:
        return []


def estado(rotina):
    """ligada?, próxima execução e último resultado SEGUNDO o Agendador (texto como o Windows escreve, no idioma dele)."""
    nome = nome_tarefa(rotina)
    base = {"rotina": rotina, "tarefa": nome, "disponivel": disponivel(), "ligada": False, "proxima": "", "ultima": "", "resultado": "", "situacao": ""}
    if not disponivel():
        return base
    try:
        r = _schtasks("/Query", "/TN", nome, "/FO", "CSV", "/V", "/NH")
    except AgendadorErro as e:
        return {**base, "erro": str(e)}
    if r.returncode != 0:
        return base
    for l in _linhas_csv(r.stdout):
        # colunas fixas do /V (qualquer idioma): 0 host, 1 nome, 2 próxima execução, 3 status, 4 modo de logon,
        # 5 última execução, 6 último resultado
        if len(l) > 6 and l[1].strip("\\").lower() == nome.lower():
            return {**base, "ligada": True, "proxima": l[2], "situacao": l[3], "ultima": l[5], "resultado": l[6]}
    return base


def listar_do_prefixo():
    """Nomes das tarefas que existem na pasta CerebroDoProjeto (para o desinstalador). Nunca devolve tarefa de fora."""
    if not disponivel():
        return []
    r = _schtasks("/Query", "/FO", "CSV", "/NH")
    if r.returncode != 0:
        return []
    achadas = []
    for l in _linhas_csv(r.stdout):
        nome = l[0].strip() if l else ""
        if NOME_VALIDO.match(nome) and nome.lstrip("\\") not in achadas:
            achadas.append(nome.lstrip("\\"))
    return achadas


def _normalizar(caminho):
    return os.path.normcase(os.path.normpath(str(caminho).strip().strip('"')))


def aponta_para_esta(rotina, cli=CLI):
    """A tarefa da rotina roda o cerebro_cli.py DESTA instalação? Lê o XML da tarefa (schtasks /Query /XML) e compara o caminho
    em <Arguments>. Tarefa ausente, XML ilegível ou de outra cópia do Cérebro: False (o desinstalador não mexe nela)."""
    nome = nome_tarefa(rotina)
    try:
        r = _schtasks("/Query", "/TN", nome, "/XML")
    except AgendadorErro:
        return False
    if r.returncode != 0:
        return False
    m = re.search(r"<Arguments>\s*&quot;(.*?)&quot;|<Arguments>\s*\"(.*?)\"", r.stdout or "", re.S)
    if not m:
        return False
    return _normalizar(m.group(1) or m.group(2)) == _normalizar(cli)


def remover_todas(cli=CLI):
    """Desinstalar: remove só as tarefas do prefixo QUE APONTAM PARA ESTA instalação (o XML roda o cerebro_cli.py desta pasta).
    Tarefas de outra cópia do Cérebro ficam (desinstalar uma cópia de teste não desliga o backup da principal).
    Devolve as removidas; as que ficaram por serem de outra cópia saem em outras_copias(...)."""
    removidas = []
    for nome in listar_do_prefixo():
        rotina = nome.split("\\")[-1]
        if rotina in ROTINAS and aponta_para_esta(rotina, cli) and desligar(rotina):
            removidas.append(nome)
    return removidas


def outras_copias(cli=CLI):
    """Tarefas do prefixo que NÃO apontam para esta instalação (para o desinstalador explicar por que ficaram)."""
    return [n for n in listar_do_prefixo() if n.split("\\")[-1] in ROTINAS and not aponta_para_esta(n.split("\\")[-1], cli)]
