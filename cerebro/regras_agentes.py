"""Agentes por tipo de tarefa: tipo -> modelo -> quem revisa.

A tabela fica em config.json (agentes_regras). Aqui o Cérebro (a) descobre qual regra vale para um subagente, pela
descrição que o gestor deu a ele e pelo tipo de agente do Claude Code, (b) compara com o modelo que foi de fato usado
(modelo mais caro que o necessário ou mais fraco que o previsto) e (c) gera, SOB PEDIDO, os arquivos .claude/agents/*.md
sugeridos numa pasta de PRÉVIA dentro de ~/.cerebro (nunca dentro do projeto).
Todo resultado de subagente passa pelo gestor, qualquer que seja o tipo: a regra só escolhe o modelo e diz quem revisa.
"""
import re
from pathlib import Path

from . import config

RANQUE = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}
_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{0,40}$")


def familia(modelo):
    """'claude-opus-5-5-2026...' -> 'opus'. Texto vazio ou desconhecido -> ''."""
    m = (modelo or "").lower()
    for f in ("haiku", "sonnet", "opus", "fable"):
        if f in m:
            return f
    return ""


def _normalizar(t):
    return (t or "").lower()


def _casa(palavra, texto):
    """A palavra aparece no começo de alguma palavra do texto ('teste' casa com 'testes')."""
    p = _normalizar(palavra).strip()
    return bool(p) and re.search(r"(?<!\w)" + re.escape(p), texto) is not None


def classificar(descricao, tipo_agente, regras):
    """A regra que vale (primeira da lista que casa) ou None. Agentes de leitura (Explore...) são tarefa mecânica."""
    if not regras:
        return None
    if _normalizar(tipo_agente) in config.TIPOS_AGENTE_SO_BUSCA:
        for r in regras:
            if r.get("id") == "mecanico":
                return r
    texto = _normalizar(descricao)
    for r in regras:
        if any(_casa(p, texto) for p in r.get("palavras") or []):
            return r
    return None


def aplicar(descricao, tipo_agente, modelo_usado, regras):
    """Para a tela de agentes: qual regra se aplicou e se o modelo usado bate com o previsto."""
    r = classificar(descricao, tipo_agente, regras)
    usado = familia(modelo_usado)
    if r is None:
        return {"regra": "", "regra_nome": "", "modelo_previsto": "", "modelo_usado": usado, "revisor": "", "situacao": "sem_regra"}
    previsto = r.get("modelo", "")
    situacao = "conforme"
    if usado and previsto in RANQUE and usado in RANQUE:
        if RANQUE[usado] > RANQUE[previsto]:
            situacao = "acima"          # gastou mais modelo do que a regra pedia
        elif RANQUE[usado] < RANQUE[previsto]:
            situacao = "abaixo"         # usou modelo mais fraco do que a regra pedia: o gestor deve conferir com mais cuidado
    elif not usado:
        situacao = "desconhecido"
    return {"regra": r.get("id", ""), "regra_nome": r.get("nome", ""), "modelo_previsto": previsto, "modelo_usado": usado,
            "revisor": r.get("revisor", ""), "situacao": situacao}


def validar_regras(regras):
    """Valida a tabela vinda da página. Devolve a lista limpa ou levanta ValueError."""
    if not isinstance(regras, list) or not 1 <= len(regras) <= 12:
        raise ValueError("a tabela de agentes precisa ter de 1 a 12 tipos de tarefa")
    limpa, ids = [], set()
    for r in regras:
        if not isinstance(r, dict):
            raise ValueError("tipo de tarefa inválido")
        id_ = str(r.get("id", "")).strip().lower()
        if not _ID.match(id_) or id_ in ids:
            raise ValueError(f"identificador inválido ou repetido: {id_!r} (use letras minúsculas, números e hífen)")
        modelo = str(r.get("modelo", "")).strip().lower()
        if modelo not in config.FAMILIAS_MODELO:
            raise ValueError("modelo precisa ser haiku, sonnet ou opus")
        nome = str(r.get("nome", "")).strip()
        revisor = str(r.get("revisor", "")).strip()
        if not nome or len(nome) > 120 or not revisor or len(revisor) > 200:
            raise ValueError("nome e revisor são obrigatórios (até 120 e 200 caracteres)")
        palavras = r.get("palavras")
        if isinstance(palavras, str):
            palavras = [x for x in re.split(r"[,\n;]", palavras)]
        if not isinstance(palavras, list) or len(palavras) > 80:
            raise ValueError("palavras-chave inválidas (até 80)")
        palavras = [str(x).strip().lower() for x in palavras if str(x).strip()]
        if any(len(x) > 40 for x in palavras):
            raise ValueError("palavra-chave grande demais (até 40 caracteres)")
        ids.add(id_)
        limpa.append({"id": id_, "nome": nome, "modelo": modelo, "revisor": revisor, "palavras": palavras})
    return limpa


