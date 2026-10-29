"""Eventos que o Claude Code manda pelos ganchos (hooks) oficiais: receptor, anel em memória, arquivo do dia e "ouvintes".

Caminho: Claude Code -> gancho (cerebro_hook.py ou "type": "http") -> POST /api/hooks/evento -> receber() aqui.
  * Cada evento é RESUMIDO (só os campos úteis, tudo mascarado e encurtado) e vai para um anel em memória (últimos 2000)
    e para ~/.cerebro/eventos/<AAAA-MM-DD>.jsonl (arquivos com mais de 7 dias são apagados pela trava config.remover).
  * O estado ao vivo (sessão trabalhando / parou / precisa de você, subagente começou / terminou, ferramenta em uso) sai
    daqui para a aba "Agentes ao vivo" (ver aplicar()). Sem ganchos, nada muda: a leitura dos arquivos continua valendo.
  * Ouvintes: outros módulos se registram por tipo de evento (registrar_ouvinte) e podem devolver um texto que volta para
    o Claude Code como "additionalContext" (só nos eventos em que a documentação oficial aceita isso).
Nada aqui decide pelo Claude Code: a resposta é sempre {} (ou só additionalContext vindo de um ouvinte registrado).
"""
import asyncio
import json
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config
from .segredos import encurtar, mascarar

ROTA = "/api/hooks/evento"
CABECALHO = "X-Cerebro-Hooks"
LIMITE_CORPO = 256 * 1024
DIAS_GUARDADOS = 7
JANELA_TRABALHANDO = 10 * 60          # sem novidade dos ganchos há mais que isto: não afirma "trabalhando"
JANELA_HOOKS_ATIVOS = 30 * 60         # recebeu evento nesta janela: a tela diz "ao vivo pelos hooks"

# Eventos que o instalador liga (ver ganchos_claude.py). Outros que chegarem também são aceitos e guardados.
EVENTOS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "SubagentStart", "SubagentStop", "Stop", "Notification",
           "PreCompact", "SessionEnd")
