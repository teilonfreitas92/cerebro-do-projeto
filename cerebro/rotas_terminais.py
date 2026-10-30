"""Rotas dos terminais de verdade (ver terminais.py): abrir o claude no projeto, listar, fechar e o WebSocket que liga a tela
(xterm.js) ao pseudo-terminal. Mesma segurança das outras rotas (cookie, Host, Origin); o WebSocket exige Origin da página.

Mensagens do WebSocket (JSON):
  servidor → página: {"t": "d", "d": texto}  pedaço da tela   ·  {"t": "fim"}  o claude terminou
  página → servidor: {"t": "e", "d": texto}  teclas digitadas ·  {"t": "r", "c": colunas, "l": linhas}  novo tamanho
"""
import asyncio
import json

from aiohttp import WSMsgType, web

from . import agentes, indice, terminais
from .web_util import K_ESTADO, K_PORTA, _corpo, _erro, _json, _projeto_ou_404

MAX_ENTRADA = 64_000


def _origem_ok(request):
    porta = request.app[K_PORTA]
    return request.headers.get("Origin") in {f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"}


async def api_terminais(request):
    p = _projeto_ou_404(request)
    return _json({"disponivel": terminais.python_ok(), "limite": terminais.LIMITE, "terminais": terminais.listar(p["slug"])})


def _em_uso(slug, sessao):
    abertas = {c.get("sessionId") for c in (agentes.claude_agents() or []) if isinstance(c, dict)}
    mtime = next((a["mtime"] for a in indice.listar_arquivos(slug) if a["tipo"] == "sessao" and a["id"] == sessao), None)
    if mtime is None:
        raise terminais.ErroTerminal("sessão não encontrada neste projeto")
    return terminais.sessao_em_uso(slug, sessao, abertas, mtime)


async def api_terminal_abrir(request):
    """Abre o claude no projeto: sessão nova, ou retomando 'sessao'. Se a sessão parece aberta em outro lugar, responde 409
    (a página pergunta e manda de novo com forcar=true)."""
    p = _projeto_ou_404(request)
    c = await _corpo(request)
    sessao = c.get("sessao") or None
    if sessao is not None and not (isinstance(sessao, str) and terminais.ID_SESSAO.match(sessao)):
        return _erro("id de sessão inválido")
    try:
        cols, rows = int(c.get("cols") or 120), int(c.get("rows") or 32)
    except (TypeError, ValueError):
        return _erro("tamanho inválido")
    titulo = c.get("titulo") if isinstance(c.get("titulo"), str) else ""
    try:
        if sessao and c.get("forcar") is not True:
            motivo = await asyncio.to_thread(_em_uso, p["slug"], sessao)
            if motivo:
                return _json({"erro": motivo + ": feche lá antes, senão as duas janelas brigam pela mesma conversa.", "em_uso": True}, 409)
        t = await asyncio.to_thread(terminais.abrir, p["slug"], p["caminho"], sessao, titulo, cols, rows)
    except terminais.ErroTerminal as e:
        return _erro(str(e))
    except OSError as e:
        return _erro(f"não consegui abrir o terminal: {type(e).__name__}")
    return _json(t.resumo())


async def api_terminal_fechar(request):
    t = terminais.achar(request.match_info["tid"])
    if t is None:
        return _erro("terminal não encontrado", 404)
    await asyncio.to_thread(terminais.fechar, t.id)
    return _json({"ok": True})


async def ws_terminal(request):
    if not _origem_ok(request):
        return web.Response(status=403, text="Origem obrigatória")
    t = terminais.achar(request.match_info["tid"])
    if t is None:
        raise web.HTTPNotFound()
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_ENTRADA * 2)
    await ws.prepare(request)
    loop, fila = asyncio.get_running_loop(), asyncio.Queue()

    def ouvir(texto):                         # roda na thread de leitura do terminal
        try:
            loop.call_soon_threadsafe(fila.put_nowait, texto)
        except RuntimeError:                  # laço já fechado
            pass

    async def enviar():
        while True:
            texto = await fila.get()
            if texto is None:
                await ws.send_str('{"t":"fim"}')
                return
            partes = [texto]
            while not fila.empty() and sum(map(len, partes)) < 200_000:     # junta o que chegou junto num envio só
                proximo = fila.get_nowait()
                if proximo is None:
                    fila.put_nowait(None)
                    break
                partes.append(proximo)
            await ws.send_str(json.dumps({"t": "d", "d": "".join(partes)}, ensure_ascii=False))

    estado = request.app[K_ESTADO]
    estado["sse_ativos"] += 1                 # janela aberta conta como página aberta (o servidor não encerra sozinho)
    cauda = t.assinar(ouvir)
    tarefa = None
    try:
        await ws.send_str(json.dumps({"t": "d", "d": cauda}, ensure_ascii=False))
        if t.fim is not None:
            await ws.send_str('{"t":"fim"}')
        tarefa = asyncio.create_task(enviar())
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(m, dict) or t.fim is not None:
                continue
            if m.get("t") == "e" and isinstance(m.get("d"), str) and len(m["d"]) <= MAX_ENTRADA:
                await asyncio.to_thread(t.pty.escrever, m["d"])
            elif m.get("t") == "r":
                try:
                    c, r = max(20, min(int(m.get("c")), 400)), max(5, min(int(m.get("l")), 200))
                    await asyncio.to_thread(t.pty.tamanho, c, r)
                except (TypeError, ValueError, OSError):
                    pass
    except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
        pass
    finally:
        t.desassinar(ouvir)
        if tarefa:
            tarefa.cancel()
        estado["sse_ativos"] -= 1
    return ws


def registrar(r):
    r.add_get("/api/p/{slug}/terminais", api_terminais)
    r.add_post("/api/p/{slug}/terminais", api_terminal_abrir)
    r.add_post("/api/terminais/{tid}/fechar", api_terminal_fechar)
    r.add_get("/api/terminais/{tid}/ws", ws_terminal)
