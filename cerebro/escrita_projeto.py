"""Escrita DENTRO de uma pasta de projeto: a única porta do Cérebro para isso (encaixe, agentes, gancho do gitleaks).

Regras (valem para tudo que passa por aqui):
  * Só roda depois do clique do dono numa tela de confirmação (ou da CLI com --confirmar): quem chama confere isso.
  * TRAVA DE CAMINHO: só dentro da pasta do projeto (resolvida), sem '..', sem caminho absoluto, sem passar por link simbólico ou
    junção, nunca dentro de .git (exceções: .git/hooks/pre-commit, a cópia do gancho antigo ao lado dele e .git/info/exclude,
    lista local de ignorados que não vai ao repositório: usada pelo manual do gestor no CLAUDE.local.md), nunca em
    projeto oculto, de "nunca_entrar"/"nunca_escrever" ou reservado, nunca em worktree, na pasta do usuário ou nas pastas do
    Claude Code e do Cérebro.
  * Só CRIA arquivo novo ou ALTERA acrescentando; antes de alterar, a versão anterior vai para
    ~/.cerebro/copias/projetos/<slug>/<data-hora>/antes/. Escrita atômica (arquivo temporário + troca).
  * "Desfazer" volta a última aplicação: arquivo alterado volta à cópia (a versão de agora também é guardada antes); arquivo
    criado do zero é MOVIDO para a pasta de cópias, nunca apagado. Se algum arquivo mudou DEPOIS da aplicação (o dono mexeu), o
    Desfazer recusa e mostra a diferença; só segue com o aceite dessa diferença (assinatura da prévia, ver previa_desfazer).
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import armazem, config, projetos
from .segredos import mascarar

# Pastas onde o Cérebro nunca escreve, qualquer que seja a configuração. Guardadas como resumo sha256 do nome em minúsculas: o
# código portátil não leva o nome de projeto de ninguém. Além delas valem "nunca_entrar" e "nunca_escrever" do config.json.
NOMES_RESERVADOS_SHA256 = {"dccc6c4496dcfda872c763d2ce1ea2d2a750fe8e31d2b27d1c4ccbd478eb032f"}
GANCHOS_PERMITIDOS = ("pre-commit", "pre-commit.cerebro-anterior")       # os únicos arquivos dentro de .git que o Cérebro toca
INFO_PERMITIDOS = ("exclude",)                                           # .git/info/exclude (ignorados só deste PC)
LIMITE_ARQUIVO = 2_000_000                                              # não mexe em arquivo maior que isso (bytes)
MAX_HISTORICO = 50

_travas = {}
_trava_geral = threading.Lock()


class EscritaRecusada(ValueError):
    """Pedido de escrita fora do que a trava permite (o texto explica o motivo, para a tela)."""


def _trava_do_projeto(slug):
    with _trava_geral:
        return _travas.setdefault(slug, threading.Lock())


def _dentro(filho, pai):
    try:
        Path(filho).relative_to(pai)
        return True
    except ValueError:
        return False


def _eh_link(p):
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True


def nome_reservado(nome):
    return hashlib.sha256(str(nome).strip().lower().encode("utf-8")).hexdigest() in NOMES_RESERVADOS_SHA256


# ---------------------------------------------------------------------------------------------------------------
# Travas
# ---------------------------------------------------------------------------------------------------------------
def conferir_projeto(p, cfg=None):
    """Recusa (EscritaRecusada) se o projeto não pode receber escrita. Devolve a pasta resolvida."""
    cfg = cfg if cfg is not None else config.ler_config()
    if not p or not p.get("caminho"):
        raise EscritaRecusada("projeto desconhecido")
    bruto = Path(p["caminho"])
    if _eh_link(bruto):
        raise EscritaRecusada("a pasta do projeto é um atalho (link) para outro lugar: o Cérebro não escreve nela")
    try:
        raiz = bruto.resolve(strict=True)
    except OSError:
        raise EscritaRecusada("a pasta do projeto não existe") from None
    if not raiz.is_dir():
        raise EscritaRecusada("a pasta do projeto não existe")
    if p.get("oculto") or p.get("slug") in (cfg.get("ocultos") or []):
        raise EscritaRecusada("este projeto está oculto: mostre-o de novo em Configurações antes de aplicar algo nele")
    if any(nome_reservado(parte) for parte in raiz.parts) or any(nome_reservado(parte) for parte in bruto.parts):
        raise EscritaRecusada("este projeto é reservado: o Cérebro nunca escreve nele")
    nunca = [str(x).lower().replace("\\", "/") for x in (cfg.get("nunca_escrever") or []) if str(x).strip()]
    if projetos.eh_proibido(str(raiz), p.get("slug", ""), cfg=cfg) or any(n in raiz.as_posix().lower() for n in nunca):
        raise EscritaRecusada("este projeto está em nunca_entrar/nunca_escrever do config.json: o Cérebro não escreve nele")
    casa_usuario = Path.home().resolve()
    if raiz == casa_usuario or raiz.parent == raiz:
        raise EscritaRecusada("a pasta do usuário (ou a raiz do disco) não é um projeto")
    for proibida in (config.CLAUDE, config.CASA):
        pr = Path(proibida).resolve()
        if _dentro(raiz, pr) or _dentro(pr, raiz):
            raise EscritaRecusada("a pasta do projeto contém (ou está dentro de) pastas do Claude Code ou do Cérebro")
    if (raiz / ".git").is_file():
        raise EscritaRecusada("esta pasta é uma worktree do git: aplique no checkout principal do projeto")
    return raiz


def alvo_seguro(raiz, rel):
    """Caminho dentro do projeto para um caminho relativo ('docs/x.md'). Recusa '..', absolutos, links, .git e fugas."""
    raiz_r = Path(raiz).resolve()
    texto = str(rel or "").replace("\\", "/")
    if not texto or "\x00" in texto or texto.startswith("/") or re.match(r"^[A-Za-z]:", texto) or len(texto) > 300:
        raise EscritaRecusada(f"caminho inválido: {rel!r}")
    partes = texto.split("/")
    if any(p in ("", ".", "..") or set(p) == {"."} or ":" in p or p != p.strip() or p.endswith(".") for p in partes):
        raise EscritaRecusada(f"caminho inválido: {rel!r}")
    baixo = [p.lower() for p in partes]
    if ".git" in baixo:
        if not (len(partes) == 3 and baixo[0] == ".git" and ((baixo[1] == "hooks" and baixo[2] in GANCHOS_PERMITIDOS)
                                                             or (baixo[1] == "info" and baixo[2] in INFO_PERMITIDOS))):
            raise EscritaRecusada("dentro de .git o Cérebro só mexe no gancho .git/hooks/pre-commit e em .git/info/exclude")
    atual = raiz_r
    for parte in partes:
        atual = atual / parte
        if _eh_link(atual):
            raise EscritaRecusada(f"{rel} passa por um atalho (link): recusado")
    final = atual.resolve()
    if not _dentro(final, raiz_r) or final == raiz_r:
        raise EscritaRecusada(f"{rel} fica fora da pasta do projeto")
    if final.is_dir():
        raise EscritaRecusada(f"{rel} é uma pasta")
    return raiz_r / Path(*partes)


def ler_existente(alvo):
    """Bytes do arquivo (None se não existe). Recusa arquivo grande demais."""
    try:
        if not alvo.is_file():
            return None
        if alvo.stat().st_size > LIMITE_ARQUIVO:
            raise EscritaRecusada(f"{alvo.name} é grande demais para o Cérebro mexer ({alvo.stat().st_size // 1024} KB)")
        return alvo.read_bytes()
    except OSError as e:
        raise EscritaRecusada(f"não consegui ler {alvo.name}: {e}") from None


# ---------------------------------------------------------------------------------------------------------------
# Cópias e escrita atômica
# ---------------------------------------------------------------------------------------------------------------
def pasta_copias(slug):
    config.pasta_projeto(slug)                       # valida o slug
    p = config.CASA / "copias" / "projetos" / slug
    p.mkdir(parents=True, exist_ok=True)
    return p


def _nova_pasta_copia(slug):
    base = pasta_copias(slug)
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    for n in range(1, 100):
        p = base / (carimbo if n == 1 else f"{carimbo}-{n}")
        try:
            p.mkdir()
            return p
        except FileExistsError:
            continue
    raise EscritaRecusada("não consegui criar a pasta de cópias")


def _gravar_atomico(alvo, dados, modo_de=None, modo=None):
    """Grava num temporário ao lado e troca (os.replace). Mantém as permissões do arquivo antigo (modo_de) ou usa 'modo'."""
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_name(f".{alvo.name}.cerebro-tmp-{uuid.uuid4().hex[:8]}")
    try:
        with open(tmp, "xb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        if modo_de is not None and Path(modo_de).exists():
            shutil.copymode(modo_de, tmp)
        elif modo is not None:
            os.chmod(tmp, modo)
        os.replace(tmp, alvo)
    except OSError:
        if tmp.exists():
            config.remover_em(alvo.parent, tmp, somente_nomes={tmp.name})
        raise


def _copiar_para(origem_bytes, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(origem_bytes)


def _mover_para_copias(alvo, destino, raiz):
    """MOVE (não apaga) um arquivo do projeto para a pasta de cópias. Mesmo disco: os.replace. Outro disco: copia, confere e só
    então tira o original pela trava única de remoção (config.remover_em, limitada a este nome dentro do projeto)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(alvo, destino)
        return
    except OSError:
        pass
    dados = alvo.read_bytes()
    destino.write_bytes(dados)
    if destino.read_bytes() != dados:
        raise EscritaRecusada(f"a cópia de {alvo.name} não confere; nada foi tirado do projeto")
    config.remover_em(raiz, alvo, somente_nomes={alvo.name})


