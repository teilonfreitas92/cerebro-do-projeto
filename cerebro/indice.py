"""Arquivos de sessão/subagente de cada projeto e o índice (cache) incremental deles.

Estrutura lida (só leitura) em ~/.claude/projects/<slug>/:
    <sessão>.jsonl                          a conversa principal
    <sessão>\\subagents\\agent-<id>.jsonl      um subagente dessa sessão
    <sessão>\\subagents\\agent-<id>.meta.json  (não documentado; "bônus": modelo, descrição, se terminou)
    <sessão>\\custom-title.json              título dado pelo dono, quando existe
O índice de cada arquivo (tokens por mensagem, título, ferramentas...) fica em ~/.cerebro/projetos/<slug>/
indice.json e é atualizado só com o que foi escrito depois da última leitura.
"""
import json
import os
import threading
import time
from pathlib import Path

from . import config, titulos, transcricao
from .segredos import encurtar

VERSAO_INDICE = 2          # 2: títulos/resumos passam a ser gravados já mascarados
_estados = {}
_trava_geral = threading.Lock()


class Estado:
    """Índice em memória + em disco de um projeto, com trava própria."""

    def __init__(self, slug):
        self.slug = slug
        self.trava = threading.RLock()
        self.arquivos = {}              # rel -> índice do arquivo
        self.sujo = False
        self.versao = 0                 # sobe a cada mudança no índice (invalida o cache de custos)
        self.ultimo_salvo = 0.0
        self.progresso = {"rodando": False, "total": 0, "feito": 0}
        self._carregar()

    def _caminho(self):
        return config.pasta_projeto(self.slug) / "indice.json"

    def _carregar(self):
        try:
            d = json.loads(self._caminho().read_text(encoding="utf-8"))
            if d.get("v") == VERSAO_INDICE:
                self.arquivos = d.get("arquivos") or {}
        except (OSError, ValueError):
            pass

    def salvar(self, forcar=False):
        with self.trava:
            if not self.sujo or (not forcar and time.time() - self.ultimo_salvo < 5):
                return
            tmp = self._caminho().with_name("indice.json.tmp")
            tmp.write_text(json.dumps({"v": VERSAO_INDICE, "arquivos": self.arquivos}, ensure_ascii=False,
                                      separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self._caminho())
            self.sujo = False
            self.ultimo_salvo = time.time()


def estado(slug):
    with _trava_geral:
        if slug not in _estados:
            _estados[slug] = Estado(slug)
        return _estados[slug]


def salvar_tudo():
    for e in list(_estados.values()):
        try:
            e.salvar(forcar=True)
        except OSError:
            pass


def pasta_claude(slug):
    return config.PROJETOS_CLAUDE / slug


def listar_arquivos(slug):
    """Todos os arquivos de transcrição do projeto: sessões e subagentes (sem ler o conteúdo, só a lista e as datas)."""
    base = pasta_claude(slug)
    saida = []
    try:
        entradas = list(os.scandir(base))
    except OSError:
        return saida
    for e in entradas:
        if e.is_file() and e.name.endswith(".jsonl"):
            try:
                st = e.stat()
            except OSError:
                continue
            sid = e.name[:-6]
            saida.append({"rel": e.name, "tipo": "sessao", "sessao": sid, "id": sid, "tam": st.st_size, "mtime": st.st_mtime})
        elif e.is_dir():
            sub = Path(e.path) / "subagents"
            try:
                itens = list(os.scandir(sub))
            except OSError:
                continue
            for a in itens:
                if a.is_file() and a.name.startswith("agent-") and a.name.endswith(".jsonl"):
                    try:
                        st = a.stat()
                    except OSError:
                        continue
                    aid = a.name[len("agent-"):-6]
                    saida.append({"rel": f"{e.name}/subagents/{a.name}", "tipo": "subagente", "sessao": e.name, "id": aid,
                                  "tam": st.st_size, "mtime": st.st_mtime})
    return saida


def ler_meta(slug, arq):
    """agent-<id>.meta.json (não documentado): {} se não houver ou estiver diferente do esperado."""
    if arq["tipo"] != "subagente":
        return {}
    caminho = pasta_claude(slug) / arq["rel"].replace(".jsonl", ".meta.json")
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {}
        for campo in ("description", "agentType", "model"):          # o texto do pedido pode ter segredo
            if isinstance(d.get(campo), str):
                d[campo] = encurtar(d[campo], 300)
        return d
    except (OSError, ValueError):
        return {}


def titulo_do_dono(slug, sessao_id):
    """custom-title.json da sessão (quando o dono renomeou)."""
    try:
        d = json.loads((pasta_claude(slug) / sessao_id / "custom-title.json").read_text(encoding="utf-8"))
        return str(d.get("customTitle") or "")
    except (OSError, ValueError, AttributeError):
        return ""


JANELA_TRABALHANDO = 60          # segundos sem escrever para deixar de ser "trabalhando"


def estado_subagente(mtime, meta, agora=None):
    """trabalhando / parado / terminou de um subagente. 'terminou' = o Claude Code marcou finished ou ficou parado mais de 1 h."""
    agora = agora or time.time()
    if meta.get("finished") is True:
        return "terminou"
    if agora - mtime < JANELA_TRABALHANDO:
        return "trabalhando"
    return "parado" if agora - mtime < 3600 else "terminou"


def titulo_sessao(slug, sessao_id, cfg, ind=None):
    """Melhor título da sessão (apelido da gestora, título do app, resumo...). Ver titulos.py. Devolve {titulo, fonte, original, resumo}."""
    if ind is None:
        ind = indice_se_existe(slug, sessao_id + ".jsonl") or {}
    return titulos.titulo_da_sessao(slug, sessao_id, ind, titulo_do_dono(slug, sessao_id), cfg)


def indice_do_arquivo(slug, arq):
    """Índice atualizado de um arquivo (lê só o que é novo). Pode demorar na primeira vez de um arquivo grande."""
    est = estado(slug)
    caminho = pasta_claude(slug) / arq["rel"]
    with est.trava:
        ind, mudou = transcricao.atualizar_indice(caminho, est.arquivos.get(arq["rel"]))
        if mudou or arq["rel"] not in est.arquivos:
            est.arquivos[arq["rel"]] = ind
            est.sujo = True
            est.versao += 1
            est.salvar()
        return ind


def indice_se_existe(slug, rel):
    """Índice já guardado (sem ler o arquivo) ou None."""
    return estado(slug).arquivos.get(rel)


def indexar_projeto(slug, desde_mtime=0.0, sinal_parar=None):
    """Atualiza o índice de todos os arquivos do projeto modificados depois de 'desde_mtime'. Atualiza o progresso."""
    est = estado(slug)
    arquivos = [a for a in listar_arquivos(slug) if a["mtime"] >= desde_mtime]
    # só precisa ler quem mudou desde a última vez
    pendentes = []
    for a in arquivos:
        ind = est.arquivos.get(a["rel"])
        if ind is None or ind.get("tam", 0) != a["tam"]:
            pendentes.append(a)
    pendentes.sort(key=lambda a: -a["mtime"])          # os mais novos primeiro
    est.progresso.update(rodando=True, total=len(pendentes), feito=0)
    try:
        for a in pendentes:
            if sinal_parar is not None and sinal_parar.is_set():
                break
            try:
                indice_do_arquivo(slug, a)
            except OSError:
                pass
            est.progresso["feito"] += 1
    finally:
        est.progresso["rodando"] = False
        est.salvar(forcar=True)
    return est.progresso["feito"]


_threads = {}


def indexar_em_segundo_plano(slug, desde_mtime=0.0):
    """Dispara a indexação numa thread (uma por projeto de cada vez). Devolve True se iniciou uma nova."""
    with _trava_geral:
        t = _threads.get(slug)
        if t is not None and t.is_alive():
            return False
        t = threading.Thread(target=indexar_projeto, args=(slug, desde_mtime), daemon=True, name=f"indexar-{slug}")
        _threads[slug] = t
        t.start()
        return True


def pendentes(slug, desde_mtime=0.0):
    """Quantos arquivos ainda precisam ser lidos (sem ler nenhum)."""
    est = estado(slug)
    n = 0
    for a in listar_arquivos(slug):
        if a["mtime"] < desde_mtime:
            continue
        ind = est.arquivos.get(a["rel"])
        if ind is None or ind.get("tam", 0) != a["tam"]:
            n += 1
    return n
