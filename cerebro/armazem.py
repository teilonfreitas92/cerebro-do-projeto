"""Gravação segura dos arquivos de dados do Cérebro (JSON e JSONL em ~/.cerebro).

O servidor e a linha de comando (cerebro_cli.py) podem escrever no mesmo arquivo ao mesmo tempo, então toda mudança
passa por `atualizar_json`: trava (dentro do processo e entre processos), lê, muda, grava num arquivo temporário e troca.
Leitura tolerante: arquivo ausente ou quebrado devolve o valor padrão e nunca derruba nada.
"""
import copy
import json
import os
import threading
import time
import uuid
from pathlib import Path

from . import config

_travas = {}
_trava_geral = threading.Lock()


def _trava_do(caminho):
    with _trava_geral:
        return _travas.setdefault(str(caminho), threading.RLock())


class _TravaDeArquivo:
    """Trava entre processos: cria <arquivo>.lock de forma exclusiva, com uma marca só desta instância dentro. Trava velha
    (mais de 20 s) é descartada. Respeita o prazo 'espera' (passou dele, segue sem a trava e NÃO apaga a dos outros) e o
    __exit__ só remove a trava se a marca for a nossa."""

    def __init__(self, caminho, espera=8.0):
        self.lock = Path(str(caminho) + ".lock")
        self.espera = espera
        self.marca = f"{os.getpid()}-{uuid.uuid4().hex}"
        self.minha = False

    def _ler_marca(self):
        try:
            return self.lock.read_text(encoding="ascii", errors="replace")
        except OSError:
            return None

    def __enter__(self):
        fim = time.monotonic() + self.espera
        while True:
            try:
                fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, self.marca.encode("ascii"))
                finally:
                    os.close(fd)
                self.minha = True
                return self
            except FileExistsError:
                try:
                    velha = time.time() - self.lock.stat().st_mtime > 20
                except OSError:
                    velha = False                     # sumiu entre uma olhada e outra: a próxima volta cria
                if velha:
                    antes = self._ler_marca()
                    if antes is not None and self._ler_marca() == antes:      # ninguém trocou a trava nesse meio tempo
                        try:
                            config.remover(self.lock)
                        except (OSError, config.RemocaoRecusada):
                            pass
            except OSError:
                pass
            if time.monotonic() >= fim:
                # não deixa o dono sem conseguir gravar por causa de uma trava esquecida: segue sem ela (e sem apagar a de ninguém)
                return self
            time.sleep(0.05)

    def __exit__(self, *a):
        if self.minha and self._ler_marca() == self.marca:
            try:
                config.remover(self.lock)
            except (OSError, config.RemocaoRecusada):
                pass


def ler_json(caminho, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(padrao)


def gravar_json(caminho, dados):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, caminho)


def atualizar_json(caminho, padrao, mudar):
    """Lê (ou usa 'padrao'), chama mudar(dados) (que altera no lugar ou devolve um valor novo) e grava. Devolve os dados."""
    caminho = Path(caminho)
    with _trava_do(caminho), _TravaDeArquivo(caminho):
        dados = ler_json(caminho, padrao)
        if dados is None or (isinstance(padrao, dict) and not isinstance(dados, dict)):
            dados = copy.deepcopy(padrao)
        novo = mudar(dados)
        if novo is not None:
            dados = novo
        gravar_json(caminho, dados)
        return dados


def anexar_jsonl(caminho, objeto):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linha = json.dumps(objeto, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _trava_do(caminho), _TravaDeArquivo(caminho):
        with open(caminho, "ab") as f:
            f.write(linha.encode("utf-8"))


def ler_jsonl(caminho, limite=None):
    """Linhas boas do JSONL (as quebradas são ignoradas). 'limite' = só as últimas N."""
    saida = []
    try:
        with open(caminho, "rb") as f:
            for linha in f:
                try:
                    o = json.loads(linha)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    saida.append(o)
    except OSError:
        return []
    return saida[-limite:] if limite else saida
