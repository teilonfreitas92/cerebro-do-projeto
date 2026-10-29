"""Compactar o MEMORY.md SEM IA (por regras), com garantias que um verificador prova antes de gravar.

O MEMORY.md é lido inteiro em TODA conversa: cada linha a menos é token economizado em todas elas. A proposta é CONSERVADORA
(na dúvida, a linha fica inteira):
  * encurta ganchos longos (o detalhe já está no arquivo da memória), só em linha sem palavra de regra;
  * junta linhas duplicadas que apontam para o mesmo arquivo (só as sem palavra de regra e sem subitens);
  * aponta (sem mexer) linhas cujo arquivo não existe e arquivos que não têm linha;
  * junta linhas em branco seguidas numa só.
  Nada muda de lugar: títulos (#), textos soltos, a ordem das linhas e os subitens recuados ficam onde estavam.
GARANTIAS (o verificar() confere e aplicar() recusa se alguma falhar):
  * toda linha que tem uma PALAVRA DE REGRA (lista abaixo: regra, negação, restrição, condição) fica INTEIRA, letra por letra;
  * nenhuma palavra de regra some do índice;
  * os títulos ficam todos, na mesma ordem; todo texto fora das linhas de memória fica igual e no mesmo lugar;
  * subitens recuados continuam inteiros e logo abaixo da sua entrada;
  * a ordem das entradas não muda (nenhuma troca de seção);
  * linha encurtada só perde o FIM do gancho (o nome e o arquivo ficam iguais);
  * todo arquivo que tinha linha continua com linha (e nenhum arquivo novo aparece);
  * o índice não fica maior.
Aplicar usa a mesma rotina segura da edição (prévia, versão, cópia de segurança, escrita atômica).
Tokens: a mesma conta do "contexto fixo" (memoria.estimar_tokens = caracteres / 4).
"""
import re
from collections import Counter

from . import memoria, memoria_edicao
from .memoria_edicao import INDICE, alvo_da_linha
from .segredos import mascarar

LIMITE_GANCHO = 90                 # gancho maior que isso é encurtado (se a linha não tiver palavra de regra)
# Palavras que protegem a linha inteira. Português e inglês, com e sem acento; comparação sem diferenciar maiúsculas.
# Além das palavras de regra, protegem negação, restrição e condição: tirar um "não", um "só" ou um "antes de" muda o sentido.
PALAVRAS_REGRA = (
    "regra", "regras", "nunca", "sempre", "jamais", "proibido", "proibida", "proibidos", "proibidas", "proibir", "proíbe", "proibe",
    "proibição", "proibicao",
    "obrigatório", "obrigatória", "obrigatórios", "obrigatórias", "obrigatorio", "obrigatoria", "obrigatoriamente", "obrigação",
    "não pode", "não podem", "não deve", "não devem", "não use", "não usar", "não faça", "nao pode", "nao deve", "nao usar",
    "exige", "exigido", "exigida", "requisito", "crítico", "critico", "importante", "atenção", "atencao", "cuidado",
    "decisão", "decisao", "decisões", "decisoes", "decidido", "decidida",
    # negação, restrição e condição (português)
    "não", "nao", "nem", "só", "somente", "apenas", "sem", "exceto", "salvo", "senão", "senao", "evite", "evitar", "evita",
    "pergunte", "perguntar", "consulte", "confirme", "quando", "caso", "a menos que", "desde que",
    "antes de", "antes da", "antes do", "antes das", "antes dos", "depois de", "depois da", "depois do", "depois das", "depois dos",
    # inglês
    "never", "always", "must", "must not", "do not", "don't", "don’t", "dont", "forbidden", "prohibited", "required", "mandatory",
    "rule", "rules", "important", "critical", "decision", "not", "only", "without", "avoid", "ask", "unless", "except", "before",
    "after", "if", "when", "should", "cannot", "can't", "won't", "shouldn't", "mustn't",
)
_LETRA = r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]"
_REGRA = re.compile(r"(?<!" + _LETRA + r")(?:" + "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in
                                                       sorted(PALAVRAS_REGRA, key=len, reverse=True)) + r")(?!" + _LETRA + r")", re.I)
