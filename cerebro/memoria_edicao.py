"""Edição SEGURA da memória do Claude Code (pela página ou pela CLI): editar, criar e arquivar memórias.

A memória mora em ~/.claude/projects/<slug>/memory/ (índice MEMORY.md + um arquivo .md por fato). Toda gravação aqui segue
a MESMA rotina, sem exceção:
  1. trava de caminho: só arquivos .md direto dentro da pasta memory do projeto (nada de ../, link ou subpasta);
  2. prévia: sem confirmar=True nada é gravado, só volta a diferença (antes/depois) para a pessoa ver;
  3. conferência de versão: a página manda a "versao" do arquivo de quando abriu; se o arquivo mudou desde então (o Claude
     Code pode ter escrito), RECUSA e pede para recarregar — nunca sobrescreve o que a pessoa não viu;
  4. cópia de segurança em ~/.cerebro/copias/memoria/<slug>/<data-hora>/ ANTES de gravar;
  5. escrita atômica (arquivo temporário na mesma pasta + troca).
Nunca apaga: arquivar MOVE o arquivo para memory/_arquivo/ e tira a linha dele do MEMORY.md.
Texto que volta para a tela passa por segredos.mascarar(); memória com segredo não é editada pela página (o texto da tela
está mascarado e gravá-lo trocaria a chave por "[segredo oculto]").
"""
import difflib
import hashlib
import os
import re
import shutil
import time
import unicodedata
import uuid
from pathlib import Path

from . import config, memoria
from .segredos import OCULTO, mascarar

INDICE = "MEMORY.md"
PASTA_ARQUIVO = "_arquivo"
TIPOS = memoria.TIPOS
AUSENTE = "ausente"                    # "versão" de um arquivo que ainda não existe
LIMITE_CORPO = 40_000
LIMITE_GANCHO = 160
_SLUG = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")
# linha do índice: "- [Título](arquivo.md) — gancho"
LINHA_INDICE = re.compile(r"^(\s*[-*+]\s+)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?\s*\)\s*(?:(—|–|-|:)\s*(.*))?$")


class Recusado(ValueError):
    """Pedido recusado (caminho fora da memória, dado inválido, segredo...). A mensagem vai para a tela."""


class Conflito(Recusado):
    """O arquivo mudou desde que foi aberto: recarregar e refazer."""


# ---------------------------------------------------------------------------------------------------------------
# Caminhos e versões
# ---------------------------------------------------------------------------------------------------------------
def pasta(slug):
    if not _SLUG.match(slug or ""):
        raise Recusado("projeto inválido")
    return memoria.pasta_memoria(slug)


def caminho_seguro(slug, nome):
    """TRAVA DE CAMINHO: devolve <memory>/<nome> só se 'nome' for um .md simples e o caminho resolvido (links e junções
    incluídos) ficar direto dentro da pasta memory do projeto. Qualquer outra coisa levanta Recusado."""
    nome = str(nome or "")
    if not memoria._ID_MEMORIA.match(nome) or nome.startswith(".") or "/" in nome or "\\" in nome or ".." in nome:
        raise Recusado(f"nome de arquivo de memória inválido: {nome[:80]!r}")
    base = pasta(slug)
    c = base / nome
    try:
        base_r = base.resolve()
        if c.resolve().parent != base_r:
            raise Recusado("fora da pasta de memória do projeto")
    except OSError:
        raise Recusado("caminho inválido") from None
    return c


def versao(caminho):
    """Impressão digital do arquivo (data em ns + tamanho + sha256). Muda se qualquer byte mudar."""
    caminho = Path(caminho)
    try:
        st = caminho.stat()
        dados = caminho.read_bytes()
    except FileNotFoundError:
        return AUSENTE
    return f"{st.st_mtime_ns}:{st.st_size}:{hashlib.sha256(dados).hexdigest()[:24]}"


def conferir_versao(caminho, esperada):
    if not esperada:
        raise Recusado("abra o arquivo antes de gravar (falta a versão de quando foi aberto)")
    if versao(caminho) != esperada:
        raise Conflito(f"{Path(caminho).name} mudou desde que você abriu (o Claude Code pode ter escrito nele). "
                       "Recarregue a página e refaça a mudança.")


def ler_texto(caminho):
    """(texto com \\n, quebra original '\\r\\n' ou '\\n'). Recusa arquivo que não é UTF-8 (não arrisca estragar)."""
    try:
        bruto = Path(caminho).read_bytes()
    except FileNotFoundError:
        return None, "\n"
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        raise Recusado(f"{Path(caminho).name} não está em UTF-8: edite num editor de texto") from None
    if texto.startswith("﻿"):
        texto = texto[1:]
    quebra = "\r\n" if "\r\n" in texto else "\n"
    return texto.replace("\r\n", "\n"), quebra