# ---------------------------------------------------------------------------------------------------------------
# Prévia dos arquivos .claude/agents/*.md (só dentro de ~/.cerebro; nada é copiado para o projeto)
# ---------------------------------------------------------------------------------------------------------------
def texto_agente(regra, nome_projeto):
    id_ = regra["id"]
    palavras = ", ".join(regra.get("palavras", [])[:12])
    descricao = (f"{regra['nome']} do projeto {nome_projeto}. Use quando a tarefa for deste tipo"
                 + (f" (por exemplo: {palavras})" if palavras else "") + ". O resultado SEMPRE volta para o gestor conferir.")
    descricao = descricao.replace("\n", " ")
    return (
        "---\n"
        f"name: cerebro-{id_}\n"
        f"description: {descricao}\n"
        f"model: {regra['modelo']}\n"
        "---\n"
        f"Você é um agente de **{regra['nome']}** do projeto {nome_projeto}. Responda e escreva em português do Brasil.\n\n"
        "Regras de trabalho (valem para qualquer tarefa):\n"
        "1. Leia o pedido inteiro e as instruções do projeto (CLAUDE.md, AGENTS.md) antes de mexer em qualquer coisa.\n"
        "2. Mexa só nos arquivos que o pedido permite. Se precisar de outro, pare e diga qual e por quê.\n"
        "3. Faça a menor mudança completa e rode os testes ou as checagens que o pedido indicar. Nunca diga que algo funciona sem ter verificado.\n"
        "4. No fim, entregue um relatório curto: o que mudou (arquivos), o que foi verificado e como, o que NÃO foi feito e dúvidas.\n"
        "5. Não publique, não envie mensagens, não apague dados e não mexa em segredos, senhas ou chaves.\n\n"
        f"Revisão: {regra['revisor']}. O gestor confere cada entrega e marca o resultado no Cérebro "
        "(aprovado, corrigido ou recusado); trabalho sem conferência não entra no projeto.\n"
    )


def gerar_previa(slug, nome_projeto, regras):
    """Grava os arquivos em ~/.cerebro/projetos/<slug>/previa_agentes/ e devolve [{arquivo, texto}]. Apaga prévias antigas."""
    pasta = config.pasta_projeto(slug) / "previa_agentes"
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("cerebro-*.md"):
        config.remover(velho)
    saida = []
    for r in validar_regras(regras):
        arquivo = f"cerebro-{r['id']}.md"
        texto = texto_agente(r, nome_projeto)
        (pasta / arquivo).write_text(texto, encoding="utf-8", newline="\n")
        saida.append({"arquivo": arquivo, "texto": texto})
    return {"pasta": str(pasta), "arquivos": saida,
            "como_aplicar": "Copiar estes arquivos para a pasta .claude/agents do projeto é uma etapa à parte e precisa da sua aprovação."}


def previa_existente(slug):
    pasta = config.pasta_projeto(slug) / "previa_agentes"
    if not pasta.is_dir():
        return None
    arqs = sorted(Path(pasta).glob("cerebro-*.md"))
    return {"pasta": str(pasta), "arquivos": [{"arquivo": a.name, "texto": a.read_text(encoding="utf-8", errors="replace")} for a in arqs]} if arqs else None
