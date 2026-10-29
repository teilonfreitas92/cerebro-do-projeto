"""Retenção das transcrições ANTIGAS da sessão gestora: a ÚNICA porta do Cérebro para apagar algo dentro de ~/.claude/projects.

A trava geral (config.remover) recusa ~/.claude de propósito e continua recusando. Esta é uma trava própria, ESTREITA:
apaga só <claude>/projects/<slug>/<uuid>.jsonl e a pasta <uuid>/ (subagentes) de UM elo "anterior" da corrente da gestora
(gestora_troca.py) do MESMO projeto, e só quando TUDO abaixo vale, conferido de novo logo antes de cada remoção:

  * o dono autorizou ESTE projeto uma vez (clique na página ou `gestora limpeza <projeto> --autorizar --confirmar`);
  * o elo existe na corrente, está "anterior" e saiu de uso (fim) há mais de N dias (padrão 7, gestora_rotacao.dias_limpeza);
  * não é a transcrição gestora atual do config nem um elo "atual"; o id tem o formato de uuid; nada de "..", barra ou link;
  * o arquivo e a pasta ficam EXATAMENTE em <claude>/projects/<slug>/ (caminho resolvido), sem link simbólico nem junção;
  * o snapshot de backup MAIS NOVO está completo, passa no backup.conferir (relê o zip) e o manifesto dele tem cada arquivo
    com o MESMO sha256 do arquivo no disco (prova de que está guardado).
Capítulos, decisões e a corrente ficam para sempre. Cada remoção vai para ~/.cerebro/projetos/<slug>/apagamentos.jsonl.
Roda sozinha na rotina do servidor (no máximo uma vez por dia) depois da autorização.
"""
import hashlib
import os
import re
import time
from pathlib import Path

from . import armazem, config

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SLUG = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")
UM_DIA = 86400


class ApagarRecusado(ValueError):
    """Alguma conferência falhou: nada foi apagado."""


def _gt():
    from . import gestora_troca
    return gestora_troca


def autorizado(slug, cfg=None):
    cfg = cfg if cfg is not None else config.ler_config()
    return bool(_gt().parametros(cfg)["apagar_autorizado"].get(slug))


def autorizar(slug, confirmar=False, ligar=True, agora=None):
    """Liga (ou desliga) a remoção automática das transcrições antigas da gestora DESTE projeto. Ligar exige confirmar=True."""
    if not SLUG.match(slug or ""):
        raise ValueError("projeto inválido")
    if ligar and confirmar is not True:
        raise ApagarRecusado("autorizar precisa do sim do dono (clique na página ou --confirmar)")
    agora = agora or time.time()

    def mudar(c):
        aut = c.setdefault("gestora_rotacao", {}).setdefault("apagar_autorizado", {})
        if ligar:
            aut[slug] = agora
        else:
            aut.pop(slug, None)
    config.atualizar_config(mudar)
    return autorizado(slug)


# ---------------------------------------------------------------------------------------------------------------
# Conferências
# ---------------------------------------------------------------------------------------------------------------
def _eh_link(p):
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for pedaco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(pedaco)
    return h.hexdigest()


def _pasta_projeto(slug):
    """<claude>/projects/<slug>, conferida: nome válido, existe, não é link e fica direto dentro de projects."""
    if not SLUG.match(slug or "") or slug in (".", ".."):
        raise ApagarRecusado("projeto inválido")
    base = Path(config.PROJETOS_CLAUDE)
    pasta = base / slug
    if _eh_link(base) or _eh_link(pasta) or not pasta.is_dir():
        raise ApagarRecusado("a pasta do projeto não existe ou é um atalho (link)")
    if pasta.resolve().parent != base.resolve():
        raise ApagarRecusado("a pasta do projeto fica fora de projects")
    return pasta


def candidatos(slug, cfg=None, agora=None):
    """Elos 'anterior' deste projeto fora de uso há mais de N dias, que não são a gestora atual (sem olhar o backup)."""
    gt = _gt()
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    dias = gt.parametros(cfg)["dias_limpeza"]
    atual = gt._gestora(slug, cfg).get("conversa", "")
    saida = []
    for e in gt.corrente(slug, cfg, agora)["elos"]:
        if e.get("estado") != "anterior" or not e.get("fim") or e["conversa"] == atual or agora - e["fim"] <= dias * UM_DIA:
            continue
        if not UUID.match(e["conversa"]):
            continue
        if not (Path(config.PROJETOS_CLAUDE) / slug / f"{e['conversa']}.jsonl").is_file():
            continue
        saida.append({"conversa": e["conversa"], "fim": e["fim"], "titulo": e.get("titulo", ""), "capitulo": e.get("capitulo", "")})
    return saida