# ---------------------------------------------------------------------------------------------------------------
# Cópia de segurança, escrita atômica e diferença
# ---------------------------------------------------------------------------------------------------------------
def copia_seguranca(categoria, slug, caminhos):
    """Copia os arquivos (os que existem) para ~/.cerebro/copias/<categoria>/<slug>/<data-hora>/. Devolve a pasta."""
    if not _SLUG.match(slug or "") or not re.fullmatch(r"[a-z]{1,20}", categoria):
        raise Recusado("cópia de segurança: nome inválido")
    raiz = config.CASA / "copias" / categoria / slug
    carimbo = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    destino = raiz / carimbo
    n = 1
    while destino.exists():
        n += 1
        destino = raiz / f"{carimbo}-{n}"
    destino.mkdir(parents=True)
    for c in caminhos:
        c = Path(c)
        if c.is_file():
            shutil.copy2(c, destino / c.name)
    return destino


def gravar_atomico(caminho, texto, quebra="\n"):
    """Grava num temporário na MESMA pasta e troca (os.replace): ninguém lê o arquivo pela metade."""
    caminho = Path(caminho)
    dados = texto.replace("\n", quebra).encode("utf-8") if quebra != "\n" else texto.encode("utf-8")
    tmp = caminho.with_name(f".{caminho.name}.cerebro-{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "wb") as f:
        f.write(dados)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def diferenca(antes, depois, nome):
    """Diferença linha a linha (formato unificado), mascarada para a tela."""
    linhas = difflib.unified_diff((antes or "").splitlines(), (depois or "").splitlines(),
                                  fromfile=f"{nome} (antes)", tofile=f"{nome} (depois)", lineterm="", n=2)
    return mascarar("\n".join(linhas))


# ---------------------------------------------------------------------------------------------------------------
# Cabeçalho (frontmatter) e corpo
# ---------------------------------------------------------------------------------------------------------------
def partes(texto):
    """(cabeçalho incluindo as linhas '---', separador de linhas em branco, corpo). Sem cabeçalho: ('', '', texto)."""
    if not texto.startswith("---"):
        return "", "", texto
    fim = texto.find("\n---", 3)
    if fim < 0:
        return "", "", texto
    fim_linha = texto.find("\n", fim + 4)
    cab = texto[:fim_linha + 1] if fim_linha >= 0 else texto + "\n"
    resto = texto[len(cab):] if fim_linha >= 0 else ""
    corpo = resto.lstrip("\n")
    return cab, resto[:len(resto) - len(corpo)], corpo


def _yaml(valor):
    """Valor de uma linha só, com aspas quando o YAML poderia ler errado."""
    v = " ".join(str(valor).split())
    if not v or re.search(r"[:#\[\]{}&*!|>'\"%@`]|^[-?,]|^\s|\s$", v):
        if "'" not in v:
            return "'" + v + "'"                      # aspas simples: nada dentro precisa de escape
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def _trocar_campo(cab, campo, valor):
    """Troca o valor de 'campo:' no cabeçalho (inclusive valor em várias linhas '|' / '>'). Sem o campo: insere depois de name."""
    linhas = cab.split("\n")
    padrao = re.compile(r"^(\s*)" + campo + r"\s*:")
    for i, linha in enumerate(linhas):
        m = padrao.match(linha)
        if not m:
            continue
        recuo = len(m.group(1))
        j = i + 1
        while j < len(linhas) and linhas[j].strip() and len(linhas[j]) - len(linhas[j].lstrip()) > recuo and linhas[j].strip() != "---":
            j += 1
        linhas[i:j] = [f"{m.group(1)}{campo}: {_yaml(valor)}"]
        return "\n".join(linhas)
    pos = next((i + 1 for i, linha in enumerate(linhas) if re.match(r"^name\s*:", linha)), 1)
    linhas.insert(pos, f"{campo}: {_yaml(valor)}")
    return "\n".join(linhas)


def _sem_segredo_novo(texto, campo):
    if OCULTO in (texto or ""):
        raise Recusado(f"{campo}: o texto tem '{OCULTO}' (veio mascarado da tela); não grave isso por cima do original")
    if mascarar(texto or "") != (texto or ""):
        raise Recusado(f"{campo}: parece ter senha, chave ou token. Memória não deve guardar segredo")


def _valor_editado(novo, original, campo):
    """Valor a gravar. Se a página mandou de volta o texto MASCARADO sem mexer, vale o original. Mexeu num texto que tinha
    segredo: recusa (gravaria a máscara no lugar da chave)."""
    if novo is None:
        return original
    novo = str(novo).replace("\r\n", "\n")
    if novo == original or novo == mascarar(original):
        return original
    if mascarar(original) != original:
        raise Recusado(f"{campo}: este texto tem um segredo escondido na tela. Edite num editor de texto")
    _sem_segredo_novo(novo, campo)
    return novo


# ---------------------------------------------------------------------------------------------------------------
# Abrir
# ---------------------------------------------------------------------------------------------------------------
def abrir(slug, nome):
    """Dados para editar um arquivo: texto/descrição/corpo MASCARADOS + a versão (para conferir na hora de gravar)."""
    c = caminho_seguro(slug, nome)
    texto, _ = ler_texto(c)
    if texto is None:
        raise Recusado(f"{nome} não existe")
    if nome == INDICE:
        return {"nome": nome, "indice": True, "texto": mascarar(texto), "corpo": mascarar(texto), "descricao": "", "titulo": "Índice da memória",
                "tipo": "índice", "versao": versao(c), "tem_segredo": mascarar(texto) != texto, "cabecalho": False}
    campos, _ = memoria._cabecalho(texto)
    cab, _, corpo = partes(texto)
    return {"nome": nome, "indice": False, "texto": mascarar(texto), "titulo": mascarar(campos.get("name") or nome),
            "descricao": mascarar(campos.get("description") or ""), "tipo": campos.get("type") or "", "corpo": mascarar(corpo),
            "versao": versao(c), "tem_segredo": mascarar(texto) != texto, "cabecalho": bool(cab)}


def _resultado(previa, nome_diff, diff, extra):
    return {"previa": previa, "gravado": not previa, "diff": diff, "arquivo": nome_diff, **extra}


# ---------------------------------------------------------------------------------------------------------------
# Editar
# ---------------------------------------------------------------------------------------------------------------
def editar(slug, nome, versao_aberta, descricao=None, corpo=None, confirmar=False):
    """Edita descrição e/ou corpo de uma memória (ou o MEMORY.md inteiro, pelo 'corpo'). Sem confirmar: só a prévia."""
    c = caminho_seguro(slug, nome)
    texto, quebra = ler_texto(c)
    if texto is None:
        raise Recusado(f"{nome} não existe")
    conferir_versao(c, versao_aberta)
    if corpo is not None and len(str(corpo)) > LIMITE_CORPO:
        raise Recusado(f"texto grande demais (máximo {LIMITE_CORPO} caracteres)")
    if nome == INDICE:
        if descricao:
            raise Recusado("o MEMORY.md não tem descrição: edite o texto")
        novo = _valor_editado(corpo, texto, "MEMORY.md")
    else:
        cab, meio, corpo_atual = partes(texto)
        novo_corpo = _valor_editado(corpo, corpo_atual, "corpo")
        if descricao is not None:
            if not cab:
                raise Recusado("este arquivo não tem cabeçalho (---): edite só o corpo")
            campos, _ = memoria._cabecalho(texto)
            atual = campos.get("description") or ""
            nova = _valor_editado(" ".join(str(descricao).split()), atual, "descrição")
            if nova != atual:
                if len(nova) < 3 or len(nova) > 400:
                    raise Recusado("descrição precisa ter de 3 a 400 caracteres")
                cab = _trocar_campo(cab, "description", nova)
        novo = cab + (meio or ("\n" if cab else "")) + novo_corpo
    if novo and not novo.endswith("\n"):
        novo += "\n"
    if novo == texto:
        return _resultado(True, nome, "", {"mudou": False, "versao": versao_aberta})
    diff = diferenca(texto, novo, nome)
    if not confirmar:
        return _resultado(True, nome, diff, {"mudou": True, "versao": versao_aberta})
    copia = copia_seguranca("memoria", slug, [c])
    conferir_versao(c, versao_aberta)               # de novo, logo antes de trocar
    gravar_atomico(c, novo, quebra)
    return _resultado(False, nome, diff, {"mudou": True, "copia": str(copia), "versao": versao(c)})


# ---------------------------------------------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------------------------------------------
def nome_para(titulo, tipo):
    """'Botões com 28 px' + feedback -> 'feedback_botoes_com_28_px.md' (só letras sem acento, dígitos e _)."""
    t = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:60].rstrip("_") or "memoria"
    return f"{tipo}_{t}.md"


