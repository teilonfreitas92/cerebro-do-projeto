"""Cópia de segurança (backup) diária e rotativa das conversas e da memória do Claude Code e dos dados do Cérebro, e a restauração.

Lição de 29/10 (um teste apagou ~/.claude/projects inteiro): o que não tem cópia some de vez. Então, uma vez por dia:

  * O QUE copia: ~/.claude/projects (conversas JSONL + memória de todos os projetos) e ~/.cerebro (menos os caches que o
    Cérebro refaz sozinho: índices, página do mapa, travas, token e servidor.json).
  * ONDE: FORA de ~/.cerebro e de ~/.claude (se alguém apagar uma delas, o backup sobrevive). Padrão:
    ~\\CerebroBackup; muda em config.json > backup > pasta (caminho COMPLETO; pasta que já tem outras coisas só
    é aceita se se chamar CerebroBackup ou tiver a marca .cerebro-backup que o Cérebro grava nela); nos testes, CEREBRO_BACKUP.
  * FORMATO: um .zip por backup (AAAA-MM-DD.zip; do 2º do mesmo dia em diante, AAAA-MM-DD_HHMMSS.zip). Um snapshot que já
    existe NUNCA é sobrescrito nem renomeado (lição da revisão: o 2º backup do dia trocava o bom, que estava protegido). Escolhido no lugar de uma pasta por dia porque as conversas são texto JSONL que
    comprime muito (tipicamente 5 a 10 vezes): 7 dias em zip ocupam menos que 1 dia copiado solto. O zip também guarda um
    CRC de cada arquivo e é UM arquivo só, o que deixa o "pronto ou não pronto" simples: ele é escrito como
    AAAA-MM-DD.zip.parcial e só vira AAAA-MM-DD.zip (troca de nome atômica) depois de completo e conferido.
  * MANIFESTO: dentro do zip, _manifesto.json (último item gravado) com cada arquivo, tamanho, data e SHA-256. Zip sem
    manifesto ou com nome fora do padrão NÃO conta como backup. "Conferir" relê tudo e compara com o manifesto.
  * ARQUIVO ABERTO pelo Claude Code: lê só até o tamanho visto no começo (conversa que cresce durante a cópia fica com o
    trecho que já existia); se o Windows negar a leitura, registra em "falhas" no manifesto e segue com os outros.
  * ROTAÇÃO: guarda os snapshots dos últimos N dias que TÊM backup (padrão 7, config.json > backup > manter_dias): com o PC
    desligado uma semana, os 7 de antes continuam lá. Dentro de um dia guardado ficam o primeiro e o último do dia (os do meio
    saem; com algum snapshot protegido, nenhum do meio sai). Só remove nomes no padrão dos snapshots, só dentro da pasta de
    backup e sempre por config.remover_em(); nunca remove o mais novo nem um protegido; não roda se o backup novo falhou.
  * ENCOLHEU: compara o backup novo com o último que NÃO encolheu (ordem pela hora em que foi criado). Encolheu se tiver menos
    da metade dos arquivos ou dos bytes no total, se um projeto que existia sumiu ou caiu a menos da metade, ou se a memória
    (memory/) de um projeto sumiu ou caiu a menos da metade. Aí o backup de referência fica PROTEGIDO (não entra na rotação)
    até a pessoa conferir e liberar (com confirmação), e a caixa "Precisa de você" avisa.

Restaurar NUNCA apaga nada: arquivo que falta hoje é copiado de volta; arquivo que existe e é diferente só é trocado se a
pessoa marcar, e a versão atual vai antes para ~/.cerebro/copias/restauracao-<data>/ (ou para a pasta de backup, se
~/.cerebro sumiu). Conversa que só cresceu desde o backup (o arquivo atual começa com o conteúdo do backup) nunca é trocada:
não haveria nada a recuperar. Escrever em ~/.claude/projects só acontece aqui, com confirmar=True (clique ou --confirmar).
"""
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import config

MANIFESTO = "_manifesto.json"
NOME_SNAPSHOT = re.compile(r"^(\d{4}-\d{2}-\d{2})(_\d{6})?\.zip$")
NOME_PARCIAL = re.compile(r"^\d{4}-\d{2}-\d{2}(_\d{6})?\.zip\.parcial$")
AREAS = ("claude", "cerebro")                     # claude/projects/... e cerebro/... dentro do zip
CACHES_NOMES = {"indice.json", "dados.js", ".estado.json.gz", "servidor.json", "token"}
CACHES_SUFIXOS = (".lock", ".tmp", ".parcial")
MANTER_PADRAO = 7
DIAS_ALERTA = 2                                   # "Precisa de você" avisa se o último backup tem mais que isso
PEDACO = 1024 * 1024
ARQ_ESTADO = "estado.json"
ARQ_TRAVA = ".backup.lock"
TRAVA_VELHA = 3 * 3600
MARCA = ".cerebro-backup"                         # arquivo-marca: "esta pasta é de backup do Cérebro"
NOME_PADRAO = "CerebroBackup"
MINIMO_PROJETO = (2, 4096)                        # projeto menor que isso (arquivos, bytes) não conta para "encolheu"


class BackupErro(Exception):
    """Algo impede o backup ou a restauração (pasta inválida, outro backup rodando, snapshot que não confere...)."""


# ---------------------------------------------------------------------------------------------------------------
# Pastas
# ---------------------------------------------------------------------------------------------------------------
def _dentro(filho, pai):
    try:
        Path(filho).resolve().relative_to(Path(pai).resolve())
        return True
    except ValueError:
        return False


