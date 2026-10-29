r"""Ambiente de mentira para os testes: CEREBRO_HOME e CEREBRO_CLAUDE apontam para pastas temporárias.

Importe este módulo ANTES de qualquer módulo do pacote `cerebro` (as pastas são lidas na importação).
Nenhum teste lê ou escreve em ~/.cerebro ou ~/.claude de verdade; nenhum transcrito real é usado.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
if "CEREBRO_TESTE_HOME" not in os.environ:
    # fora de AppData\Local\Temp de propósito: a descoberta de projetos ignora pastas dentro dele
    _raiz_testes = Path.home() / ".cerebro-testes"
    _raiz_testes.mkdir(exist_ok=True)
    _base = Path(tempfile.mkdtemp(prefix="t_", dir=_raiz_testes))
    os.environ["CEREBRO_TESTE_HOME"] = str(_base)
    os.environ["CEREBRO_HOME"] = str(_base / "casa")
    os.environ["CEREBRO_CLAUDE"] = str(_base / "claude")
    os.environ["CEREBRO_BACKUP"] = str(_base / "backup")          # pasta do backup (backup.py): nunca a de verdade
BASE = Path(os.environ["CEREBRO_TESTE_HOME"])
os.environ.setdefault("CEREBRO_BACKUP", str(BASE / "backup"))
RAIZ_TESTES = Path.home() / ".cerebro-testes"
CASA = Path(os.environ["CEREBRO_HOME"])
CLAUDE = Path(os.environ["CEREBRO_CLAUDE"])
BACKUP = Path(os.environ["CEREBRO_BACKUP"])
# settings.json do Claude Code (instalador dos ganchos/statusLine): sempre um arquivo de mentira dentro da pasta de testes
os.environ.setdefault("CEREBRO_CLAUDE_SETTINGS", str(BASE / "claude" / "settings.json"))


def garantir_isolamento():
    """TRAVA DE SEGURANÇA: se o Cérebro foi importado antes deste módulo, as pastas dele podem ser as REAIS (.cerebro e .claude do
    dono) e qualquer teste que apague pastas destruiria conversas e memória. Aborta antes de apagar qualquer coisa."""
    from cerebro import config
    try:
        BASE.resolve().relative_to(RAIZ_TESTES.resolve())
    except ValueError:
        raise RuntimeError(f"ISOLAMENTO FALHOU: a pasta de testes {BASE} não está dentro de {RAIZ_TESTES}.") from None
    for nome, pasta in (("CASA", config.CASA), ("PROJETOS_CLAUDE", config.PROJETOS_CLAUDE),
                        ("CEREBRO_CLAUDE_SETTINGS", os.environ.get("CEREBRO_CLAUDE_SETTINGS") or "")):
        try:
            Path(pasta).resolve().relative_to(BASE.resolve())
        except ValueError:
            raise RuntimeError(f"ISOLAMENTO FALHOU: config.{nome} = {pasta} está fora da pasta de testes {BASE}. "
                               "Importe 'testes' (ou testes._ambiente) antes de qualquer módulo do cerebro.") from None
    from cerebro import agendador, backup
    try:
        backup.pasta_backup().resolve().relative_to(BASE.resolve())
    except ValueError:
        raise RuntimeError(f"ISOLAMENTO FALHOU: a pasta de backup {backup.pasta_backup()} está fora da pasta de testes {BASE}.") from None
    if not isinstance(agendador.EXECUTAR, AgendadorFalso):
        agendador.EXECUTAR = AgendadorFalso()     # o Agendador de Tarefas REAL nunca é chamado nos testes


class _Resposta:
    def __init__(self, codigo=0, saida="", erro=""):
        self.returncode, self.stdout, self.stderr = codigo, saida, erro


class AgendadorFalso:
    """schtasks de mentira: guarda as tarefas num dicionário e as chamadas numa lista. Nunca toca o Agendador real."""

    def __init__(self):
        self.tarefas = {}          # nome sem a barra inicial -> xml
        self.chamadas = []
        self.falhar = False

    def __call__(self, argv, **_kw):
        self.chamadas.append(list(argv))
        # só o schtasks pelo caminho completo (%SystemRoot%\System32\schtasks.exe): nome solto acharia um .exe plantado na pasta atual
        if not (Path(argv[0]).is_absolute() and Path(argv[0]).name.lower() == "schtasks.exe"):
            raise RuntimeError(f"comando inesperado no Agendador falso: {argv!r}")
        if self.falhar:
            return _Resposta(1, "", "ERRO: falso")
        args = [a.upper() if a.startswith("/") else a for a in argv[1:]]
        tn = argv[argv.index("/TN") + 1].lstrip("\\") if "/TN" in argv else None
        if args[0] == "/CREATE":
            xml = argv[argv.index("/XML") + 1]
            self.tarefas[tn] = Path(xml).read_text(encoding="utf-16")
            return _Resposta(0, "ÊXITO: tarefa criada")
        if args[0] == "/DELETE":
            if tn in self.tarefas:
                del self.tarefas[tn]
                return _Resposta(0, "ÊXITO")
            return _Resposta(1, "", "ERRO: não encontrada")
        if args[0] == "/QUERY":
            if tn is not None:
                if tn not in self.tarefas:
                    return _Resposta(1, "", "ERRO: não encontrada")
                if "/XML" in args:
                    return _Resposta(0, self.tarefas[tn])
                return _Resposta(0, f'"PC","\\{tn}","30/10/2026 12:30:00","Pronto","Interativo","N/A","267011","eu"\n')
            return _Resposta(0, "".join(f'"\\{n}","30/10/2026 12:30:00","Pronto"\n' for n in self.tarefas)
                             + '"\\Microsoft\\Outra","N/A","Pronto"\n')
        return _Resposta(1, "", "ERRO: argumento desconhecido")


garantir_isolamento()
from cerebro import config as _config  # noqa: E402
print("[testes] config.CASA =", _config.CASA, file=sys.stderr, flush=True)
print("[testes] config.PROJETOS_CLAUDE =", _config.PROJETOS_CLAUDE, file=sys.stderr, flush=True)
print("[testes] pasta do backup =", BACKUP, file=sys.stderr, flush=True)


class ApagarRecusado(Exception):
    """Tentativa de apagar algo fora da pasta temporária dos testes."""


def _liberar_e_repetir(funcao, caminho, _info):
    """Windows: arquivos do .git são somente leitura e o rmtree desiste deles. Libera e tenta de novo (o caminho já foi conferido)."""
    try:
        os.chmod(caminho, 0o700)
        funcao(caminho)
    except OSError:
        pass


def apagar(caminho, base=None):
    """ÚNICO jeito de apagar nos testes (e no atexit). Resolve o caminho (links e junções incluídos) e só apaga se estiver
    estritamente DENTRO de BASE; fora disso levanta ApagarRecusado e não apaga nada. Aceita arquivo ou pasta; ausente = nada a fazer."""
    base = Path(base if base is not None else BASE).resolve()
    bruto = Path(os.path.abspath(str(caminho)))
    alvo, pai = bruto.resolve(), bruto.parent.resolve()
    for p in (alvo, pai):
        try:
            p.relative_to(base)
        except ValueError:
            raise ApagarRecusado(f"recusado: {caminho} está fora de {base}") from None
    if alvo == base:
        raise ApagarRecusado(f"recusado: não apago a própria pasta base {base}")
    if alvo.is_dir() and not bruto.is_symlink():
        shutil.rmtree(alvo, onerror=_liberar_e_repetir)
    else:
        alvo.unlink(missing_ok=True)


def _apagar_base_no_fim():
    try:
        if BASE.parent.resolve() == RAIZ_TESTES.resolve():           # só a pasta t_xxxx criada por este processo
            shutil.rmtree(BASE.resolve(), onerror=_liberar_e_repetir)
    except OSError:
        pass


atexit.register(_apagar_base_no_fim)


def reiniciar_memoria():
    """Esquece os índices guardados em memória (por slug) entre um teste e outro: o mesmo slug 'Falso' é reaproveitado."""
    from cerebro import indice
    indice._estados.clear()


def linha_assistente(mid, modelo="claude-opus-5-5", ts="2026-10-28T12:00:00.000Z", entrada=10, saida=20, leitura=1000,
                     escrita=0, w1=0, conteudo=None, cwd="C:/Projetos/Falso"):
    """Uma linha sintética no formato (tolerante) dos transcritos do Claude Code."""
    uso = {"input_tokens": entrada, "output_tokens": saida, "cache_read_input_tokens": leitura,
           "cache_creation_input_tokens": escrita, "cache_creation": {"ephemeral_5m_input_tokens": escrita - w1, "ephemeral_1h_input_tokens": w1}}
    return json.dumps({"parentUuid": None, "isSidechain": False, "type": "assistant", "uuid": "u-" + mid, "timestamp": ts, "cwd": cwd,
                       "gitBranch": "main", "version": "9.9.9", "sessionId": "s1",
                       "message": {"id": mid, "model": modelo, "role": "assistant", "usage": uso,
                                   "content": conteudo or [{"type": "text", "text": "oi"}]}}, separators=(",", ":")) + "\n"


def linha_usuario(texto, ts="2026-10-28T11:59:00.000Z"):
    return json.dumps({"type": "user", "timestamp": ts, "uuid": "x", "message": {"role": "user", "content": texto}}, separators=(",", ":")) + "\n"


SLUG_EXEMPLO = "C--Users-ana-Projetos-Loja"          # slug inventado: nenhum teste usa nome ou caminho de gente de verdade
GESTORA_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class MundoFalso:
    """Mixin de teste: projeto de mentira (pasta + conversa gestora + subagentes) dentro da pasta temporária.

    Uso: herdar junto com unittest.TestCase e chamar self.montar_mundo() no setUp.
    """

    def montar_mundo(self, nome="Falso"):
        from cerebro import config, projetos
        garantir_isolamento()
        apagar(config.PROJETOS_CLAUDE)
        apagar(BASE / "mundo")
        apagar(CASA / "projetos")
        reiniciar_memoria()
        for f in ("config.json", "novidades.json"):
            apagar(CASA / f)
        self.real = BASE / "mundo" / "Desktop" / nome
        self.real.mkdir(parents=True)
        self.slug = projetos.codificar(self.real)
        self.pasta_claude = config.PROJETOS_CLAUDE / self.slug
        self.pasta_claude.mkdir(parents=True)
        self.salvo_home = projetos.HOME
        projetos.HOME = BASE / "mundo"
        (self.pasta_claude / f"{GESTORA_ID}.jsonl").write_text(
            json.dumps({"type": "user", "cwd": str(self.real)}) + "\n" + linha_usuario("Gerencie") + linha_assistente("g1"), encoding="utf-8")
        projetos.descobrir(forcar=True)
        config.atualizar_config(lambda c: c["gestoras"].__setitem__(self.slug, {"conversa": GESTORA_ID, "nome": "Gestora de teste"}))
        self.cfg = config.ler_config()

    def desmontar_mundo(self):
        from cerebro import projetos
        projetos.HOME = self.salvo_home
        projetos.descobrir(forcar=True)

    def criar_subagente(self, id_, descricao, modelo="claude-haiku-5-5", terminou=True, idade_s=7200, tipo="general-purpose"):
        """Cria agent-<id>.jsonl + .meta.json na sessão gestora. 'idade_s' = há quanto tempo foi escrito (muda o mtime)."""
        import os
        import time
        pasta = self.pasta_claude / GESTORA_ID / "subagents"
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / f"agent-{id_}.jsonl"
        arq.write_text(linha_usuario(descricao) + linha_assistente("m-" + id_, modelo=modelo), encoding="utf-8")
        meta = {"agentType": tipo, "description": descricao, "spawnDepth": 1}
        if terminou:
            meta["finished"] = True
        (pasta / f"agent-{id_}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        t = time.time() - idade_s
        os.utime(arq, (t, t))
        return arq
