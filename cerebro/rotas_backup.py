"""Rotas do backup e das rotinas no Windows. A segurança (cookie, Host, Origin, JSON) vem do middleware do servidor como em
toda rota; aqui só a validação dos pedidos. Escrever em ~/.claude/projects só por /api/backup/restaurar com "confirmar": true
(o botão da página manda depois do segundo clique). Ligar uma rotina no Windows: o clique da pessoa é a confirmação."""
import asyncio

from . import agendador, backup, rotinas_windows
from .segredos import mascarar
from .web_util import _corpo, _erro, _json


def _texto(v, limite=200):
    return v.strip()[:limite] if isinstance(v, str) else ""


def _mascarar_plano(pl):
    """Nomes de arquivo vão para a tela: passam pelo mascaramento (o 'arq' original segue como chave para marcar a troca)."""
    for g in pl["grupos"]:
        for chave in ("faltam", "diferentes", "cresceram"):
            for it in g[chave]:
                it["mostrar"] = mascarar(it["arq"])
        g["suspeitos"] = [mascarar(x) for x in g["suspeitos"]]
    return pl


async def api_backup(request):
    r = await asyncio.to_thread(backup.resumo)
    try:
        r["origem_hoje"] = await asyncio.to_thread(backup.medir_origens)
    except Exception:
        r["origem_hoje"] = None
    return _json(r)


async def api_backup_agora(request):
    try:
        r = await asyncio.to_thread(backup.fazer_backup)
    except backup.BackupErro as e:
        return _erro(str(e), 409)
    r["falhas"] = [{"arq": mascarar(f["arq"]), "erro": f["erro"]} for f in r["falhas"][:30]]
    return _json(r)


async def api_backup_conferir(request):
    c = await _corpo(request)
    try:
        return _json(await asyncio.to_thread(backup.conferir, _texto(c.get("snapshot"))))
    except backup.BackupErro as e:
        return _erro(str(e), 404)


async def api_backup_plano(request):
    c = await _corpo(request)
    try:
        pl = await asyncio.to_thread(backup.plano, _texto(c.get("snapshot")), _texto(c.get("projeto")) or None, c.get("so_memoria") is True)
    except backup.BackupErro as e:
        return _erro(str(e), 404)
    return _json(_mascarar_plano(pl))


async def api_backup_restaurar(request):
    c = await _corpo(request)
    if c.get("confirmar") is not True:
        return _erro("restaurar precisa de confirmação explícita", 400)
    trocar = c.get("trocar") or []
    if not isinstance(trocar, list) or not all(isinstance(x, str) and len(x) < 1000 for x in trocar) or len(trocar) > 50000:
        return _erro("lista de arquivos a trocar inválida")
    try:
        r = await asyncio.to_thread(backup.restaurar, _texto(c.get("snapshot")), True, trocar, False,
                                    _texto(c.get("projeto")) or None, c.get("so_memoria") is True)
    except backup.BackupErro as e:
        return _erro(str(e), 409)
    return _json({"copiados": len(r["copiados"]), "trocados": len(r["trocados"]), "pulados": len(r["pulados"]),
                  "cresceram": r["cresceram"], "erros": [mascarar(x) for x in r["erros"][:30]], "copias": r["copias"]})


async def api_backup_liberar(request):
    """Devolver os protegidos à rotação deixa o backup bom sair em alguns dias: só com "confirmar": true (o botão da página
    manda depois de a pessoa confirmar), como restaurar."""
    c = await _corpo(request)
    if c.get("confirmar") is not True:
        return _erro("liberar os backups protegidos precisa de confirmação explícita", 400)
    return _json({"liberados": await asyncio.to_thread(backup.liberar_protegidos)})


async def api_rotinas_windows(request):
    return _json(await asyncio.to_thread(rotinas_windows.situacao))


async def api_rotinas_windows_mudar(request):
    c = await _corpo(request)
    rotina, acao = c.get("rotina"), c.get("acao")
    if rotina not in agendador.ROTINAS or acao not in ("ligar", "desligar"):
        return _erro("pedido inválido")
    try:
        if acao == "ligar":
            p = {k: c[k] for k in ("hora", "dias", "horas") if k in c}
            await asyncio.to_thread(agendador.ligar, rotina, {**agendador.parametros(rotina), **p})
        else:
            await asyncio.to_thread(agendador.desligar, rotina)
    except (ValueError, agendador.AgendadorErro) as e:
        return _erro(str(e), 409)
    return _json(await asyncio.to_thread(rotinas_windows.situacao))


def registrar(r):
    """Chamado por servidor.criar_app."""
    r.add_get("/api/backup", api_backup)
    r.add_post("/api/backup/agora", api_backup_agora)
    r.add_post("/api/backup/conferir", api_backup_conferir)
    r.add_post("/api/backup/plano", api_backup_plano)
    r.add_post("/api/backup/restaurar", api_backup_restaurar)
    r.add_post("/api/backup/liberar", api_backup_liberar)
    r.add_get("/api/rotinas/windows", api_rotinas_windows)
    r.add_post("/api/rotinas/windows", api_rotinas_windows_mudar)
