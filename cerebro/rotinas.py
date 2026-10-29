"""Rotinas que rodam SÓ enquanto o servidor está aberto: análise automática e (se você ligar) busca de novidades.

O intervalo vem do config (autoevolucao_dias / vigia_novidades_dias). Quando o servidor está no ar e o prazo passou, a rotina
roda sozinha em segundo plano; com o servidor fechado nada roda (o agendamento no Windows fica para depois, com o "sim" do
dono). A análise não usa IA e só propõe; a busca de novidades só roda sozinha se `novidades_automatica` estiver ligado.
"""
import threading
import time

from . import analise, config, novidades, projetos, propostas

_trava = threading.Lock()
_rodando = set()           # nomes de rotinas em andamento
_ultimo_erro = {}
_erro_em = {}              # chave -> quando falhou (espera 1 h antes de tentar de novo)
ESPERA_APOS_ERRO = 3600


def _analisados(cfg):
    """Projetos que a análise automática cobre: os visíveis que têm sessão gestora escolhida, mais o próprio Cérebro."""
    gestoras = cfg.get("gestoras") or {}
    slugs = [p["slug"] for p in projetos.descobrir() if not p["oculto"] and p["slug"] in gestoras]
    return slugs + [propostas.ESCOPO_CEREBRO]


def devidos(cfg, agora=None):
    """Lista de ('analise', slug) e ('novidades', '') que já passaram do prazo. Só lê datas de arquivos pequenos."""
    agora = agora or time.time()
    r = cfg.get("rotinas") or {}
    saida = []
    if r.get("analise_automatica", True):
        dias = int(r.get("autoevolucao_dias") or 7)
        for slug in _analisados(cfg):
            ultima = analise.ler(slug, cfg)["ultima_em"]
            if ultima is None or agora - ultima >= dias * 86400:
                saida.append(("analise", slug))
    if r.get("novidades_automatica"):
        dias = int(r.get("vigia_novidades_dias") or 3)
        ult = novidades.estado().get("ultima_busca")
        if ult is None or agora - ult >= dias * 86400:
            saida.append(("novidades", ""))
    return saida


def tick(agora=None, fazer_analise=None, fazer_novidades=None):
    """Um giro: roda UMA rotina devida (a mais atrasada) e devolve o que fez. Síncrono; o servidor chama numa thread."""
    cfg = config.ler_config()
    fazer_analise = fazer_analise or (lambda slug: analise.executar(slug, cfg))
    fazer_novidades = fazer_novidades or (lambda: novidades.procurar(cfg))
    for tipo, slug in devidos(cfg, agora):
        chave = f"{tipo}:{slug}"
        with _trava:
            if chave in _rodando or (agora or time.time()) - _erro_em.get(chave, 0) < ESPERA_APOS_ERRO:
                continue
            _rodando.add(chave)
        try:
            if tipo == "analise":
                fazer_analise(slug)
            else:
                fazer_novidades()
            _ultimo_erro.pop(chave, None)
            _erro_em.pop(chave, None)
            return [chave]
        except Exception as e:
            _ultimo_erro[chave] = f"{type(e).__name__}: {str(e)[:200]}"
            _erro_em[chave] = agora or time.time()
            return [chave + " (erro)"]
        finally:
            with _trava:
                _rodando.discard(chave)
    return []


def situacao():
    with _trava:
        return {"rodando": sorted(_rodando), "erros": dict(_ultimo_erro)}
