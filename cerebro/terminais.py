"""Terminais de verdade no painel: o Cérebro abre o Claude Code (`claude`) num pseudo-terminal e a página mostra e digita nele
por WebSocket (xterm.js), como se fosse o cmd. Você aprova, interrompe (Esc) e conversa ali mesmo.

Regras:
  * só roda o `claude` (sessão nova ou `--resume <id da sessão>`), na pasta do projeto; nada de shell livre;
  * no máximo LIMITE terminais abertos; cada um guarda o final da tela (CAUDA) para quem conectar depois;
  * uma sessão aberta no app do Claude ao mesmo tempo briga com o terminal: a rota avisa antes (sessao_em_uso);
  * no Windows usa o ConPTY pelo pywinpty; no Linux e no macOS, o pty da biblioteca padrão.
"""
import codecs
import os
import re
import secrets
import shutil
import subprocess
import threading
import time

LIMITE = 8
CAUDA = 400_000                  # caracteres guardados de cada tela (para quem conecta depois ou recarrega a página)
ID_TERMINAL = re.compile(r"^[0-9a-f]{12}$")
ID_SESSAO = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
JANELA_EM_USO = 120              # sessão escrita há menos que isto (fora do Cérebro) conta como aberta em outro lugar
ENV_FORA = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")   # o claude acharia que está dentro de outro claude


class ErroTerminal(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------
# Pseudo-terminal (Windows: ConPTY pelo pywinpty; outros: pty)
# ---------------------------------------------------------------------------------------------------------------
class _PtyWindows:
    def __init__(self, argv, cwd, env, cols, rows):
        try:
            from winpty import PtyProcess
        except ImportError as e:
            raise ErroTerminal("falta o pywinpty (rode o instalar.py de novo ou: pip install pywinpty)") from e
        self.p = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))
        self.pid = self.p.pid

    def ler(self):
        """Texto que chegou (bloqueia); '' quando o processo terminou."""
        try:
            return self.p.read(8192)
        except EOFError:
            return ""

    def escrever(self, texto):
        self.p.write(texto)

    def tamanho(self, cols, rows):
        self.p.setwinsize(rows, cols)

    def vivo(self):
        return self.p.isalive()

    def matar(self):
        try:
            self.p.terminate(force=True)
        except Exception:
            pass


class _PtyPosix:
    def __init__(self, argv, cwd, env, cols, rows):
        import pty
        mestre, escravo = pty.openpty()
        self._tamanho_fd(escravo, cols, rows)
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=escravo, stdout=escravo, stderr=escravo,
                                     start_new_session=True, close_fds=True)
        os.close(escravo)
        self.fd, self.pid = mestre, self.proc.pid
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")

    @staticmethod
    def _tamanho_fd(fd, cols, rows):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def ler(self):
        try:
            b = os.read(self.fd, 8192)
        except OSError:
            b = b""
        return self.dec.decode(b) if b else ""

    def escrever(self, texto):
        os.write(self.fd, texto.encode("utf-8"))

    def tamanho(self, cols, rows):
        self._tamanho_fd(self.fd, cols, rows)

    def vivo(self):
        return self.proc.poll() is None

    def matar(self):
        try:
            os.killpg(self.proc.pid, 15)
        except OSError:
            pass
        try:
            self.proc.wait(3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, 9)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def abrir_pty(argv, cwd, env, cols=120, rows=32):
    return (_PtyWindows if os.name == "nt" else _PtyPosix)(argv, cwd, env, cols, rows)


# ---------------------------------------------------------------------------------------------------------------
# Terminais abertos
# ---------------------------------------------------------------------------------------------------------------
class Terminal:
    def __init__(self, slug, sessao, pty, titulo):
        self.id = secrets.token_hex(6)
        self.slug, self.sessao, self.pty, self.titulo = slug, sessao, pty, titulo
        self.criado = self.ultimo = time.time()
        self.fim = None
        self._cauda, self._tam = [], 0
        self._ouvintes = set()                   # funções chamadas (na thread de leitura) com cada pedaço; None = terminou
        self._trava = threading.Lock()

    def _receber(self, texto):
        with self._trava:
            self.ultimo = time.time()
            self._cauda.append(texto)
            self._tam += len(texto)
            while self._tam > CAUDA and len(self._cauda) > 1:
                self._tam -= len(self._cauda.pop(0))
            ouvintes = list(self._ouvintes)
        for f in ouvintes:
            f(texto)

    def _terminou(self):
        with self._trava:
            self.fim = time.time()
            ouvintes = list(self._ouvintes)
        for f in ouvintes:
            f(None)

    def assinar(self, f):
        """Começa a receber; devolve o que já está na tela (tudo atômico: nada se perde entre a cauda e o primeiro pedaço)."""
        with self._trava:
            self._ouvintes.add(f)
            return "".join(self._cauda)

    def desassinar(self, f):
        with self._trava:
            self._ouvintes.discard(f)

    def ler_continuo(self):
        while True:
            texto = self.pty.ler()
            if not texto:
                if not self.pty.vivo():
                    break
                time.sleep(0.05)
                continue
            self._receber(texto)
        self._terminou()

    def resumo(self):
        return {"id": self.id, "slug": self.slug, "sessao": self.sessao, "titulo": self.titulo, "criado": self.criado,
                "ultimo": self.ultimo, "vivo": self.fim is None, "fim": self.fim, "pid": self.pty.pid,
                "conectados": len(self._ouvintes)}