def _alvos(pasta, conversa):
    """[(caminho, rel_no_zip)] dos arquivos a apagar e [pastas] (da mais funda para a raiz). Recusa link em qualquer ponto."""
    arq = pasta / f"{conversa}.jsonl"
    if _eh_link(arq) or not arq.is_file():
        raise ApagarRecusado("a transcrição não existe ou é um atalho (link)")
    if arq.resolve().parent != pasta.resolve():
        raise ApagarRecusado("a transcrição fica fora da pasta do projeto")
    arquivos, pastas = [(arq, f"{conversa}.jsonl")], []
    sub = pasta / conversa
    if sub.exists() or _eh_link(sub):
        if _eh_link(sub) or not sub.is_dir() or sub.resolve().parent != pasta.resolve():
            raise ApagarRecusado("a pasta de subagentes é um atalho ou fica fora do projeto")
        for raiz, dirs, nomes in os.walk(sub, topdown=False, followlinks=False):
            r = Path(raiz)
            for n in nomes:
                f = r / n
                if _eh_link(f) or not f.is_file():
                    raise ApagarRecusado(f"{f.name}: atalho (link) ou arquivo especial dentro da pasta de subagentes")
                arquivos.append((f, f.relative_to(pasta).as_posix()))
            for n in dirs:
                if _eh_link(r / n):
                    raise ApagarRecusado("atalho (link) dentro da pasta de subagentes")
            pastas.append(r)
    return arquivos, pastas


_conferidos = {}       # (nome, tamanho, mtime) -> ok? (backup.conferir relê o zip inteiro: uma vez por snapshot)


def prova_backup(slug, arquivos):
    """Snapshot mais novo conferido + manifesto com o mesmo sha256 de cada arquivo. Devolve o nome do snapshot ou levanta."""
    from . import backup
    try:
        base = backup.pasta_backup()
        completos = backup.listar(base)[0] if base.is_dir() else []
    except (OSError, backup.BackupErro) as e:
        raise ApagarRecusado(f"backup indisponível: {e}") from None
    if not completos:
        raise ApagarRecusado("não há backup completo")
    novo = completos[0]
    p = base / novo["nome"]
    try:
        st = p.stat()
    except OSError:
        raise ApagarRecusado("o backup mais novo sumiu") from None
    chave = (novo["nome"], st.st_size, st.st_mtime)
    if chave not in _conferidos:
        try:
            _conferidos[chave] = bool(backup.conferir(novo["nome"], base).get("ok"))
        except (OSError, backup.BackupErro):
            _conferidos[chave] = False
    if not _conferidos[chave]:
        raise ApagarRecusado(f"o backup mais novo ({novo['nome']}) não passou na conferência")
    man = backup.ler_manifesto(p) or {}
    shas = {e.get("arq"): e.get("sha256") for e in man.get("arquivos", []) if isinstance(e, dict)}
    for f, rel in arquivos:
        esperado = shas.get(f"claude/projects/{slug}/{rel}")
        if not esperado:
            raise ApagarRecusado(f"{rel} não está no backup mais novo")
        if _sha(f) != esperado:
            raise ApagarRecusado(f"{rel} mudou depois do backup mais novo (sha256 diferente)")
    return novo["nome"]


def conferir(slug, conversa, cfg=None, agora=None):
    """Todas as conferências, sem apagar nada. Devolve {arquivos, pastas, snapshot} ou levanta ApagarRecusado."""
    gt = _gt()
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    if not UUID.match(conversa or ""):
        raise ApagarRecusado("id de transcrição inválido")
    pasta = _pasta_projeto(slug)
    if conversa == gt._gestora(slug, cfg).get("conversa"):
        raise ApagarRecusado("é a transcrição gestora ATUAL")
    elo = next((e for e in gt.corrente(slug, cfg, agora)["elos"] if e["conversa"] == conversa), None)
    if elo is None:
        raise ApagarRecusado("essa transcrição não está na corrente da gestora deste projeto")
    if elo.get("estado") != "anterior":
        raise ApagarRecusado(f"o elo está '{elo.get('estado')}', não 'anterior'")
    dias = gt.parametros(cfg)["dias_limpeza"]
    if not elo.get("fim") or agora - elo["fim"] <= dias * UM_DIA:
        raise ApagarRecusado(f"saiu de uso há menos de {dias} dias")
    arquivos, pastas = _alvos(pasta, conversa)
    snap = prova_backup(slug, arquivos)
    return {"arquivos": arquivos, "pastas": pastas, "snapshot": snap, "pasta": pasta}