def linha_do_indice(titulo, nome, gancho):
    titulo = " ".join(str(titulo).replace("[", "(").replace("]", ")").split())
    gancho = " ".join(str(gancho).split())
    return f"- [{titulo}]({nome})" + (f" — {gancho}" if gancho else "")


def _limpo(valor, campo, minimo, maximo):
    v = " ".join(str(valor or "").split())
    if len(v) < minimo or len(v) > maximo:
        raise Recusado(f"{campo}: de {minimo} a {maximo} caracteres")
    _sem_segredo_novo(v, campo)
    return v


def criar(slug, titulo, descricao, tipo, corpo, porque="", como_aplicar="", gancho="", nome=None, versao_indice=None, confirmar=False):
    """Cria <memory>/<nome>.md (cabeçalho name/description/metadata.type + corpo) e acrescenta a linha no MEMORY.md.
    feedback/project levam as linhas **Why:** e **How to apply:**. Sem confirmar: prévia + versão do índice para confirmar."""
    if tipo not in TIPOS:
        raise Recusado("tipo precisa ser: " + ", ".join(TIPOS))
    titulo = _limpo(titulo, "título", 3, 120)
    descricao = _limpo(descricao, "descrição", 3, 300)
    gancho = _limpo(gancho, "gancho", 0, LIMITE_GANCHO) if gancho else ""
    corpo = str(corpo or "").replace("\r\n", "\n").strip()
    if len(corpo) > LIMITE_CORPO:
        raise Recusado(f"texto grande demais (máximo {LIMITE_CORPO} caracteres)")
    _sem_segredo_novo(corpo, "texto")
    if tipo in ("feedback", "project") and "**Why:**" not in corpo:
        porque = _limpo(porque, "por quê", 3, 1000)
        como_aplicar = _limpo(como_aplicar, "como aplicar", 3, 1000)
        corpo = (corpo + "\n\n" if corpo else "") + f"**Why:** {porque}\n**How to apply:** {como_aplicar}"
    if not corpo:
        raise Recusado("escreva o texto da memória")
    nome = nome or nome_para(titulo, tipo)
    c = caminho_seguro(slug, nome)
    if nome == INDICE or c.exists() or (pasta(slug) / PASTA_ARQUIVO / nome).exists():
        raise Recusado(f"já existe uma memória chamada {nome}: escolha outro título")
    if not (config.PROJETOS_CLAUDE / slug).is_dir():
        raise Recusado("este projeto não tem pasta no Claude Code")
    novo_arquivo = (f"---\nname: {_yaml(titulo)}\ndescription: {_yaml(descricao)}\nmetadata:\n  type: {tipo}\n---\n\n{corpo}\n")
    ind = caminho_seguro(slug, INDICE)
    antes, quebra = ler_texto(ind)
    antes = antes or ""
    linha = linha_do_indice(titulo, nome, gancho or descricao[:LIMITE_GANCHO])
    depois = (antes.rstrip("\n") + "\n" if antes.strip() else "") + linha + "\n"
    diff = diferenca(antes, depois, INDICE) + "\n" + diferenca("", novo_arquivo, nome)
    v_ind = versao(ind)
    if not confirmar:
        return _resultado(True, nome, diff, {"versao_indice": v_ind, "nome": nome})
    conferir_versao(ind, versao_indice)
    pasta(slug).mkdir(exist_ok=True)
    copia = copia_seguranca("memoria", slug, [ind])
    conferir_versao(ind, versao_indice)
    if c.exists():
        raise Conflito(f"{nome} apareceu enquanto você confirmava: recarregue")
    gravar_atomico(c, novo_arquivo)
    gravar_atomico(ind, depois, quebra)
    return _resultado(False, nome, diff, {"copia": str(copia), "nome": nome, "versao_indice": versao(ind)})