_TITULO = re.compile(r"^#{1,6}(\s|$)")
COMPACTAR_COM_IA_LIGADO = False      # ponto de extensão: desligado (ver compactar_com_ia)


def tem_regra(texto):
    return bool(_REGRA.search(texto or ""))


def contar_palavras_regra(texto):
    """Quantas vezes cada palavra de regra aparece (minúsculas, espaços normalizados)."""
    return Counter(" ".join(m.group(0).lower().split()) for m in _REGRA.finditer(texto or ""))


def tokens(texto):
    return memoria.estimar_tokens(len(texto or ""))


def encurtar_gancho(gancho, limite=LIMITE_GANCHO):
    """Primeira frase (se couber) ou corte na última palavra inteira + '…'."""
    g = " ".join((gancho or "").split())
    if len(g) <= limite:
        return g
    for sep in (". ", "; ", " — ", " – ", ": ", " (", ", "):
        i = g.find(sep)
        if 25 <= i <= limite - 1:
            return g[:i].rstrip(" .;:,—–(") + "…"
    corte = g[:limite - 1]
    if " " in corte[20:]:
        corte = corte[:corte.rfind(" ")]
    return corte.rstrip(" .;:,—–(") + "…"


def _tipo_do_arquivo(pasta, alvo):
    c = pasta / alvo
    if "/" in alvo or not c.is_file():
        return None
    try:
        campos, _ = memoria._cabecalho(memoria._ler(c) or "")
    except OSError:
        return None
    t = campos.get("type") or ""
    return t if t in memoria.TIPOS else ""


def arquivos_de_memoria(pasta):
    if not pasta.is_dir():
        return []
    return sorted(f.name for f in pasta.glob("*.md") if f.is_file() and f.name != INDICE and memoria._ID_MEMORIA.match(f.name))


# ---------------------------------------------------------------------------------------------------------------
# Leitura do índice em blocos (a mesma para a proposta e para o verificador)
# ---------------------------------------------------------------------------------------------------------------
def _recuo(linha):
    s = linha.expandtabs(4)
    return len(s) - len(s.lstrip())


def blocos(texto):
    """O índice em blocos, na ordem do arquivo: {"tipo": titulo|entrada|texto|vazio, "n", "linha", "alvo", "subitens"}.
    Uma ENTRADA (linha que aponta para um arquivo de memória) leva junto os SUBITENS: as linhas logo abaixo com recuo maior que o
    dela (linhas em branco no meio contam; as do fim, não). Assim um subitem nunca se separa da sua entrada."""
    linhas = (texto or "").replace("\r\n", "\n").split("\n")
    saida, i = [], 0
    while i < len(linhas):
        linha = linhas[i]
        if not linha.strip():
            saida.append({"tipo": "vazio", "n": i + 1, "linha": linha})
            i += 1
            continue
        if _TITULO.match(linha):
            saida.append({"tipo": "titulo", "n": i + 1, "linha": linha})
            i += 1
            continue
        alvo = alvo_da_linha(linha)
        if alvo is None:
            saida.append({"tipo": "texto", "n": i + 1, "linha": linha})
            i += 1
            continue
        recuo, j, fim = _recuo(linha), i + 1, i + 1
        while j < len(linhas):
            if not linhas[j].strip():
                j += 1
            elif _recuo(linhas[j]) > recuo:
                j += 1
                fim = j
            else:
                break
        saida.append({"tipo": "entrada", "n": i + 1, "linha": linha, "alvo": alvo, "subitens": linhas[i + 1:fim]})
        i = fim
    return saida


def _sem_branco(linhas):
    return tuple(x for x in linhas if x.strip())