_terminais = {}
_trava = threading.Lock()


def _ambiente():
    env = {k: v for k, v in os.environ.items() if k not in ENV_FORA}
    env.update(TERM="xterm-256color", COLORTERM="truecolor")
    return env


def comando_claude(sessao=None):
    exe = shutil.which("claude")
    if not exe:
        raise ErroTerminal("não achei o Claude Code (comando claude) neste PC")
    if sessao is not None and not ID_SESSAO.match(sessao):
        raise ErroTerminal("id de sessão inválido")
    return [exe] + (["--resume", sessao] if sessao else [])


def abrir(slug, pasta, sessao=None, titulo="", cols=120, rows=32, criar_pty=None):
    """Abre o claude na pasta do projeto (sessão nova, ou retomando 'sessao'). A mesma sessão já aberta aqui é reaproveitada."""
    if not os.path.isdir(pasta):
        raise ErroTerminal("a pasta do projeto não existe")
    cols, rows = max(20, min(int(cols), 400)), max(5, min(int(rows), 200))
    with _trava:
        if sessao:
            for t in _terminais.values():
                if t.sessao == sessao and t.fim is None:
                    return t
        if sum(1 for t in _terminais.values() if t.fim is None) >= LIMITE:
            raise ErroTerminal(f"já há {LIMITE} terminais abertos; feche um antes")
        argv = comando_claude(sessao)
        pty = (criar_pty or abrir_pty)(argv, pasta, _ambiente(), cols, rows)
        t = Terminal(slug, sessao, pty, (titulo or ("retomando " + sessao[:8] if sessao else "sessão nova"))[:120])
        _terminais[t.id] = t
    threading.Thread(target=t.ler_continuo, name="terminal-" + t.id, daemon=True).start()
    return t


def achar(tid):
    if not ID_TERMINAL.match(tid or ""):
        return None
    with _trava:
        return _terminais.get(tid)


def listar(slug=None):
    with _trava:
        lista = [t.resumo() for t in _terminais.values() if slug is None or t.slug == slug]
    return sorted(lista, key=lambda r: r["criado"])


def sessoes_abertas_aqui():
    with _trava:
        return {t.sessao for t in _terminais.values() if t.sessao and t.fim is None}


def fechar(tid):
    """Encerra o claude (se ainda roda) e tira o terminal da lista."""
    with _trava:
        t = _terminais.pop(tid, None)
    if t is None:
        return False
    t.pty.matar()
    return True


def ativos():
    with _trava:
        return sum(1 for t in _terminais.values() if t.fim is None)


def parar_todos():
    with _trava:
        ids = list(_terminais)
    for tid in ids:
        fechar(tid)


def sessao_em_uso(slug, sessao, abertas=None, mtime=None, agora=None):
    """A sessão parece aberta fora do Cérebro (no app do Claude ou noutro terminal)? Devolve o motivo ou ''.
    'abertas' = ids do `claude agents --json`; 'mtime' = última escrita do transcrito."""
    if sessao in sessoes_abertas_aqui():
        return ""
    if abertas and sessao in abertas:
        return "a sessão está aberta no Claude Code agora"
    if mtime and (agora or time.time()) - mtime < JANELA_EM_USO:
        return "a sessão escreveu há menos de 2 minutos"
    return ""


def python_ok():
    """O pseudo-terminal funciona aqui? (no Windows precisa do pywinpty)"""
    if os.name != "nt":
        return True
    try:
        import winpty  # noqa: F401
        return True
    except ImportError:
        return False
