"""O mapa se atualiza sozinho.

Os ganchos do Graphify (se o projeto os tiver) já refazem `<projeto>\\graphify-out\\graph.json` a cada commit. Enquanto o servidor do Cérebro
está no ar, este vigia olha (a cada ~30 s, barato: só a data do arquivo) o graph.json de cada projeto com mapa e, quando
ele fica mais novo que o dados.js do Cérebro, roda o gerador em segundo plano (processo à parte, sem janela, sem travar a
página). Ao abrir o servidor a mesma checagem roda uma vez na hora. A página do mapa já recarrega sozinha quando o
dados.js muda. Se o gerador falhar, tenta de novo com espera crescente (1, 2, 4... até 15 min) e mostra o erro.
Só LÊ o graphify-out do projeto; escreve apenas em ~/.cerebro.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, projetos
from .segredos import mascarar

GERADOR = Path(__file__).resolve().parent.parent / "mapa" / "gerar.py"
ESTABILIZAR = 4               # segundos que o graph.json precisa estar parado antes de gerar (o Graphify ainda pode estar escrevendo)
MSG_TEMPO = "o gerador do mapa passou do tempo limite (5 minutos) e foi interrompido"
_trava = threading.Lock()
_estado = {}                  # slug -> {gerando, ultima_geracao, ultimo_erro, falhas, proxima, graph_visto, motivo}


def gerar(caminho_projeto, timeout=300):
    """Roda o gerar.py. Devolve (ok, últimas linhas da saída)."""
    r = subprocess.run([sys.executable, str(GERADOR), "--projeto", str(caminho_projeto)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-600:]


def _est(slug):
    return _estado.setdefault(slug, {"gerando": False, "ultima_geracao": None, "ultimo_erro": "", "falhas": 0, "proxima": 0.0,
                                     "graph_visto": None, "motivo": ""})


def motivo_para_gerar(caminho, slug, agora=None):
    """'' se está em dia; senão o motivo ('sem página' / 'mapa novo')."""
    agora = agora or time.time()
    graph = Path(caminho) / "graphify-out" / "graph.json"
    dados = config.CASA / "projetos" / slug / "mapa" / "dados.js"
    try:
        gm = graph.stat().st_mtime
    except OSError:
        return ""
    try:
        dm = dados.stat().st_mtime
    except OSError:
        dm = None
    if agora - gm < ESTABILIZAR:
        return ""                                   # ainda sendo escrito: espera o próximo giro
    if dm is None:
        return "sem página"
    return "mapa novo" if gm > dm else ""


def varrer(forcar=False, agora=None, gerar_fn=None):
    """Um giro do vigia: gera o que estiver defasado. Devolve a lista de slugs gerados agora. Síncrono (rode em thread)."""
    cfg = config.ler_config()
    if not forcar and not (cfg.get("rotinas") or {}).get("mapa_automatico", True):
        return []
    agora = agora or time.time()
    gerar_fn = gerar_fn or gerar
    feitos = []
    for p in projetos.descobrir():
        if p["oculto"]:
            continue
        slug, caminho = p["slug"], p["caminho"]
        graph = Path(caminho) / "graphify-out" / "graph.json"
        if not graph.is_file():
            continue
        e = _est(slug)
        with _trava:
            if e["gerando"]:
                continue
            try:
                gm = graph.stat().st_mtime
            except OSError:
                continue
            if e["graph_visto"] != gm:               # mapa mudou: zera a espera dos erros
                e["graph_visto"], e["falhas"], e["proxima"] = gm, 0, 0.0
            if agora < e["proxima"]:
                continue
            motivo = motivo_para_gerar(caminho, slug, agora)
            if not motivo:
                continue
            e["gerando"], e["motivo"] = True, motivo
        try:
            ok, saida = gerar_fn(caminho)
        except subprocess.TimeoutExpired:
            ok, saida = False, MSG_TEMPO
        except Exception as ex:                       # QUALQUER erro: o projeto não pode ficar preso em "gerando"
            ok, saida = False, f"{type(ex).__name__}: {ex}"
        with _trava:
            e["gerando"] = False
            if ok:
                e.update(ultima_geracao=time.time(), ultimo_erro="", falhas=0, proxima=0.0)
                feitos.append(slug)
            else:
                e["falhas"] += 1
                e["ultimo_erro"] = saida[-300:]
                e["proxima"] = time.time() + min(900, 60 * 2 ** (e["falhas"] - 1))
    return feitos


def gerar_agora(slug, caminho_projeto, timeout=300):
    """Botão "refazer agora": marca 'gerando' (o vigia não roda junto) e devolve (ok, texto). ok=None se já havia geração em curso."""
    e = _est(slug)
    with _trava:
        if e["gerando"]:
            return None, "o mapa já está sendo gerado; espere terminar"
        e["gerando"], e["motivo"] = True, "manual"
    try:
        try:
            ok, saida = gerar(caminho_projeto, timeout)
        except subprocess.TimeoutExpired:
            ok, saida = False, MSG_TEMPO
        except Exception as ex:
            ok, saida = False, f"{type(ex).__name__}: {ex}"
    finally:
        with _trava:
            e["gerando"] = False
    with _trava:
        if ok:
            e.update(ultima_geracao=time.time(), ultimo_erro="", falhas=0, proxima=0.0)
        else:
            e["ultimo_erro"] = saida[-300:]
    return ok, saida


def criar_mapa(slug, caminho_projeto, exe, timeout=600, rodar=None):
    """Primeiro uso, SÓ com clique: roda `graphify update .` DENTRO do projeto (ele cria a pasta graphify-out lá) e depois monta a página
    do Cérebro. Devolve (ok, texto); ok=None se já havia geração em curso. 'rodar' existe para os testes."""
    e = _est(slug)
    with _trava:
        if e["gerando"]:
            return None, "o mapa já está sendo gerado; espere terminar"
        e["gerando"], e["motivo"] = True, "primeiro mapa"
    try:
        try:
            if rodar is not None:
                rodar(caminho_projeto)
                saida = ""
            else:
                r = subprocess.run([exe, "update", "."], cwd=str(caminho_projeto), capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=timeout, stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"})
                saida = mascarar((r.stdout + r.stderr).strip()[-600:])
                if r.returncode != 0:
                    return False, "o Graphify terminou com erro:\n" + saida
            if not (Path(caminho_projeto) / "graphify-out" / "graph.json").is_file():
                return False, "o Graphify rodou mas não criou o graphify-out/graph.json neste projeto." + (("\n" + saida) if saida else "")
            ok, texto = gerar(caminho_projeto)
            if ok:
                e.update(ultima_geracao=time.time(), ultimo_erro="", falhas=0, proxima=0.0)
            return ok, texto
        except subprocess.TimeoutExpired:
            return False, "o Graphify passou do tempo limite (10 minutos) e foi interrompido"
        except Exception as ex:
            return False, f"{type(ex).__name__}: {ex}"
    finally:
        with _trava:
            e["gerando"] = False


def estado(slug):
    """Para a página: o que o vigia está fazendo com este projeto."""
    with _trava:
        e = dict(_est(slug))
    e["proxima_tentativa_em"] = e["proxima"] if e["proxima"] > time.time() else None
    return e
