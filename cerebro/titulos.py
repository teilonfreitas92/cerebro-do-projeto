"""Títulos melhores para as sessões.

O título que o dono dá no app costuma ser um rótulo ("### Loja ###") que diz pouco quando há muitas conversas. Aqui o
Cérebro escolhe, nesta ordem (SOMENTE LEITURA):
  1. o apelido configurado para a sessão gestora ("Gestora principal");
  2. o título do app Claude (pasta de sessões do aplicativo), se não for só um rótulo;
  3. o título gravado na conversa (custom-title), se não for só um rótulo;
  4. o título/resumo que o Claude Code grava no JSONL (ai-title / summary), quando existir;
  5. o resumo curto do último turno que o app guarda ("Cérebro v1 pronto; construindo a versão 1.1");
  6. a primeira mensagem útil do dono;
  7. o rótulo do dono, se não houver mais nada; por último o começo do identificador.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

from .segredos import encurtar

_ROTULO = re.compile(r"^\s*(#{2,}|\*{2,}|={2,}|-{3,})")        # começa com ###, ***, === ou ---
_cache = {"t": 0.0, "arquivos": {}, "mapa": {}}
_trava = threading.Lock()


def pasta_app():
    """Pasta onde o app Claude guarda os metadados das sessões (título, resumo). Pode não existir: tudo é opcional."""
    env = os.environ.get("CEREBRO_APPDATA")
    if env:
        return Path(env)
    base = os.environ.get("APPDATA")
    return Path(base) / "Claude" / "claude-code-sessions" if base else None


def eh_rotulo(titulo):
    """'### Loja ###', '### Loja (fork)' e vazio são rótulos de organização, não descrevem a conversa."""
    t = (titulo or "").strip()
    return not t or bool(_ROTULO.match(t)) or t.lower() in ("(sem título)", "sem título", "untitled", "new session")


def _ler_app():
    """cliSessionId -> {titulo, resumo, fonte}. Relê só os arquivos que mudaram (são poucos e pequenos)."""
    base = pasta_app()
    if base is None or not base.is_dir():
        return {}
    with _trava:
        if time.time() - _cache["t"] < 10:
            return _cache["mapa"]
        novos, mapa = {}, {}
        try:
            arquivos = [f for f in base.rglob("local_*.json") if f.is_file()]
        except OSError:
            arquivos = []
        for f in arquivos:
            try:
                st = f.stat()
            except OSError:
                continue
            chave = (str(f), st.st_mtime, st.st_size)
            item = _cache["arquivos"].get(chave)
            if item is None:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(d, dict):
                    continue
                post = d.get("postTurnSummary") if isinstance(d.get("postTurnSummary"), dict) else {}
                item = {"sessao": str(d.get("cliSessionId") or ""), "titulo": str(d.get("title") or ""),
                        "fonte": str(d.get("titleSource") or ""), "resumo": str(post.get("status_detail") or "")}
            novos[chave] = item
            if item["sessao"]:
                mapa[item["sessao"]] = item
        _cache.update(t=time.time(), arquivos=novos, mapa=mapa)
        return mapa


def _resumir(texto, limite=90):
    t = " ".join((texto or "").split())
    t = t.split(". ")[0] if len(t) > limite else t
    return encurtar(t, limite)


def escolher(slug, sessao_id, ind=None, titulo_dono="", apelido=""):
    """Devolve {titulo, fonte, original, resumo}. 'ind' = índice da sessão; 'titulo_dono' = custom-title.json."""
    ind = ind or {}
    app = _ler_app().get(sessao_id, {})
    original = encurtar(app.get("titulo") or titulo_dono or ind.get("titulo") or "", 200)
    resumo = _resumir(app.get("resumo", ""))
    resultado = {"original": original, "resumo": resumo}
    if apelido:
        return {**resultado, "titulo": apelido, "fonte": "apelido da gestora"}
    for fonte, valor in (("app", app.get("titulo")), ("conversa", titulo_dono), ("conversa", ind.get("titulo")),
                         ("ia", ind.get("titulo_ia")), ("resumo", ind.get("resumo"))):
        if valor and not eh_rotulo(valor):
            return {**resultado, "titulo": encurtar(valor, 120), "fonte": fonte}
    if resumo:
        return {**resultado, "titulo": resumo, "fonte": "resumo do app"}
    primeira = ind.get("primeira") or ""
    if primeira:
        return {**resultado, "titulo": _resumir(primeira, 90), "fonte": "primeira mensagem"}
    if original:
        return {**resultado, "titulo": original, "fonte": "rótulo do dono"}
    return {**resultado, "titulo": (sessao_id or "")[:8] or "(sem título)", "fonte": "identificador"}


def titulo_da_sessao(slug, sessao_id, ind, titulo_dono, cfg):
    """Atalho: título final, usando o apelido da gestora quando a sessão é a gestora do projeto."""
    ges = (cfg.get("gestoras") or {}).get(slug) or {}
    apelido = ges.get("nome", "") if ges.get("conversa") == sessao_id else ""
    return escolher(slug, sessao_id, ind, titulo_dono, apelido)