# ---------------------------------------------------------------------------------------------------------------
# Proposta (função pura sobre o texto + a lista de arquivos)
# ---------------------------------------------------------------------------------------------------------------
def propor_texto(texto, pasta):
    """Monta o índice compacto a partir do texto do MEMORY.md. Devolve (novo_texto, mudancas, apontamentos).
    Nada muda de lugar: só encurta ganchos, junta duplicadas e linhas em branco seguidas."""
    texto = (texto or "").replace("\r\n", "\n")
    bs = blocos(texto)
    mudancas = []
    entradas = [b for b in bs if b["tipo"] == "entrada"]
    for e in entradas:
        # protegida: tem palavra de regra ou tem subitens (o que está embaixo dela depende dela)
        e["fixa"] = tem_regra(e["linha"]) or bool(_sem_branco(e["subitens"]))

    # duplicadas: mesma meta. Entradas fixas ficam todas (inteiras); das outras fica só a primeira, e só se não houver uma fixa
    por_alvo = {}
    for e in entradas:
        por_alvo.setdefault(e["alvo"], []).append(e)
    for e in entradas:
        e["sai"] = False
        if e["fixa"]:
            continue
        grupo = por_alvo[e["alvo"]]
        primeira_comum = next(x for x in grupo if not x["fixa"])
        if any(x["fixa"] for x in grupo) or e is not primeira_comum:
            e["sai"] = True
            mudancas.append({"tipo": "duplicada", "linha": e["n"], "antes": e["linha"],
                             "depois": f"(juntada: {e['alvo']} já tem outra linha no índice)"})

    # ganchos longos (só em linha sem palavra de regra); o começo da linha (marcador, nome e arquivo) fica igual
    for e in entradas:
        e["nova"] = e["linha"]
        if e["sai"] or tem_regra(e["linha"]):
            continue
        m = memoria_edicao.LINHA_INDICE.match(e["linha"])
        gancho = (m.group(5) or "").strip()
        curto = encurtar_gancho(gancho)
        if curto != " ".join(gancho.split()):
            e["nova"] = e["linha"][:m.start(4)].rstrip() + " — " + curto
            mudancas.append({"tipo": "encurtado", "linha": e["n"], "antes": e["linha"], "depois": e["nova"]})

    saida = []
    for b in bs:
        if b["tipo"] == "vazio":
            if saida and saida[-1].strip():
                saida.append("")
            continue
        if b["tipo"] != "entrada":
            saida.append(b["linha"])
            continue
        if b["sai"]:
            continue
        saida.append(b["nova"])
        saida.extend(b["subitens"])
    while saida and not saida[-1].strip():
        saida.pop()
    novo = "\n".join(saida) + "\n" if saida else ""

    existentes = set(arquivos_de_memoria(pasta))
    citadas = [(n, linha, alvo_da_linha(linha)) for n, linha in enumerate(texto.split("\n"), 1)]
    citadas = [x for x in citadas if x[2] is not None]
    apontamentos = {
        "sem_arquivo": [{"linha": n, "texto": linha, "alvo": alvo} for n, linha, alvo in citadas
                        if alvo not in existentes and not (pasta / alvo).is_file()],
        "sem_linha": sorted(existentes - {alvo for _, _, alvo in citadas}),
    }
    return novo, mudancas, apontamentos


# ---------------------------------------------------------------------------------------------------------------
# Verificador das garantias
# ---------------------------------------------------------------------------------------------------------------
def _estrutura(texto):
    """(fixos, entradas): fixos = títulos e textos soltos, na ordem; entradas = [(âncora, alvo, linha, subitens)], em que a
    âncora é quantos fixos vêm antes da entrada (diz em que seção e entre quais textos ela está)."""
    fixos, entradas = [], []
    for b in blocos(texto):
        if b["tipo"] in ("titulo", "texto"):
            fixos.append((b["tipo"], b["linha"]))
        elif b["tipo"] == "entrada":
            entradas.append((len(fixos), b["alvo"], b["linha"], _sem_branco(b["subitens"])))
    return fixos, entradas


def _subsequencia(curta, longa):
    it = iter(longa)
    return all(any(x == y for y in it) for x in curta)


def _so_encurtou(linha, originais):
    """True se 'linha' é uma das originais ou uma delas com o gancho cortado no fim (mesmo começo, mesmo nome, mesmo arquivo)."""
    if linha in originais:
        return True
    m = memoria_edicao.LINHA_INDICE.match(linha)
    if not m or not (m.group(5) or "").endswith("…"):
        return False
    resto = " ".join(m.group(5)[:-1].split())
    for o in originais:
        mo = memoria_edicao.LINHA_INDICE.match(o)
        if mo and mo.group(1, 2, 3) == m.group(1, 2, 3) and " ".join((mo.group(5) or "").split()).startswith(resto):
            return True
    return False