def pasta_padrao():
    """~/CerebroBackup. NÃO usa AppData de propósito: programas instalados como pacote do Windows (MSIX, ex.: o app do Claude)
    gravam em AppData numa cópia virtual só deles; a tarefa agendada e o painel veriam outra pasta e o backup ficaria dividido."""
    return Path.home() / "CerebroBackup"


def _cfg_backup(cfg=None):
    """config.json > backup, lido SEM criar ~/.cerebro (o desinstalador e a restauração podem rodar com ela apagada)."""
    if cfg is None:
        try:
            cfg = json.loads((Path(config.CASA) / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    b = cfg.get("backup") if isinstance(cfg, dict) else None
    return b if isinstance(b, dict) else {}


def pasta_backup(cfg=None):
    """Onde ficam os snapshots: CEREBRO_BACKUP (testes) > config.json backup.pasta > padrão. Recusa pasta dentro de ~/.cerebro ou
    de ~/.claude (e pasta que contenha uma delas): o backup precisa sobreviver se alguém apagar qualquer uma das duas.
    Recusa caminho relativo (a tarefa agendada roda com outra pasta atual: os zips iriam parar dentro de um repositório) e, na
    pasta escolhida em config.json, uma pasta que já tem outras coisas e não é do Cérebro (ver eh_pasta_do_cerebro)."""
    escolhida = os.environ.get("CEREBRO_BACKUP")
    da_config = not escolhida
    if not escolhida:
        escolhida = str(_cfg_backup(cfg).get("pasta") or "").strip()
    if escolhida and not Path(escolhida).is_absolute():
        raise BackupErro(f"a pasta de backup precisa ser um caminho completo (por exemplo D:\\CerebroBackup), não {escolhida!r}")
    base = Path(escolhida) if escolhida else pasta_padrao()
    base = Path(os.path.abspath(str(base)))
    for nome, outra in (("~/.cerebro", config.CASA), ("~/.claude", config.CLAUDE)):
        if _dentro(base, outra) or _dentro(outra, base):
            raise BackupErro(f"a pasta de backup ({base}) não pode ficar dentro de {nome} nem conter essa pasta")
    if base.resolve() == Path(base.anchor).resolve():
        raise BackupErro(f"a pasta de backup não pode ser a raiz do disco ({base})")
    if da_config and escolhida and not eh_pasta_do_cerebro(base):
        raise BackupErro(f"a pasta {base} já tem outros arquivos e não é uma pasta de backup do Cérebro: escolha uma pasta vazia "
                         f"(ou chamada {NOME_PADRAO}) em config.json > backup > pasta")
    return base


def eh_pasta_do_cerebro(base):
    """Pasta aceitável para o backup: ainda não existe, está vazia, chama CerebroBackup ou tem a marca do Cérebro."""
    base = Path(base)
    try:
        if not base.exists():
            return True
        if not base.is_dir():
            return False
        return base.name == NOME_PADRAO or (base / MARCA).is_file() or not any(base.iterdir())
    except OSError:
        return False


def _preparar_pasta(base):
    """Cria a pasta de backup com a marca do Cérebro (sem a marca, o desinstalador não apaga nada nela)."""
    base.mkdir(parents=True, exist_ok=True)
    marca = base / MARCA
    if not marca.exists():
        marca.write_text("Pasta de backup do Cérebro do Projeto (não apague este arquivo).\n", encoding="utf-8")


def manter_dias(cfg=None):
    v = _cfg_backup(cfg).get("manter_dias", MANTER_PADRAO)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 365 else MANTER_PADRAO


def _origens():
    """(área, pasta de origem) na ordem em que entram no zip."""
    return [("claude/projects", config.PROJETOS_CLAUDE), ("cerebro", config.CASA)]


def _eh_cache(rel_partes):
    nome = rel_partes[-1]
    return nome in CACHES_NOMES or nome.endswith(CACHES_SUFIXOS)


def _arquivos_de(area, origem, excluir):
    """Arquivos de uma origem como (rel posix, caminho). Pula caches refazíveis, links e a própria pasta de backup."""
    origem = Path(origem)
    if not origem.is_dir():
        return
    for raiz, pastas, arquivos in os.walk(origem):
        raiz_p = Path(raiz)
        pastas[:] = sorted(d for d in pastas if not (raiz_p / d).is_symlink() and not any(_dentro(raiz_p / d, x) for x in excluir))
        for nome in sorted(arquivos):
            p = raiz_p / nome
            partes = p.relative_to(origem).parts
            if area == "cerebro" and _eh_cache(partes):
                continue
            if p.is_symlink():
                continue
            yield "/".join(partes), p


def medir_origens():
    """Só lê tamanhos (nada é copiado): quantos arquivos e bytes o backup levaria hoje, por área."""
    saida = {}
    try:
        excluir = [pasta_backup()]
    except BackupErro:
        excluir = []
    for area, origem in _origens():
        n = b = 0
        for _rel, p in _arquivos_de(area.split("/")[0], origem, excluir):
            try:
                b += p.stat().st_size
                n += 1
            except OSError:
                continue
        saida[area] = {"arquivos": n, "bytes": b, "pasta": str(origem)}
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Estado (fica NA pasta de backup: sobrevive se ~/.cerebro sumir)
# ---------------------------------------------------------------------------------------------------------------
def _ler_estado(base):
    try:
        d = json.loads((base / ARQ_ESTADO).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_estado(base, estado):
    _preparar_pasta(base)
    tmp = base / (ARQ_ESTADO + ".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, base / ARQ_ESTADO)


class _Trava:
    """Um backup por vez (o botão e a tarefa agendada podem coincidir). Trava velha (processo morto há horas) é descartada."""

    def __init__(self, base):
        self.base = base
        self.arq = base / ARQ_TRAVA
        self.minha = False

    def __enter__(self):
        _preparar_pasta(self.base)
        for _ in range(2):
            try:
                fd = os.open(self.arq, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode("ascii"))
                os.close(fd)
                self.minha = True
                return self
            except FileExistsError:
                try:
                    velha = time.time() - self.arq.stat().st_mtime > TRAVA_VELHA
                except OSError:
                    velha = True
                if not velha:
                    raise BackupErro("já há um backup em andamento; espere ele terminar") from None
                config.remover_em(self.base, self.arq, somente_nomes=(ARQ_TRAVA,))
        raise BackupErro("não consegui travar a pasta de backup")

    def __exit__(self, *_):
        if self.minha:
            try:
                config.remover_em(self.base, self.arq, somente_nomes=(ARQ_TRAVA,))
            except (OSError, config.RemocaoRecusada):
                pass


# ---------------------------------------------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------------------------------------------
def ler_manifesto(caminho):
    """Manifesto de um snapshot, ou None se o zip estiver incompleto/quebrado/sem manifesto (não conta como backup)."""
    try:
        with zipfile.ZipFile(caminho) as zf:
            with zf.open(MANIFESTO) as f:
                m = json.loads(f.read().decode("utf-8"))
        return m if isinstance(m, dict) and isinstance(m.get("arquivos"), list) else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, EOFError):
        return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def listar(base=None):
    """Snapshots completos (mais novo primeiro: pelo dia e, no mesmo dia, pela hora em que foi criado) e os que não contam
    (incompletos ou quebrados)."""
    base = base or pasta_backup()
    completos, incompletos = [], []
    if not base.is_dir():
        return completos, incompletos
    for p in sorted(base.iterdir(), key=lambda x: x.name, reverse=True):
        if NOME_PARCIAL.match(p.name):
            incompletos.append({"nome": p.name, "motivo": "backup interrompido (não terminou)"})
            continue
        m = NOME_SNAPSHOT.match(p.name)
        if not m or not p.is_file():
            continue
        man = ler_manifesto(p)
        if man is None:
            incompletos.append({"nome": p.name, "motivo": "zip sem manifesto ou quebrado"})
            continue
        completos.append({"nome": p.name, "data": m.group(1), "criado_em": man.get("criado_em"), "bytes_zip": p.stat().st_size,
                          "bytes": man.get("total_bytes", 0), "arquivos": man.get("total_arquivos", 0),
                          "falhas": len(man.get("falhas") or []), "projetos": sorted(_projetos_do_manifesto(man))})
    completos.sort(key=lambda s: (s["data"], _num(s["criado_em"]), s["nome"]), reverse=True)
    return completos, incompletos


def _projetos_do_manifesto(man):
    return {e["arq"].split("/")[2] for e in man.get("arquivos", []) if e.get("arq", "").startswith("claude/projects/") and e["arq"].count("/") >= 3}


def _caminho_snapshot(base, nome):
    if not NOME_SNAPSHOT.match(nome or ""):
        raise BackupErro(f"nome de snapshot inválido: {nome!r}")
    p = base / nome
    if not p.is_file():
        raise BackupErro(f"snapshot não encontrado: {nome}")
    return p


def achar_snapshot(ref, base=None):
    """Aceita 'AAAA-MM-DD', 'AAAA-MM-DD.zip' ou o nome com hora. Para a data, vale o mais novo daquele dia."""
    base = base or pasta_backup()
    completos, _ = listar(base)
    ref = (ref or "").strip()
    for s in completos:
        if s["nome"] == ref:
            return s["nome"]
    do_dia = [s["nome"] for s in completos if s["data"] == ref]          # só a data: o mais novo do dia (mais de um no dia)
    if do_dia:
        return do_dia[0]
    for s in completos:
        if s["nome"] == ref + ".zip":
            return s["nome"]
    raise BackupErro(f"não há backup completo para {ref!r}. Veja: python cerebro_cli.py backup --listar")


def _sha_e_copia(origem, destino_escrita, limite):
    """Lê até 'limite' bytes de origem, escreve em destino_escrita (arquivo aberto) e devolve (sha256, bytes)."""
    h = hashlib.sha256()
    n = 0
    with open(origem, "rb") as f:
        while n < limite:
            bloco = f.read(min(PEDACO, limite - n))
            if not bloco:
                break
            h.update(bloco)
            destino_escrita.write(bloco)
            n += len(bloco)
    return h.hexdigest(), n


def _info_zip(arcname, mtime):
    t = time.localtime(max(mtime, 315532800 + 86400))       # zip não guarda datas antes de 1980
    zi = zipfile.ZipInfo(arcname, date_time=t[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    return zi


def _escrever_zip(destino, agora):
    """Escreve o zip inteiro em 'destino' e devolve o manifesto."""
    excluir = [destino.parent]
    arquivos, falhas = [], []
    total = 0
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for area, origem in _origens():
            for rel, p in _arquivos_de(area.split("/")[0], origem, excluir):
                arc = f"{area}/{rel}"
                try:
                    st = p.stat()
                    with zf.open(_info_zip(arc, st.st_mtime), "w", force_zip64=True) as w:
                        sha, n = _sha_e_copia(p, w, st.st_size)
                except OSError as e:                # arquivo travado, apagado no meio, sem permissão: registra e segue
                    falhas.append({"arq": arc, "erro": f"{type(e).__name__}: {str(e)[:160]}"})
                    continue
                arquivos.append({"arq": arc, "tam": n, "sha256": sha, "mtime": st.st_mtime})
                total += n
        man = {"versao": 1, "criado_em": agora, "data": time.strftime("%Y-%m-%d", time.localtime(agora)),
               "origens": {a: str(o) for a, o in _origens()}, "total_arquivos": len(arquivos), "total_bytes": total,
               "arquivos": arquivos, "falhas": falhas}
        zf.writestr(_info_zip(MANIFESTO, agora), json.dumps(man, ensure_ascii=False, separators=(",", ":")))
    return man


def conferir(nome, base=None):
    """Relê o snapshot inteiro: CRC do zip + SHA-256 de cada arquivo contra o manifesto. Devolve {ok, problemas, conferidos}."""
    base = base or pasta_backup()
    p = _caminho_snapshot(base, nome)
    return _conferir_arquivo(p)


def _conferir_arquivo(p):
    man = ler_manifesto(p)
    if man is None:
        return {"ok": False, "problemas": ["zip sem manifesto ou quebrado"], "conferidos": 0}
    problemas = []
    try:
        with zipfile.ZipFile(p) as zf:
            nomes = set(zf.namelist())
            for e in man["arquivos"]:
                if e["arq"] not in nomes:
                    problemas.append(f"falta no zip: {e['arq']}")
                    continue
                h = hashlib.sha256()
                with zf.open(e["arq"]) as f:
                    for bloco in iter(lambda f=f: f.read(PEDACO), b""):
                        h.update(bloco)
                if h.hexdigest() != e["sha256"]:
                    problemas.append(f"conteúdo diferente do manifesto: {e['arq']}")
    except (OSError, zipfile.BadZipFile, EOFError) as ex:
        problemas.append(f"zip ilegível: {type(ex).__name__}: {ex}")
    return {"ok": not problemas, "problemas": problemas[:50], "conferidos": len(man["arquivos"])}


def _medidas(man):
    """Do manifesto: por projeto, [arquivos, bytes] de tudo e, à parte, da memória (claude/projects/<slug>/memory/...)."""
    projetos, memoria = {}, {}
    for e in (man or {}).get("arquivos") or []:
        partes = str(e.get("arq", "")).split("/") if isinstance(e, dict) else []
        if partes[:2] != ["claude", "projects"] or len(partes) < 4:
            continue
        tam = _num(e.get("tam"))
        alvos = [projetos] + ([memoria] if len(partes) > 4 and partes[3] == "memory" else [])
        for alvo in alvos:
            m = alvo.setdefault(partes[2], [0, 0])
            m[0] += 1
            m[1] += tam
    return projetos, memoria


def _encolheu(novo, anterior):
    """Sinais de que algo foi apagado desde o backup de referência ('anterior' = manifesto dele). Devolve a lista de motivos
    (vazia = não encolheu): total com menos da metade dos arquivos ou bytes; projeto que sumiu ou caiu a menos da metade;
    memória de um projeto que sumiu ou caiu a menos da metade. Comparar só o total deixava passar um projeto inteiro apagado."""
    if not anterior:
        return []
    motivos = []
    na, nb = _num(anterior.get("total_arquivos")), _num(anterior.get("total_bytes"))
    if (na >= 4 and novo["total_arquivos"] < na / 2) or (nb >= 4096 and novo["total_bytes"] < nb / 2):
        motivos.append(f"total: {na} → {novo['total_arquivos']} arquivos")
    proj_a, mem_a = _medidas(anterior)
    proj_n, mem_n = _medidas(novo)
    for slug, (a, b) in sorted(proj_a.items()):
        if a < MINIMO_PROJETO[0] and b < MINIMO_PROJETO[1]:
            continue                                  # projeto minúsculo: ruído
        n, nbytes = proj_n.get(slug, (0, 0))
        if n == 0:
            motivos.append(f"o projeto {slug} sumiu ({a} arquivos)")
        elif n < a / 2 or nbytes < b / 2:
            motivos.append(f"o projeto {slug} caiu de {a} para {n} arquivos")
    for slug, (a, b) in sorted(mem_a.items()):
        n, nbytes = mem_n.get(slug, (0, 0))
        if n == 0:
            motivos.append(f"a memória do projeto {slug} sumiu ({a} arquivos)")
        elif (a >= 2 and n < a / 2) or (b >= 1024 and nbytes < b / 2):
            motivos.append(f"a memória do projeto {slug} caiu de {a} para {n} arquivos")
    return motivos


def _nome_livre(base, dia, agora, protegidos):
    """Nome do snapshot novo: AAAA-MM-DD.zip se o dia ainda não tem; senão AAAA-MM-DD_HHMMSS.zip (andando um segundo se já
    existir). NUNCA devolve um nome que já existe nem um protegido: snapshot existente não é sobrescrito."""
    candidatos = [f"{dia}.zip"]
    for i in range(120):
        t = time.localtime(agora + i)
        if time.strftime("%Y-%m-%d", t) != dia:
            break
        candidatos.append(f"{dia}_{time.strftime('%H%M%S', t)}.zip")
    for nome in candidatos:
        if nome not in protegidos and not (base / nome).exists() and not (base / nome).is_symlink():
            return base / nome
    raise BackupErro(f"não achei um nome livre para o backup de {dia} (backups demais no mesmo minuto?)")


def _trocar_nome_sem_sobrescrever(base, parcial, destino):
    """parcial -> destino de forma atômica e SEM sobrescrever: se o destino aparecer no meio, falha (FileExistsError)."""
    if os.name == "nt":
        os.rename(parcial, destino)                   # no Windows, rename recusa destino existente
    else:
        os.link(parcial, destino)                     # link também recusa destino existente
        config.remover_em(base, parcial, somente_nomes=(parcial.name,))


def fazer_backup(agora=None, so_se_faltar_hoje=False):
    """Faz o snapshot de hoje. Devolve um resumo. 'so_se_faltar_hoje' (rotina agendada ao fazer logon): pula se hoje já tem.
    Erro grave levanta BackupErro (e fica registrado no estado); arquivo travado não é erro grave (vai em 'falhas')."""
    agora = agora or time.time()
    base = pasta_backup()
    dia = time.strftime("%Y-%m-%d", time.localtime(agora))
    completos, _ = listar(base) if base.is_dir() else ([], [])
    if so_se_faltar_hoje and any(s["data"] == dia for s in completos):
        return {"ok": True, "pulado": True, "motivo": f"já existe o backup de {dia}"}
    inicio = time.time()
    with _Trava(base):
        estado = _ler_estado(base)
        completos, _ = listar(base)                   # de novo, já com a trava: outro backup pode ter terminado
        nomes = {s["nome"] for s in completos}
        protegidos = [x for x in (estado.get("protegidos") or []) if isinstance(x, str) and x in nomes]
        encolhidos = [x for x in (estado.get("encolhidos") or []) if isinstance(x, str) and x in nomes]
        parcial = base / f"{dia}.zip.parcial"
        try:
            man = _escrever_zip(parcial, agora)
            conf = _conferir_arquivo(parcial)
            if not conf["ok"]:
                raise BackupErro("o zip recém-escrito não confere com o manifesto: " + "; ".join(conf["problemas"][:3]))
            destino = _nome_livre(base, dia, agora, protegidos)
            _trocar_nome_sem_sobrescrever(base, parcial, destino)
        except Exception as e:
            try:
                config.remover_em(base, parcial, somente_nomes=(parcial.name,))
            except (OSError, config.RemocaoRecusada):
                pass
            estado["ultimo"] = {"em": agora, "ok": False, "erro": f"{type(e).__name__}: {str(e)[:300]}"}
            _gravar_estado(base, estado)
            raise BackupErro(f"o backup falhou: {e}") from e
        # referência = o mais novo que NÃO encolheu (um backup já menor não serve de régua para o seguinte)
        anterior = next((s for s in completos if s["nome"] not in encolhidos), completos[0] if completos else None)
        motivos = _encolheu(man, ler_manifesto(base / anterior["nome"]) if anterior else None)
        encolheu = bool(motivos)
        protegeu_agora = False
        if encolheu:
            encolhidos.append(destino.name)
            if anterior["nome"] not in protegidos:
                protegidos.append(anterior["nome"])
                protegeu_agora = True
        estado.update(protegidos=protegidos, encolhidos=encolhidos, ultimo={
            "em": agora, "ok": True, "nome": destino.name, "bytes_zip": destino.stat().st_size, "bytes": man["total_bytes"],
            "arquivos": man["total_arquivos"], "falhas": man["falhas"][:20], "encolheu": encolheu,
            "duracao": round(time.time() - inicio, 1), "anterior": anterior["nome"] if anterior else None})
        if encolheu:
            estado["encolheu"] = {"em": agora, "nome": destino.name, "anterior": anterior["nome"], "motivos": motivos[:20],
                                  "arquivos": [anterior["arquivos"], man["total_arquivos"]], "bytes": [anterior["bytes"], man["total_bytes"]]}
        _gravar_estado(base, estado)
        # rotação: não roda no backup que acabou de proteger um snapshot (a pessoa ainda não viu o aviso); os protegidos nunca saem
        removidos = [] if protegeu_agora else rodar_rotacao(base, manter_dias(), protegidos)
    return {"ok": True, "nome": destino.name, "arquivos": man["total_arquivos"], "bytes": man["total_bytes"],
            "bytes_zip": destino.stat().st_size, "falhas": man["falhas"], "encolheu": encolheu, "motivos": motivos,
            "removidos": removidos, "duracao": round(time.time() - inicio, 1)}


def remover_snapshot(base, caminho):
    """Apaga UM snapshot. Só nomes no padrão, só diretamente dentro da pasta de backup, sempre pela trava do app."""
    caminho = Path(caminho)
    nome = caminho.name
    if not (NOME_SNAPSHOT.match(nome) or NOME_PARCIAL.match(nome)):
        raise config.RemocaoRecusada(f"recusado: {nome} não é um snapshot do backup")
    if Path(os.path.abspath(str(caminho.parent))).resolve() != Path(base).resolve():
        raise config.RemocaoRecusada(f"recusado: {caminho} está fora da pasta de backup {base}")
    config.remover_em(base, caminho, somente_nomes=(nome,))


def rodar_rotacao(base, manter, protegidos=(), agora=None):
    """Mantém os snapshots dos 'manter' dias mais recentes que têm backup (+ os protegidos). Nunca apaga o mais novo.
    Dentro de um dia mantido ficam o primeiro e o último do dia; os do meio saem, MENOS quando há algum protegido (dia ruim:
    nada sai até a pessoa conferir). Também tira backups interrompidos (.parcial) com mais de 6 h. Devolve os nomes removidos."""
    manter = max(1, int(manter))
    agora = agora or time.time()
    completos, _ = listar(base)
    dias, por_dia = [], {}
    for s in completos:
        if s["data"] not in dias:
            dias.append(s["data"])
        por_dia.setdefault(s["data"], []).append(s["nome"])          # mais novo primeiro
    ficam = set(dias[:manter])
    removidos = []
    for i, s in enumerate(completos):
        if i == 0 or s["nome"] in protegidos:
            continue
        if s["data"] in ficam and (protegidos or s["nome"] in (por_dia[s["data"]][0], por_dia[s["data"]][-1])):
            continue
        remover_snapshot(base, base / s["nome"])
        removidos.append(s["nome"])
    for p in base.iterdir():
        if NOME_PARCIAL.match(p.name):
            try:
                if agora - p.stat().st_mtime > 6 * 3600:
                    remover_snapshot(base, p)
                    removidos.append(p.name)
            except OSError:
                continue
    return removidos


def liberar_protegidos():
    """A pessoa conferiu que a redução foi de propósito: os snapshots protegidos voltam para a rotação normal (e os que
    encolheram passam a valer como referência normal para o próximo backup)."""
    base = pasta_backup()
    estado = _ler_estado(base)
    antes = list(estado.get("protegidos") or [])
    estado["protegidos"] = []
    estado["encolhidos"] = []
    estado.pop("encolheu", None)
    _gravar_estado(base, estado)
    return antes


def resumo():
    """Para a página e a CLI: pasta, último backup, snapshots, protegidos, quanto a origem tem hoje (só tamanhos)."""
    try:
        base = pasta_backup()
    except BackupErro as e:
        return {"erro": str(e), "snapshots": [], "incompletos": []}
    completos, incompletos = listar(base)
    estado = _ler_estado(base)
    return {"pasta": str(base), "manter_dias": manter_dias(), "ultimo": estado.get("ultimo"), "protegidos": estado.get("protegidos") or [],
            "encolheu": estado.get("encolheu"), "snapshots": completos, "incompletos": incompletos,
            "bytes_total": sum(s["bytes_zip"] for s in completos)}


def alertas(agora=None):
    """Itens para a caixa "Precisa de você": backup falhou, está velho (mais de 2 dias), nunca foi feito, ou encolheu."""
    agora = agora or time.time()
    link = "#/config"
    r = resumo()
    if r.get("erro"):
        return [{"nivel": "aviso", "projeto": "", "aba": "", "link": link, "titulo": "Backup: pasta inválida", "texto": r["erro"]}]
    itens = []
    ult = r.get("ultimo") or {}
    novo = r["snapshots"][0] if r["snapshots"] else None
    if ult and not ult.get("ok"):
        itens.append({"nivel": "aviso", "projeto": "", "aba": "", "link": link, "titulo": "O último backup falhou",
                      "texto": (ult.get("erro") or "")[:200] + " Veja Configurações › Backup."})
    if novo is None:
        itens.append({"nivel": "info", "projeto": "", "aba": "", "link": link, "titulo": "Nenhum backup das conversas ainda",
                      "texto": "Faça o primeiro em Configurações › Backup (fica fora de .claude e de .cerebro) e ligue a cópia diária."})
    else:
        idade = agora - (novo.get("criado_em") or 0)
        if idade > DIAS_ALERTA * 86400:
            itens.append({"nivel": "aviso", "projeto": "", "aba": "", "link": link, "titulo": f"Backup atrasado: o último tem {int(idade // 86400)} dias",
                          "texto": "Faça um backup agora em Configurações › Backup e confira se a cópia diária no Windows está ligada."})
    if r.get("protegidos"):
        enc = r.get("encolheu") or {}
        itens.append({"nivel": "aviso", "projeto": "", "aba": "", "link": link, "titulo": "O backup ficou bem menor que o anterior",
                      "texto": f"Confira se alguma conversa ou memória foi apagada ({(enc.get('arquivos') or ['?', '?'])[0]} → "
                               f"{(enc.get('arquivos') or ['?', '?'])[1]} arquivos"
                               + "".join(f"; {m}" for m in (enc.get("motivos") or [])[:3])
                               + f"). O backup de antes ({', '.join(r['protegidos'])}) está guardado e "
                               "não sai na rotação até você liberar em Configurações › Backup."})
    return itens


# ---------------------------------------------------------------------------------------------------------------
# Restauração (nunca apaga nada)
# ---------------------------------------------------------------------------------------------------------------
def _destino(arc):
    """Caminho real de um item do zip, ou None se o nome for suspeito (fora da área, '..', unidade, absoluto)."""
    pp = PurePosixPath(arc)
    partes = pp.parts
    if pp.is_absolute() or any(x in ("", ".", "..") or ":" in x or "\\" in x for x in partes):
        return None
    if partes[:2] == ("claude", "projects") and len(partes) > 2:
        base, resto = config.PROJETOS_CLAUDE, partes[2:]
    elif partes[0] == "cerebro" and len(partes) > 1:
        base, resto = config.CASA, partes[1:]
    else:
        return None
    alvo = Path(base).joinpath(*resto)
    return alvo if _dentro(alvo, base) else None


def _grupo(arc):
    """Projeto (slug) de um item, ou '_cerebro' para os dados do Cérebro."""
    partes = arc.split("/")
    return partes[2] if partes[:2] == ["claude", "projects"] else "_cerebro"


def _eh_memoria(arc):
    partes = arc.split("/")
    return partes[:2] == ["claude", "projects"] and len(partes) > 4 and partes[3] == "memory"


def _sha_arquivo(p, limite=None):
    h = hashlib.sha256()
    n = 0
    with open(p, "rb") as f:
        while limite is None or n < limite:
            bloco = f.read(PEDACO if limite is None else min(PEDACO, limite - n))
            if not bloco:
                break
            h.update(bloco)
            n += len(bloco)
    return h.hexdigest()


def _filtro(man, projeto=None, so_memoria=False):
    """Itens do manifesto que entram (projeto = slug exato, ou trecho que casa um só slug do snapshot)."""
    itens = man["arquivos"]
    if projeto:
        slugs = sorted(_projetos_do_manifesto(man))
        alvo = projeto if projeto in slugs or projeto == "_cerebro" else None
        if alvo is None:
            casam = [s for s in slugs if projeto.lower() in s.lower()]
            if len(casam) != 1:
                raise BackupErro(f"projeto {projeto!r} {'casa com vários' if casam else 'não está'} no backup. Projetos no backup: " + ", ".join(slugs[:30]))
            alvo = casam[0]
        if alvo == "_cerebro":
            itens = [e for e in itens if _grupo(e["arq"]) == "_cerebro"]
        else:
            itens = [e for e in itens if _grupo(e["arq"]) == alvo or e["arq"].startswith(f"cerebro/projetos/{alvo}/")]
    if so_memoria:
        itens = [e for e in itens if _eh_memoria(e["arq"])]
    return itens


def plano(nome, projeto=None, so_memoria=False, base=None):
    """O que mudaria (só lê): por projeto, arquivos que faltam hoje, diferentes, iguais e os que só cresceram depois do backup."""
    base = base or pasta_backup()
    p = _caminho_snapshot(base, nome)
    man = ler_manifesto(p)
    if man is None:
        raise BackupErro(f"o snapshot {nome} está incompleto ou quebrado")
    grupos = {}
    for e in _filtro(man, projeto, so_memoria):
        dest = _destino(e["arq"])
        g = grupos.setdefault(_grupo(e["arq"]), {"grupo": _grupo(e["arq"]), "faltam": [], "diferentes": [], "cresceram": [], "iguais": 0, "suspeitos": []})
        if dest is None:
            g["suspeitos"].append(e["arq"])
            continue
        try:
            tam = dest.stat().st_size if dest.is_file() else None
        except OSError:
            tam = None
        item = {"arq": e["arq"], "tam_backup": e["tam"], "tam_hoje": tam, "memoria": _eh_memoria(e["arq"])}
        if tam is None:
            g["faltam"].append(item)
        elif tam == e["tam"] and _sha_arquivo(dest) == e["sha256"]:
            g["iguais"] += 1
        elif tam > e["tam"] and _sha_arquivo(dest, e["tam"]) == e["sha256"]:
            g["cresceram"].append(item)          # o atual é o backup + o que foi escrito depois: nada a recuperar
        else:
            g["diferentes"].append(item)
    lista = sorted(grupos.values(), key=lambda g: (g["grupo"] == "_cerebro", g["grupo"]))
    return {"snapshot": nome, "criado_em": man.get("criado_em"), "projeto": projeto or "", "so_memoria": bool(so_memoria), "grupos": lista,
            "totais": {k: sum(len(g[k]) for g in lista) for k in ("faltam", "diferentes", "cresceram")} | {"iguais": sum(g["iguais"] for g in lista)}}


def _pasta_copias(agora):
    marca = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(agora))
    if Path(config.CASA).is_dir():
        return Path(config.CASA) / "copias" / f"restauracao-{marca}"
    base = pasta_backup()
    _preparar_pasta(base)
    return base / "copias" / f"restauracao-{marca}"


def _extrair(zf, arc, sha, dest):
    """Escreve o item do zip em dest de forma atômica (arquivo temporário ao lado + troca de nome), conferindo o SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".restaurando")
    h = hashlib.sha256()
    with zf.open(arc) as f, open(tmp, "wb") as w:
        for bloco in iter(lambda: f.read(PEDACO), b""):
            h.update(bloco)
            w.write(bloco)
    if h.hexdigest() != sha:
        raise BackupErro(f"o conteúdo de {arc} não confere com o manifesto (ficou em {tmp.name}, nada foi trocado)")
    os.replace(tmp, dest)


def restaurar(nome, confirmar=False, trocar=(), trocar_diferentes=False, projeto=None, so_memoria=False, agora=None):
    """Restaura SEM APAGAR: copia o que falta; troca um arquivo diferente só se estiver em 'trocar' (ou trocar_diferentes), e
    guarda antes a versão atual em copias/restauracao-<data>/. Exige confirmar=True (clique na página ou --confirmar)."""
    if confirmar is not True:
        raise BackupErro("restaurar escreve em .claude/projects: precisa de confirmação explícita (--confirmar ou o botão da página)")
    agora = agora or time.time()
    base = pasta_backup()
    p = _caminho_snapshot(base, nome)
    conf = _conferir_arquivo(p)
    if not conf["ok"]:
        raise BackupErro("o snapshot não confere com o manifesto; nada foi restaurado: " + "; ".join(conf["problemas"][:3]))
    pl = plano(nome, projeto, so_memoria, base)
    marcados = set(trocar or ())
    man = {e["arq"]: e for e in ler_manifesto(p)["arquivos"]}
    copias = None
    feitos = {"copiados": [], "trocados": [], "pulados": [], "erros": [], "copias": ""}
    with zipfile.ZipFile(p) as zf:
        for g in pl["grupos"]:
            for it in g["faltam"]:
                dest = _destino(it["arq"])
                try:
                    if dest.exists():                       # apareceu depois do plano: não sobrescreve
                        feitos["pulados"].append(it["arq"])
                        continue
                    _extrair(zf, it["arq"], man[it["arq"]]["sha256"], dest)
                    feitos["copiados"].append(it["arq"])
                except (OSError, BackupErro) as e:
                    feitos["erros"].append(f"{it['arq']}: {e}")
            for it in g["diferentes"]:
                if not (trocar_diferentes or it["arq"] in marcados):
                    feitos["pulados"].append(it["arq"])
                    continue
                dest = _destino(it["arq"])
                try:
                    if copias is None:
                        copias = _pasta_copias(agora)
                    guarda = copias.joinpath(*it["arq"].split("/"))
                    guarda.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, guarda)              # a versão de hoje fica guardada ANTES da troca
                    _extrair(zf, it["arq"], man[it["arq"]]["sha256"], dest)
                    feitos["trocados"].append(it["arq"])
                except (OSError, BackupErro) as e:
                    feitos["erros"].append(f"{it['arq']}: {e}")
    feitos["copias"] = str(copias) if copias else ""
    feitos["cresceram"] = pl["totais"]["cresceram"]
    return feitos


ARQS_DO_BACKUP = (ARQ_ESTADO, ARQ_ESTADO + ".tmp", ARQ_TRAVA)
GUARDAR_DA_CASA = ("copias", "ganchos.json")      # copias/ (versões antes de restaurar/editar, settings.json original) e a statusLine antiga


def guardar_copias_da_casa(agora=None):
    """Desinstalar: COPIA (não move, não apaga) ~/.cerebro/copias/ e ~/.cerebro/ganchos.json (onde fica a statusLine que o
    Cérebro trocou) para <pasta de backup>/copias/desinstalacao-<data>/, antes de a casa ser apagada. Devolve a pasta criada
    ou None se não havia nada a guardar. Erro de cópia levanta OSError/BackupErro (aí o desinstalador NÃO apaga a casa)."""
    casa = Path(config.CASA)
    itens = [casa / n for n in GUARDAR_DA_CASA if (casa / n).exists() and not (casa / n).is_symlink()]
    if not itens:
        return None
    base = pasta_backup()
    _preparar_pasta(base)
    marca = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(agora or time.time()))
    destino, n = base / "copias" / f"desinstalacao-{marca}", 1
    while destino.exists():
        n += 1
        destino = base / "copias" / f"desinstalacao-{marca}-{n}"
    destino.mkdir(parents=True)
    for item in itens:
        if item.is_dir():
            shutil.copytree(item, destino / item.name, symlinks=True)
        else:
            shutil.copy2(item, destino / item.name)
    return destino


def apagar_tudo(copias=False):
    """Desinstalar (só com pergunta própria): apaga SÓ o que é do backup dentro da pasta de backup: snapshots completos (nome no
    padrão E manifesto do Cérebro), backups interrompidos (.zip.parcial), estado.json e a trava. A pasta copias/ (versões
    guardadas antes de restaurar e as copiadas da casa na desinstalação) só sai com copias=True (pergunta própria). Qualquer
    outra coisa fica. A pasta só sai se ficar vazia. Recusa (BackupErro) pasta sem nome CerebroBackup e sem a marca do Cérebro:
    com backup.pasta apontando para Documentos, nada de lá é apagado. Cada item passa por config.remover_em(pasta de backup)."""
    base = pasta_backup()
    if not base.is_dir():
        return 0
    if not (base.name == NOME_PADRAO or (base / MARCA).is_file()):
        raise BackupErro(f"recusado: {base} não tem a marca de pasta de backup do Cérebro; se quiser, apague os backups à mão")
    n = 0
    for filho in sorted(base.iterdir()):
        nome = filho.name
        if filho.is_symlink():
            continue
        if filho.is_file() and (NOME_PARCIAL.match(nome) or (NOME_SNAPSHOT.match(nome) and ler_manifesto(filho) is not None)):
            remover_snapshot(base, filho)
        elif filho.is_file() and nome in ARQS_DO_BACKUP:
            config.remover_em(base, filho, somente_nomes=(nome,))
        elif copias and nome == "copias" and filho.is_dir():
            config.remover_em(base, filho, pasta=True, somente_nomes=("copias",))
        else:
            continue                                  # não é do backup (ou é copias/ sem a pergunta própria): fica
        n += 1
    if (base / MARCA).is_file() and not any(f.name != MARCA for f in base.iterdir()):
        config.remover_em(base, base / MARCA, somente_nomes=(MARCA,))       # a marca sai por último, só com a pasta vazia
        try:
            base.rmdir()
        except OSError:
            pass
    return n


def sobras(base=None):
    """O que ficou na pasta de backup e não é do backup (para o desinstalador explicar por que a pasta não sumiu)."""
    base = base or pasta_backup()
    if not base.is_dir():
        return []
    return sorted(f.name for f in base.iterdir() if f.name != MARCA)