# ---------------------------------------------------------------------------------------------------------------
# Arquivar (mover para memory/_arquivo/, nunca apagar)
# ---------------------------------------------------------------------------------------------------------------
def alvo_da_linha(linha):
    """Arquivo para onde uma linha do índice aponta ('./x.md' vira 'x.md'), ou None se não for linha de memória."""
    m = LINHA_INDICE.match(linha)
    if not m:
        return None
    alvo = m.group(3).replace("\\", "/")
    while alvo.startswith("./"):
        alvo = alvo[2:]
    return alvo


def tirar_do_indice(texto, nome):
    """Texto do índice sem as linhas que apontam para 'nome'. Devolve (novo_texto, linhas_tiradas)."""
    fica, tiradas = [], []
    for linha in texto.split("\n"):
        (tiradas if alvo_da_linha(linha) == nome else fica).append(linha)
    return "\n".join(fica), tiradas


def _nomes_possiveis(destino_pasta, stem):
    data = time.strftime("%Y%m%d-%H%M%S")
    yield destino_pasta / f"{stem}.md"
    yield destino_pasta / f"{stem}-{data}.md"
    for i in range(2, 1000):
        yield destino_pasta / f"{stem}-{data}-{i}.md"


def _nome_livre(destino_pasta, stem):
    """Primeiro nome que ainda não existe em _arquivo/: x.md, x-AAAAMMDD-HHMMSS.md, x-AAAAMMDD-HHMMSS-2.md..."""
    for d in _nomes_possiveis(destino_pasta, stem):
        if not d.exists():
            return d
    raise Recusado(f"não achei um nome livre para {stem}.md em {PASTA_ARQUIVO}/")