def verificar(antes, depois):
    """Prova as garantias comparando o texto de antes com o de depois. Devolve {ok, checagens:[{nome, ok, detalhe}]}."""
    antes = (antes or "").replace("\r\n", "\n")
    depois = (depois or "").replace("\r\n", "\n")
    linhas_depois = set(depois.split("\n"))
    checagens = []

    def checar(nome, ok, detalhe):
        checagens.append({"nome": nome, "ok": bool(ok), "detalhe": detalhe})

    protegidas = [x for x in antes.split("\n") if tem_regra(x)]
    faltando = [x for x in protegidas if x not in linhas_depois]
    checar("Linhas com palavra de regra ficaram inteiras", not faltando,
           f"{len(protegidas)} linha(s) protegida(s)" + (f"; {len(faltando)} mudaram ou sumiram: " + " | ".join(faltando[:3]) if faltando else ", todas iguais, letra por letra"))

    ca, cd = contar_palavras_regra(antes), contar_palavras_regra(depois)
    perdidas = {p: ca[p] - cd.get(p, 0) for p in ca if cd.get(p, 0) < ca[p]}
    checar("Nenhuma palavra de regra sumiu", not perdidas,
           (", ".join(f"{p} ({n} a menos)" for p, n in perdidas.items()) if perdidas
            else (", ".join(f"{p} ×{n}" for p, n in ca.most_common(8)) or "nenhuma palavra de regra no índice")))

    fa, ea = _estrutura(antes)
    fd, ed = _estrutura(depois)
    ta_, td_ = [x[1] for x in fa if x[0] == "titulo"], [x[1] for x in fd if x[0] == "titulo"]
    checar("Os títulos ficaram todos, na mesma ordem", ta_ == td_,
           f"{len(ta_)} título(s)" + (", iguais e na mesma ordem" if ta_ == td_ else
                                       "; antes: " + " | ".join(ta_[:4]) + " — depois: " + " | ".join(td_[:4])))
    checar("Texto fora das linhas de memória ficou igual e no mesmo lugar", fa == fd,
           f"{len(fa)} linha(s) de título/texto" + (", todas iguais" if fa == fd else
                                                     f"; mudaram: {', '.join(x[1] for x in fa if x not in fd)[:200] or 'a ordem'}"))

    com_sub = Counter((x[1], x[3]) for x in ea if x[3])
    com_sub_depois = Counter((x[1], x[3]) for x in ed if x[3])
    soltos = [a for (a, s), n in com_sub.items() if com_sub_depois.get((a, s), 0) < n]
    checar("Subitens continuam inteiros, logo abaixo da sua entrada", not soltos,
           f"{sum(com_sub.values())} entrada(s) com subitens" + (f"; separados ou mudados: {', '.join(soltos[:4])}" if soltos else ", todos no lugar"))

    ordem_ok = _subsequencia([(x[0], x[1]) for x in ed], [(x[0], x[1]) for x in ea])
    checar("A ordem das entradas não mudou (nenhuma trocou de seção)", ordem_ok,
           "mesma ordem" if ordem_ok else "alguma entrada mudou de lugar ou de seção")

    originais = {}
    for x in ea:
        originais.setdefault(x[1], set()).add(x[2])
    reescritas = [x[2] for x in ed if not _so_encurtou(x[2], originais.get(x[1], set()))]
    checar("Linhas encurtadas só perderam o fim do gancho", not reescritas,
           "nada reescrito" if not reescritas else "reescritas: " + " | ".join(reescritas[:3]))

    alvos_antes = {a for a in (alvo_da_linha(x) for x in antes.split("\n")) if a}
    alvos_depois = {a for a in (alvo_da_linha(x) for x in depois.split("\n")) if a}
    sumiram = sorted(alvos_antes - alvos_depois)
    checar("Todo arquivo de memória continua com a sua linha", not sumiram,
           f"{len(alvos_antes)} arquivo(s) no índice" + (f"; sem linha agora: {', '.join(sumiram[:6])}" if sumiram else ", todos continuam"))
    novos = sorted(alvos_depois - alvos_antes)
    checar("Nenhum arquivo novo inventado", not novos, ", ".join(novos[:6]) or "nenhum")

    ta, td = tokens(antes), tokens(depois)
    checar("O índice não ficou maior", td <= ta, f"≈ {ta} → ≈ {td} tokens")
    return {"ok": all(c["ok"] for c in checagens), "checagens": checagens}