# Eventos em que a doc oficial aceita hookSpecificOutput.additionalContext. Stop/SubagentStop ficam de fora de propósito:
# lá o contexto faz a conversa CONTINUAR, e um ouvinte nunca deve prender o Claude Code num laço.
EVENTOS_COM_CONTEXTO = {"SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
LIMITE_CONTEXTO = 10_000

_trava = threading.RLock()
_anel = deque(maxlen=2000)
_sessoes = {}          # session_id -> estado ao vivo da sessão
_agentes = {}          # agent_id -> estado ao vivo do subagente
_ouvintes = {}         # nome do evento (ou "*") -> [funções]
_rotacao = {"dia": None}
_esperando = set()     # asyncio.Event de cada fluxo SSE esperando novidade


# ---------------------------------------------------------------------------------------------------------------
# Segredo próprio dos ganchos (NUNCA o token da página)
# ---------------------------------------------------------------------------------------------------------------
def arquivo_token():
    return config.CASA / "hooks_token"


def token_hooks(criar=True):
    """Segredo que o gancho manda no cabeçalho X-Cerebro-Hooks. Arquivo só do usuário (como o token da página), mas é OUTRO
    segredo: quem o tem só consegue entregar eventos, não abre a página."""
    import secrets
    caminho = arquivo_token()
    try:
        t = caminho.read_text(encoding="ascii").strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    if not criar:
        return ""
    config.garantir_casa()
    t = secrets.token_urlsafe(32)
    caminho.write_text(t, encoding="ascii")
    config._restringir_ao_dono(caminho)
    return t


# ---------------------------------------------------------------------------------------------------------------
# Resumo de um evento (o que entra no anel, no arquivo e na tela)
# ---------------------------------------------------------------------------------------------------------------
def _texto(v, limite=200):
    return encurtar(v, limite) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _alvo_ferramenta(entrada):
    """O 'alvo' de uma chamada de ferramenta em poucas palavras (arquivo, padrão, comando...). Mascarado e curto."""
    if not isinstance(entrada, dict):
        return ""
    for chave in ("file_path", "path", "notebook_path", "pattern", "url", "query", "description", "command", "prompt"):
        v = entrada.get(chave)
        if isinstance(v, str) and v.strip():
            return encurtar(v.strip().splitlines()[0], 160)
    return ""


def _slug_de(bruto):
    """Projeto do evento: a pasta do transcrito (~/.claude/projects/<slug>/<sessão>.jsonl) ou, se faltar, o cwd codificado."""
    import re
    tp = bruto.get("transcript_path")
    if isinstance(tp, str) and tp:
        p = Path(tp)
        for pasta in (p.parent, p.parent.parent, p.parent.parent.parent):
            if pasta.parent.name == "projects" and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", pasta.name):
                return pasta.name
    cwd = bruto.get("cwd")
    if isinstance(cwd, str) and cwd:
        return re.sub(r"[^A-Za-z0-9]", "-", cwd)[:200]
    return ""


def resumir(bruto, agora=None):
    """Só os campos conhecidos e úteis; campos desconhecidos são ignorados. Todo texto passa por mascarar() e é encurtado."""
    if not isinstance(bruto, dict):
        return None
    nome = bruto.get("hook_event_name")
    if not isinstance(nome, str) or not nome or len(nome) > 60 or not nome.isalnum():
        return None
    ev = {"em": agora or time.time(), "evento": nome, "slug": _slug_de(bruto)}
    for chave, limite in (("session_id", 80), ("agent_id", 80), ("agent_type", 80), ("tool_name", 80), ("tool_use_id", 80),
                          ("notification_type", 40), ("source", 30), ("reason", 40), ("trigger", 20), ("permission_mode", 30),
                          ("title", 120)):
        v = _texto(bruto.get(chave), limite)
        if v:
            ev[chave] = v
    m = bruto.get("model")
    if isinstance(m, str):
        ev["model"] = _texto(m, 80)
    elif isinstance(m, dict):
        ev["model"] = _texto(m.get("id") or m.get("display_name"), 80)
    for chave, limite in (("message", 300), ("prompt", 300), ("last_assistant_message", 300), ("error", 200)):
        v = _texto(bruto.get(chave), limite)
        if v:
            ev[chave] = v
    if "tool_input" in bruto:
        alvo = _alvo_ferramenta(bruto.get("tool_input"))
        if alvo:
            ev["alvo"] = alvo
    if isinstance(bruto.get("stop_hook_active"), bool):
        ev["stop_hook_active"] = bruto["stop_hook_active"]
    if isinstance(bruto.get("duration_ms"), (int, float)) and not isinstance(bruto.get("duration_ms"), bool):
        ev["duration_ms"] = bruto["duration_ms"]
    return ev


# ---------------------------------------------------------------------------------------------------------------
# Estado ao vivo
# ---------------------------------------------------------------------------------------------------------------
def _atualizar_estado(ev):
    t, nome, sid, aid = ev["em"], ev["evento"], ev.get("session_id"), ev.get("agent_id")
    if sid:
        s = _sessoes.setdefault(sid, {"slug": ev["slug"], "inicio": t, "inicio_turno": None, "ferramenta": "", "alvo": "",
                                      "espera_dono": False, "estado": "parado"})
        s.update(ultimo=t, evento=nome)
        if ev["slug"]:
            s["slug"] = ev["slug"]
        if nome == "UserPromptSubmit":
            s.update(estado="trabalhando", inicio_turno=t, espera_dono=False, ferramenta="", alvo="")
        elif nome == "PreToolUse" and not aid:
            s.update(estado="trabalhando", espera_dono=False, ferramenta=ev.get("tool_name", ""), alvo=ev.get("alvo", ""))
        elif nome in ("PreCompact", "SubagentStart", "PostToolUse"):
            s.update(estado="trabalhando", espera_dono=False)
        elif nome == "Notification":
            s.update(espera_dono=True, aviso=ev.get("message", ""), tipo_aviso=ev.get("notification_type", ""))
        elif nome == "Stop":
            s.update(estado="parado", espera_dono=False, ferramenta="", alvo="")
        elif nome == "SessionStart":
            s.update(estado="parado", espera_dono=False)
        elif nome == "SessionEnd":
            s.update(estado="terminou", espera_dono=False, ferramenta="", alvo="")
    if aid:
        a = _agentes.setdefault(aid, {"session_id": sid, "tipo": ev.get("agent_type", ""), "inicio": t, "fim": None, "ferramenta": "", "alvo": ""})
        a["ultimo"] = t
        if nome == "SubagentStart":
            a.update(inicio=t, fim=None)
        elif nome == "SubagentStop":
            a.update(fim=t, ferramenta="", alvo="")
        elif nome == "PreToolUse":
            a.update(ferramenta=ev.get("tool_name", ""), alvo=ev.get("alvo", ""))
    while len(_agentes) > 3000:                          # nunca cresce sem limite
        _agentes.pop(next(iter(_agentes)))
    while len(_sessoes) > 1000:
        _sessoes.pop(next(iter(_sessoes)))


def sessao(sid):
    with _trava:
        s = _sessoes.get(sid)
        return dict(s) if s else None


def ultimo_evento():
    with _trava:
        return _anel[-1]["em"] if _anel else None


def recentes(limite=50, slug=None):
    with _trava:
        lista = [e for e in _anel if slug is None or e.get("slug") == slug]
    return lista[-limite:]


def hooks_ativos(agora=None):
    t = ultimo_evento()
    return bool(t) and (agora or time.time()) - t < JANELA_HOOKS_ATIVOS


def aplicar(slug, dados, agora=None):
    """Junta o estado vindo dos ganchos na árvore montada por agentes.montar() (que leu os arquivos). Os ganchos só valem
    quando são mais novos que o arquivo; sem ganchos (ou velhos), o nó fica como estava, com fonte = "arquivos"."""
    agora = agora or time.time()
    algum = False
    with _trava:
        for no in dados.get("sessoes", []):
            no["fonte"] = "arquivos"
            s = _sessoes.get(no.get("id"))
            if s and s.get("ultimo", 0) >= (no.get("mtime") or 0) - 5:
                algum = True
                no["fonte"] = "hooks"
                estado = s["estado"]
                if estado == "trabalhando" and agora - s["ultimo"] > JANELA_TRABALHANDO:
                    estado = "parado"
                no["estado"] = estado
                no["espera_dono"] = bool(s.get("espera_dono"))
                if s.get("espera_dono"):
                    no["aviso_dono"] = s.get("aviso", "")
                if estado == "trabalhando" and s.get("ferramenta"):
                    no["ferramenta_agora"] = {"nome": s["ferramenta"], "alvo": s.get("alvo", "")}
            for sub in no.get("subagentes", []):
                sub["fonte"] = "arquivos"
                a = _agentes.get(sub.get("id"))
                if not a:
                    continue
                algum = True
                sub["fonte"] = "hooks"
                if a.get("fim"):
                    sub["estado"] = "terminou"
                elif agora - a.get("ultimo", 0) < JANELA_TRABALHANDO:
                    sub["estado"] = "trabalhando"
                    if a.get("ferramenta"):
                        sub["ferramenta_agora"] = {"nome": a["ferramenta"], "alvo": a.get("alvo", "")}
            if no.get("estado") != "trabalhando" and any(x.get("estado") == "trabalhando" for x in no.get("subagentes", [])):
                no["tem_filho_trabalhando"] = True
    dados["fonte"] = "hooks" if algum else "arquivos"
    dados["hooks_ativos"] = hooks_ativos(agora)
    dados["hooks_ultimo_evento"] = ultimo_evento()
    if algum:
        dados["trabalhando"] = sum(1 for n in dados.get("sessoes", []) for x in [n] + n.get("subagentes", []) if x.get("estado") == "trabalhando")
    return dados


# ---------------------------------------------------------------------------------------------------------------
# Arquivo do dia e rotação (7 dias)
# ---------------------------------------------------------------------------------------------------------------
def pasta_eventos():
    return config.CASA / "eventos"


def _gravar(ev):
    pasta = pasta_eventos()
    hoje = date.fromtimestamp(ev["em"])
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / f"{hoje.isoformat()}.jsonl", "ab") as f:
            f.write((json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    except OSError:
        return
    if _rotacao["dia"] != hoje:
        _rotacao["dia"] = hoje
        girar(hoje)


def girar(hoje=None):
    """Apaga (pela trava config.remover) os arquivos de eventos com mais de DIAS_GUARDADOS dias. Devolve quantos apagou."""
    hoje = hoje or date.today()
    corte = hoje - timedelta(days=DIAS_GUARDADOS)
    n = 0
    try:
        arquivos = list(pasta_eventos().glob("*.jsonl"))
    except OSError:
        return 0
    for f in arquivos:
        try:
            dia = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dia < corte:
            try:
                config.remover(f)
                n += 1
            except (OSError, config.RemocaoRecusada):
                pass
    return n


# ---------------------------------------------------------------------------------------------------------------
# Ouvintes (ponto de extensão)
# ---------------------------------------------------------------------------------------------------------------
def registrar_ouvinte(evento, funcao):
    """Chama 'funcao(ev)' a cada evento desse tipo ('*' = todos). 'ev' é o resumo mascarado (ver resumir()).
    Se a função devolver um texto e o evento aceitar (EVENTOS_COM_CONTEXTO), ele volta ao Claude Code como additionalContext.
    Registrar a mesma função duas vezes não duplica. Erros do ouvinte são engolidos (nunca derrubam o receptor)."""
    with _trava:
        lista = _ouvintes.setdefault(evento, [])
        if funcao not in lista:
            lista.append(funcao)


def remover_ouvinte(evento, funcao):
    with _trava:
        if funcao in _ouvintes.get(evento, []):
            _ouvintes[evento].remove(funcao)


def _chamar_ouvintes(ev):
    with _trava:
        funcoes = list(_ouvintes.get(ev["evento"], [])) + list(_ouvintes.get("*", []))
    textos = []
    for f in funcoes:
        try:
            r = f(dict(ev))
        except Exception as e:                        # um ouvinte com defeito não atrapalha os outros
            print(f"Ouvinte de ganchos falhou: {type(e).__name__}: {e}", flush=True)
            continue
        if isinstance(r, str) and r.strip():
            textos.append(r.strip())
    return textos


def resposta_para(ev, textos):
    """O que devolver ao Claude Code: {} (nada a dizer) ou só additionalContext, no formato da doc oficial."""
    if not textos or ev["evento"] not in EVENTOS_COM_CONTEXTO:
        return {}
    texto = mascarar("\n\n".join(textos))[:LIMITE_CONTEXTO]
    return {"hookSpecificOutput": {"hookEventName": ev["evento"], "additionalContext": texto}}


# ---------------------------------------------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------------------------------------------
def receber(bruto, agora=None):
    """Registra um evento cru (dict vindo do Claude Code). Devolve (resumo ou None, resposta para o Claude Code).
    Síncrono e rápido: chamado numa thread pelo receptor HTTP."""
    ev = resumir(bruto, agora)
    if ev is None:
        return None, {}
    with _trava:
        _anel.append(ev)
        _atualizar_estado(ev)
        _gravar(ev)
    return ev, resposta_para(ev, _chamar_ouvintes(ev))


def ler_corpo(bytes_):
    """JSON tolerante: corpo quebrado ou que não é objeto vira None (o receptor responde {} e segue)."""
    try:
        d = json.loads(bytes_.decode("utf-8", "replace"))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


# ---------------------------------------------------------------------------------------------------------------
# Fluxos SSE acordam na hora em que chega evento (em vez de esperar o próximo ciclo de 3 s)
# ---------------------------------------------------------------------------------------------------------------
def acordar():
    for e in list(_esperando):
        e.set()


async def esperar_novidade(limite):
    """Espera até 'limite' segundos ou até chegar um evento dos ganchos (o que vier primeiro)."""
    e = asyncio.Event()
    _esperando.add(e)
    try:
        await asyncio.wait_for(e.wait(), timeout=limite)
        await asyncio.sleep(0.25)                     # junta uma rajada de eventos numa atualização só
    except asyncio.TimeoutError:
        pass
    finally:
        _esperando.discard(e)


def zerar():
    """Só para os testes: esquece tudo que está em memória."""
    with _trava:
        _anel.clear()
        _sessoes.clear()
        _agentes.clear()
        _ouvintes.clear()
        _rotacao["dia"] = None


def info():
    with _trava:
        return {"eventos_em_memoria": len(_anel), "ultimo_evento": _anel[-1]["em"] if _anel else None,
                "por_tipo": _contar(), "pasta": str(pasta_eventos()), "ativos": hooks_ativos()}


def _contar():
    c = {}
    for e in _anel:
        c[e["evento"]] = c.get(e["evento"], 0) + 1
    return c