def _mover_sem_sobrescrever(origem, destino_pasta, stem):
    """Move 'origem' para um nome livre de _arquivo/ SEM nunca trocar um arquivo que já está lá. No Windows os.rename já recusa
    destino existente; nos outros sistemas o nome é reservado antes (criação exclusiva) e só então o arquivo vai para ele."""
    for d in _nomes_possiveis(destino_pasta, stem):
        if d.exists():
            continue
        try:
            if os.name == "nt":
                os.rename(origem, d)
            else:
                os.close(os.open(d, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))   # reserva o nome (falha se já existe)
                os.replace(origem, d)                                                # troca só a reserva vazia, que é nossa
            return d
        except FileExistsError:
            continue                                                                 # alguém pegou o nome agora: tenta o próximo
    raise Recusado(f"não achei um nome livre para {stem}.md em {PASTA_ARQUIVO}/")


def arquivar(slug, nome, versao_aberta, versao_indice=None, confirmar=False):
    """Move a memória para memory/_arquivo/ e tira a(s) linha(s) dela do MEMORY.md. Nunca apaga nada."""
    if nome == INDICE:
        raise Recusado("o MEMORY.md não pode ser arquivado")
    c = caminho_seguro(slug, nome)
    if not c.is_file():
        raise Recusado(f"{nome} não existe")
    conferir_versao(c, versao_aberta)
    ind = caminho_seguro(slug, INDICE)
    antes, quebra = ler_texto(ind)
    antes = antes or ""
    depois, tiradas = tirar_do_indice(antes, nome)
    destino_pasta = pasta(slug) / PASTA_ARQUIVO
    destino = _nome_livre(destino_pasta, c.stem)
    diff = diferenca(antes, depois, INDICE) if tiradas else f"(nenhuma linha do {INDICE} aponta para {nome})"
    diff += f"\n\nmover: {nome}  ->  {PASTA_ARQUIVO}/{destino.name}  (nada é apagado)"
    v_ind = versao(ind)
    if not confirmar:
        return _resultado(True, nome, diff, {"versao_indice": v_ind, "linhas_tiradas": [mascarar(x) for x in tiradas]})
    if tiradas:
        conferir_versao(ind, versao_indice)
    copia = copia_seguranca("memoria", slug, [c, ind])
    conferir_versao(c, versao_aberta)
    if tiradas:
        conferir_versao(ind, versao_indice)
    destino_pasta.mkdir(exist_ok=True)
    destino = _mover_sem_sobrescrever(c, destino_pasta, c.stem)   # mover, não apagar; nunca por cima de outra arquivada
    if tiradas:
        try:
            gravar_atomico(ind, depois, quebra)
        except OSError:
            if not c.exists():                               # não deu para mexer no índice: devolve o arquivo ao lugar
                os.replace(destino, c)                       # (se algo novo já ocupou o nome, ele fica no _arquivo/)
            raise
    return _resultado(False, nome, diff, {"copia": str(copia), "arquivado_em": str(destino), "versao_indice": versao(ind)})


def arquivadas(slug):
    """Memórias já arquivadas (memory/_arquivo/*.md), mais novas primeiro."""
    p = pasta(slug) / PASTA_ARQUIVO
    if not p.is_dir():
        return []
    itens = [{"arquivo": f.name, "modificado": f.stat().st_mtime} for f in p.glob("*.md") if f.is_file()]
    return sorted(itens, key=lambda i: -i["modificado"])