# ---------------------------------------------------------------------------------------------------------------
# Proposta, aplicação e ponto de extensão
# ---------------------------------------------------------------------------------------------------------------
def _ler_indice(slug):
    c = memoria_edicao.caminho_seguro(slug, INDICE)
    texto, quebra = memoria_edicao.ler_texto(c)
    if texto is None:
        raise memoria_edicao.Recusado("este projeto não tem MEMORY.md")
    return c, texto, quebra


def propor(slug):
    """Proposta para a tela: antes/depois (mascarados), tokens, mudanças, apontamentos, verificação e a versão do arquivo."""
    c, texto, quebra = _ler_indice(slug)
    novo, mudancas, apont = propor_texto(texto, c.parent)
    ver = verificar(texto, novo)
    # mesma conta do "contexto fixo" (caracteres do arquivo como está no disco, com o \r de cada linha se for CRLF)
    no_disco = lambda s: memoria.estimar_tokens(len(s) + (s.count("\n") if quebra == "\r\n" else 0))  # noqa: E731
    ta, td = no_disco(texto), no_disco(novo)
    m = lambda s: mascarar(s)  # noqa: E731
    return {
        "antes": m(texto), "depois": m(novo), "diff": memoria_edicao.diferenca(texto, novo, INDICE),
        "tokens_antes": ta, "tokens_depois": td, "economia": ta - td, "pct": round(100 * (ta - td) / ta, 1) if ta else 0,
        "mudancas": [{**x, "antes": m(x["antes"]), "depois": m(x["depois"])} for x in mudancas],
        "contagem": dict(Counter(x["tipo"] for x in mudancas)),
        "apontamentos": {"sem_arquivo": [{**x, "texto": m(x["texto"])} for x in apont["sem_arquivo"]], "sem_linha": apont["sem_linha"]},
        "verificacao": ver, "versao": memoria_edicao.versao(c), "igual": novo == texto,
        "palavras_regra": list(PALAVRAS_REGRA), "com_ia": COMPACTAR_COM_IA_LIGADO,
    }


def aplicar(slug, versao_vista, confirmar=False):
    """Grava a proposta (recalculada do arquivo ATUAL, que precisa ser o mesmo que a pessoa viu). Recusa se o verificador falhar."""
    c, texto, _ = _ler_indice(slug)
    memoria_edicao.conferir_versao(c, versao_vista)
    novo, _, _ = propor_texto(texto, c.parent)
    ver = verificar(texto, novo)
    if not ver["ok"]:
        falhas = "; ".join(x["nome"] for x in ver["checagens"] if not x["ok"])
        raise memoria_edicao.Recusado("a proposta não passou no verificador (" + falhas + "): nada foi gravado")
    if novo == texto:
        raise memoria_edicao.Recusado("nada a compactar")
    r = memoria_edicao.editar(slug, INDICE, versao_vista, corpo=novo, confirmar=confirmar)
    r["verificacao"] = ver
    r["economia"] = tokens(texto) - tokens(novo)
    return r


def compactar_com_ia(texto, pasta, modelo=None):
    """PONTO DE EXTENSÃO (DESLIGADO): compactar o índice com IA, mantendo as mesmas garantias.

    Assinatura: (texto do MEMORY.md, pasta da memória, modelo opcional) -> novo texto ou None.
    TODO: quando o dono aprovar, chamar a IA aqui SÓ com o texto do índice (já mascarado) e passar o resultado por
    verificar(texto, novo) antes de qualquer gravação; se a verificação falhar, descartar. Hoje nada é enviado a lugar nenhum.
    """
    if not COMPACTAR_COM_IA_LIGADO:
        return None
    raise NotImplementedError("compactar com IA ainda não foi implementado")