def _remover_arquivo(f, pasta, conversa, sha_esperado):
    """Última conferência de UM arquivo e a remoção. Só arquivo comum, dentro do projeto, com o sha conferido."""
    rp = f.resolve()
    if _eh_link(f) or not f.is_file():
        raise ApagarRecusado(f"{f.name} virou atalho ou sumiu")
    dentro = rp.parent == pasta.resolve() and rp.name == f"{conversa}.jsonl"
    if not dentro:
        try:
            rp.relative_to((pasta / conversa).resolve())
            dentro = True
        except ValueError:
            dentro = False
    if not dentro:
        raise ApagarRecusado(f"{f.name} fica fora do que pode ser apagado")
    if _sha(f) != sha_esperado:
        raise ApagarRecusado(f"{f.name} mudou durante a limpeza")
    os.remove(rp)


def apagar(slug, conversa, quem="rotina", cfg=None, agora=None):
    """Apaga a transcrição antiga (e a pasta de subagentes) de UM elo, depois de todas as conferências. Exige a autorização."""
    gt = _gt()
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    if not autorizado(slug, cfg):
        raise ApagarRecusado("o dono ainda não autorizou a limpeza neste projeto")
    c = conferir(slug, conversa, cfg, agora)
    shas = {str(f): _sha(f) for f, _ in c["arquivos"]}
    c2 = conferir(slug, conversa, cfg, agora)                       # de novo, logo antes de apagar
    if sorted(str(f) for f, _ in c2["arquivos"]) != sorted(shas):
        raise ApagarRecusado("os arquivos mudaram entre as conferências")
    for f, _ in sorted(c2["arquivos"], key=lambda x: -len(str(x[0]))):
        _remover_arquivo(f, c2["pasta"], conversa, shas[str(f)])
    for d in c2["pastas"]:                                         # da mais funda para a raiz; só pasta VAZIA
        try:
            if not _eh_link(d) and d.resolve() != c2["pasta"].resolve():
                os.rmdir(d)
        except OSError:
            pass

    def mudar(x):
        x = gt._normalizar(x)
        for e in x["elos"]:
            if e["conversa"] == conversa:
                e.update(estado="apagada", apagada_em=agora, apagada_por=quem, snapshot=c2["snapshot"])
        gt._log(x, "transcrição antiga apagada (backup conferido)", agora, conversa=conversa, quem=quem)
        return x

    armazem.atualizar_json(gt._arq_corrente(slug), gt._vazio(), mudar)
    armazem.anexar_jsonl(gt.arq_apagamentos(slug), {"em": agora, "conversa": conversa, "quem": quem, "snapshot": c2["snapshot"],
                                                    "arquivos": [r for _, r in c2["arquivos"]]})
    return {"conversa": conversa, "snapshot": c2["snapshot"], "arquivos": len(c2["arquivos"])}


def _arq_estado():
    return config.CASA / "retencao.json"


def rodar(cfg=None, agora=None, forcar=False):
    """Rotina: nos projetos autorizados, apaga os candidatos que passam em todas as conferências. No máximo 1 vez por dia."""
    from . import projetos
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    aut = _gt().parametros(cfg)["apagar_autorizado"]
    if not aut:
        return []
    est = armazem.ler_json(_arq_estado(), {}) or {}
    if not forcar and agora - (est.get("ultima") or 0) < UM_DIA:
        return []
    feitos, recusas = [], []
    conhecidos = {p["slug"] for p in projetos.descobrir()}
    for slug in sorted(aut):
        if slug not in conhecidos:
            continue
        for c in candidatos(slug, cfg, agora):
            try:
                feitos.append({"projeto": slug, **apagar(slug, c["conversa"], "rotina", cfg, agora)})
            except (ApagarRecusado, OSError) as e:
                recusas.append({"projeto": slug, "conversa": c["conversa"], "motivo": str(e)[:200]})
    armazem.gravar_json(_arq_estado(), {"ultima": agora, "feitos": feitos[-50:], "recusas": recusas[-50:]})
    return feitos