def _sha(b):
    return hashlib.sha256(b or b"").hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# Aplicação (um conjunto de mudanças que se desfaz de uma vez)
# ---------------------------------------------------------------------------------------------------------------
def _arq_historico(slug):
    return config.pasta_projeto(slug) / "aplicacoes.json"


def historico(slug):
    d = armazem.ler_json(_arq_historico(slug), {"itens": []})
    return d.get("itens", []) if isinstance(d, dict) else []


def ultima_desfazivel(slug):
    return next((x for x in historico(slug) if not x.get("desfeita") and x.get("operacoes")), None)


class Aplicacao:
    """Uso: with Aplicacao(p, 'instrucoes', 'Bloco do Cérebro no CLAUDE.md') as ap: ap.criar(...) / ap.alterar(...).
    Grava o manifesto e o histórico ao sair (mesmo com erro no meio: o que já foi feito fica registrado e pode ser desfeito)."""

    def __init__(self, p, acao, titulo, cfg=None):
        self.p, self.acao, self.titulo = p, acao, titulo
        self.slug = p["slug"]
        self.raiz = conferir_projeto(p, cfg)
        self.ops = []
        self.pasta = None
        self._trava = _trava_do_projeto(self.slug)

    def __enter__(self):
        if not self._trava.acquire(timeout=30):
            raise EscritaRecusada("já há uma aplicação em andamento neste projeto")
        self.pasta = _nova_pasta_copia(self.slug)
        return self

    def __exit__(self, tipo, valor, tb):
        try:
            if self.ops:
                self._registrar(erro=str(valor) if valor else "")
            else:
                try:
                    config.remover(self.pasta, pasta=True)      # pasta de cópias vazia, criada agora, dentro de ~/.cerebro
                except (OSError, config.RemocaoRecusada):
                    pass
        finally:
            self._trava.release()
        return False

    def _rel(self, alvo):
        return alvo.relative_to(self.raiz).as_posix()

    def criar(self, rel, dados, modo=None):
        """Cria um arquivo NOVO. Se já existir, recusa (quem chama decide antes o que fazer)."""
        alvo = alvo_seguro(self.raiz, rel)
        if alvo.exists():
            raise EscritaRecusada(f"{rel} já existe: o Cérebro não sobrescreve")
        _gravar_atomico(alvo, dados, modo=modo)
        self.ops.append({"rel": self._rel(alvo), "tipo": "criado", "sha_depois": _sha(dados)})
        return alvo

    def alterar(self, rel, dados, esperado_antes=None):
        """Troca o conteúdo de um arquivo que existe, guardando antes a versão atual em <copia>/antes/<rel>."""
        alvo = alvo_seguro(self.raiz, rel)
        antes = ler_existente(alvo)
        if antes is None:
            raise EscritaRecusada(f"{rel} não existe mais")
        if esperado_antes is not None and _sha(antes) != esperado_antes:
            raise EscritaRecusada(f"{rel} mudou desde a prévia: abra a prévia de novo")
        copia = self.pasta / "antes" / self._rel(alvo)
        _copiar_para(antes, copia)
        _gravar_atomico(alvo, dados, modo_de=alvo)
        self.ops.append({"rel": self._rel(alvo), "tipo": "alterado", "copia": copia.relative_to(self.pasta).as_posix(), "sha_depois": _sha(dados)})
        return alvo

    def retirar(self, rel):
        """Tira um arquivo DO CÉREBRO do projeto movendo-o para <copia>/retirados/<rel> (nunca apaga)."""
        alvo = alvo_seguro(self.raiz, rel)
        if not alvo.is_file():
            raise EscritaRecusada(f"{rel} não existe")
        destino = self.pasta / "retirados" / self._rel(alvo)
        _mover_para_copias(alvo, destino, self.raiz)
        self.ops.append({"rel": self._rel(alvo), "tipo": "retirado", "copia": destino.relative_to(self.pasta).as_posix()})

    def _registrar(self, erro=""):
        item = {"id": self.pasta.name, "em": time.time(), "acao": self.acao, "titulo": self.titulo, "projeto": str(self.raiz),
                "pasta_copia": str(self.pasta), "operacoes": self.ops, "desfeita": False, "erro": erro[:300]}
        (self.pasta / "manifesto.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

        def mudar(d):
            d["itens"] = ([item] + [x for x in d.get("itens", []) if x.get("id") != item["id"]])[:MAX_HISTORICO]
            return d

        armazem.atualizar_json(_arq_historico(self.slug), {"itens": []}, mudar)
        self.registro = item


class DesfazerComMudancas(EscritaRecusada):
    """O dono mexeu num arquivo depois da aplicação: desfazer só com o aceite da diferença (assinatura_mexidos da prévia)."""

    def __init__(self, mensagem, mexidos, assinatura):
        super().__init__(mensagem)
        self.mexidos, self.assinatura = mexidos, assinatura


LIMITE_DIFF_DESFAZER = 400          # linhas de diferença mostradas por arquivo


def _diff(antes, depois, rel):
    a = (antes or b"").decode("utf-8", "replace").splitlines()
    d = (depois or b"").decode("utf-8", "replace").splitlines()
    linhas = list(difflib.unified_diff(a, d, "agora/" + rel, "depois-de-desfazer/" + rel, n=2, lineterm=""))
    if len(linhas) > LIMITE_DIFF_DESFAZER:
        linhas = linhas[:LIMITE_DIFF_DESFAZER] + [f"... (+{len(linhas) - LIMITE_DIFF_DESFAZER} linhas)"]
    return mascarar("\n".join(linhas))


def _registro_desfazivel(slug, raiz):
    item = ultima_desfazivel(slug)
    if item is None:
        raise EscritaRecusada("não há aplicação para desfazer")
    pasta = Path(item["pasta_copia"])
    if not _dentro(pasta.resolve(), pasta_copias(slug).resolve()):
        raise EscritaRecusada("o registro da aplicação aponta para fora da pasta de cópias")
    if Path(item.get("projeto") or "").resolve() != raiz:
        raise EscritaRecusada("a aplicação foi feita em outra pasta")
    return item, pasta


def _mexidos(item, pasta, raiz):
    """Arquivos que mudaram DEPOIS da aplicação (o dono ou outro programa mexeu), com a diferença entre como está agora e como
    ficaria depois de desfazer. Devolve (lista, assinatura); a assinatura muda se qualquer um deles mudar de novo."""
    lista, partes = [], [item["id"]]
    for op in item["operacoes"]:
        alvo = alvo_seguro(raiz, op["rel"])
        atual = ler_existente(alvo)
        if op["tipo"] in ("criado", "alterado"):
            mudou = atual is None or _sha(atual) != op.get("sha_depois")
        else:                                                    # retirado: depois da aplicação o arquivo não existia
            mudou = atual is not None
        if not mudou:
            continue
        if op["tipo"] == "criado":
            depois = None
        else:
            copia = pasta / (op.get("copia") or "")
            depois = copia.read_bytes() if op.get("copia") and _dentro(copia.resolve(), pasta.resolve()) and copia.is_file() else atual
        motivo = ("foi apagado depois da aplicação" if atual is None else
                  "existe de novo (alguém o recriou)" if op["tipo"] == "retirado" else "foi mexido depois da aplicação")
        lista.append({"rel": op["rel"], "tipo": op["tipo"], "motivo": motivo, "diff": _diff(atual, depois, op["rel"])})
        partes.append(f"{op['rel']}:{_sha(atual) if atual is not None else '-'}")
    return lista, hashlib.sha256("\n".join(partes).encode("utf-8")).hexdigest()


def previa_desfazer(p, cfg=None):
    """O que o 'Desfazer' faria, SEM mexer em nada: a última aplicação e os arquivos que mudaram depois dela (com a diferença)."""
    raiz = conferir_projeto(p, cfg)
    item, pasta = _registro_desfazivel(p["slug"], raiz)
    mexidos, assinatura = _mexidos(item, pasta, raiz)
    return {"id": item["id"], "titulo": item["titulo"], "arquivos": [op["rel"] for op in item["operacoes"]],
            "mexidos": mexidos, "assinatura_mexidos": assinatura}


def desfazer(p, cfg=None, aceitar_mexidos=None):
    """Desfaz a última aplicação ainda não desfeita. Devolve o registro com o que foi feito.
    Se algum arquivo mudou depois da aplicação, RECUSA (DesfazerComMudancas, com a diferença) a menos que 'aceitar_mexidos' seja a
    assinatura que a prévia mostrou (a pessoa viu a diferença e confirmou; se o arquivo mudou de novo, a assinatura não bate)."""
    slug = p["slug"]
    raiz = conferir_projeto(p, cfg)
    trava = _trava_do_projeto(slug)
    if not trava.acquire(timeout=30):
        raise EscritaRecusada("já há uma aplicação em andamento neste projeto")
    try:
        item, pasta = _registro_desfazivel(slug, raiz)
        mexidos, assinatura = _mexidos(item, pasta, raiz)
        if mexidos and aceitar_mexidos != assinatura:
            nomes = ", ".join(m["rel"] for m in mexidos)
            raise DesfazerComMudancas(f"{nomes} mudou depois da aplicação: veja a diferença e confirme que quer desfazer mesmo assim "
                                      "(a versão de agora vai para a pasta de cópias)", mexidos, assinatura)
        feito = []
        for op in reversed(item["operacoes"]):
            alvo = alvo_seguro(raiz, op["rel"])
            if op["tipo"] == "criado":
                if alvo.is_file():
                    _mover_para_copias(alvo, pasta / "removidos" / op["rel"], raiz)
                    feito.append(f"{op['rel']}: criado pelo Cérebro, movido para a pasta de cópias")
                else:
                    feito.append(f"{op['rel']}: já não estava lá")
            elif op["tipo"] in ("alterado", "retirado"):
                copia = pasta / op["copia"]
                if not _dentro(copia.resolve(), pasta.resolve()) or not copia.is_file():
                    feito.append(f"{op['rel']}: cópia não encontrada; nada mudou")
                    continue
                atual = ler_existente(alvo)
                if atual is not None:
                    _copiar_para(atual, pasta / "antes-de-desfazer" / op["rel"])
                _gravar_atomico(alvo, copia.read_bytes(), modo_de=alvo if atual is not None else None)
                feito.append(f"{op['rel']}: voltou à versão de antes")

        def mudar(d):
            for x in d.get("itens", []):
                if x.get("id") == item["id"]:
                    x["desfeita"] = True
                    x["desfeita_em"] = time.time()
            return d

        armazem.atualizar_json(_arq_historico(slug), {"itens": []}, mudar)
        return {"id": item["id"], "titulo": item["titulo"], "feito": feito, "pasta_copia": str(pasta)}
    finally:
        trava.release()
