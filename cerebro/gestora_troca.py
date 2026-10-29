"""Sessão GESTORA que se renova na MESMA sessão do app (padrão): vigia de contexto, "gestora limpar", corrente de transcrições.

Padrão: só a compactação automática (capítulo no PreCompact + resumo no SessionStart). Fluxo da limpeza OPCIONAL
(gestora_rotacao.ativo; a gestora nunca é trocada):
  1. Vigia: contexto do último turno da gestora (lido do fim do JSONL) passou de limite_pct% de janela_tokens (padrão 60% de
     200 mil; config.json > "gestora_rotacao"). No próximo UserPromptSubmit da gestora, ligacoes.py entrega UMA vez por
     transcrição o recado: "Contexto em X%. Ao terminar este turno: rode `... gestora limpar <projeto>` e, se ele disser OK,
     chame clear_session com session_id "self"." (nada de Stop hook: prenderia a conversa).
  2. limpar(): grava o capítulo completo (capitulos.py), RELÊ e confere que tem tudo; só então registra a "limpeza pendente"
     (transcrição atual + hora) em corrente.json. Sem capítulo bom: "NÃO limpe".
  3. ao_iniciar_sessao() (gancho SessionStart "clear"/"compact", síncrono, via cerebro_hook.py --sincrono): só para a gestora.
     Em "clear" com limpeza pendente do projeto nos últimos 30 min (ou, sem pendente, gestora mexida nos últimos 3 min =
     /clear manual), troca gestoras[slug].conversa para o novo id e abre um elo novo: a transcrição antiga vira "anterior"
     (fim = agora, capítulo ligado). Devolve a linha do GESTOR.md + o resumo do último capítulo como additionalContext.
  4. Retenção das transcrições "anterior": retencao_gestora.py (apagar estreito, só com backup conferido e o sim do dono).

corrente.json (~/.cerebro/projetos/<slug>/corrente.json): elos (conversa, sessao_app, titulo, inicio, fim, capitulo, estado
atual|anterior|apagada, quem, como), limpezas pendentes, avisos de limite já entregues, pendentes de troca e log.

Troca por start_session (preparar/trocar com a marca "[cerebro-bastao:<id>]") continua só na CLI, sem destaque: não é o padrão.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

from . import armazem, config, indice, transcricao
from .segredos import encurtar, mascarar

PADRAO = {"janela_tokens": 200_000, "limite_pct": 60, "dias_limpeza": 7, "nomes_base": {}, "ativo": False,
          "apagar_autorizado": {}}
ID_CONVERSA = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
ID_APP = re.compile(r"^local_[A-Za-z0-9_\-]{1,80}$")
ID_MARCA = re.compile(r"^[0-9a-f]{10}$")
SUFIXO_ATUAL = " (sessão atual)"
_ATE = re.compile(r"\s*·\s*até\s+\d{1,2}/\d{1,2}(/\d{2,4})?\s*$")
PENDENTE_DIAS = 7
LER_PRIMEIRAS_LINHAS = 80
JANELA_LIMPEZA = 24 * 3600        # limpeza pendente vale por 24 h: no app, a conversa nova só nasce na PRÓXIMA mensagem do dono
FOLGA_FIM_TURNO = 10 * 60        # depois do capítulo, a gestora ainda termina o turno: a transcrição antiga pode crescer até isso
# Testado em 29/10/2026: um lembrete do CronCreate agendado antes do clear_session NÃO sobrevive à limpeza; a conversa
# limpa só recomeça com uma mensagem do dono (ou de outra sessão). Sem toque nenhum, só a compactação automática.
# Primeira coisa que a gestora diz depois de uma limpeza (pedido do dono, 29/10/2026): avisar que limpou e que pode seguir.
AVISO_LIMPA = ("A conversa da gestora acabou de ser LIMPA pelo Cérebro (capítulo salvo). Na sua PRIMEIRA resposta, comece "
               "com uma linha para o dono: \"Conversa limpa pelo Cérebro: o capítulo foi salvo e eu já recebi o resumo. Pode prosseguir.\" "
               "Depois responda normalmente ao que ele pediu.")
JANELA_CLEAR_MANUAL = 3 * 60      # sem pendente: gestora mexida há até 3 min = /clear manual
SECOES_CAPITULO = ("## Onde parou", "## Últimos pedidos", "## Arquivos mais mexidos", "## Decisões recentes", "Ramo do git:")


def marca_texto(marca):
    return f"[cerebro-bastao:{marca}]"


def parametros(cfg=None):
    b = dict(PADRAO)
    extra = (cfg or {}).get("gestora_rotacao")
    if isinstance(extra, dict):
        for k in ("janela_tokens", "limite_pct", "dias_limpeza"):
            v = extra.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                b[k] = v
        if isinstance(extra.get("ativo"), bool):
            b["ativo"] = extra["ativo"]
        if isinstance(extra.get("nomes_base"), dict):
            b["nomes_base"] = {str(k): str(v)[:80] for k, v in extra["nomes_base"].items() if str(v).strip()}
        if isinstance(extra.get("apagar_autorizado"), dict):
            b["apagar_autorizado"] = dict(extra["apagar_autorizado"])
    b["limite_tokens"] = int(b["janela_tokens"] * min(b["limite_pct"], 100) / 100)
    return b


def _gestora(slug, cfg):
    return ((cfg.get("gestoras") or {}).get(slug) or {})


def caminho_cli():
    """Caminho do cerebro_cli.py com barras normais (o recado manda rodar por ele)."""
    return str(Path(__file__).resolve().parent.parent / "cerebro_cli.py").replace("\\", "/")


# ---------------------------------------------------------------------------------------------------------------
# Vigia
# ---------------------------------------------------------------------------------------------------------------
def contexto_atual(caminho, cauda=400_000):
    """Contexto do ÚLTIMO turno do assistente (entrada + cache lido + cache escrito), lido do fim do JSONL. 0 se não houver."""
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - cauda))
            linhas = f.read().split(b"\n")
    except OSError:
        return 0
    for linha in reversed(linhas):
        if not transcricao._tem_tipo(linha, b"assistant") or b'"usage"' not in linha:
            continue
        try:
            o = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get("isSidechain"):
            continue
        u = (o.get("message") or {}).get("usage") if isinstance(o.get("message"), dict) else None
        if isinstance(u, dict):
            soma = 0
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                v = u.get(k)
                soma += v if isinstance(v, int) and not isinstance(v, bool) else 0
            return soma
    return 0


def vigia(slug, cfg=None):
    """Tamanho do contexto da conversa gestora. 'longa' = passou do limite."""
    cfg = cfg if cfg is not None else config.ler_config()
    b = parametros(cfg)
    conversa = _gestora(slug, cfg).get("conversa", "")
    saida = {"conversa": conversa, "contexto": 0, "pct": 0, "mb": 0.0, "longa": False, "limite_tokens": b["limite_tokens"],
             "limite_pct": b["limite_pct"], "ativo": b["ativo"]}
    if not conversa or not ID_CONVERSA.match(conversa):
        return saida
    caminho = indice.pasta_claude(slug) / f"{conversa}.jsonl"
    try:
        tam = caminho.stat().st_size
    except OSError:
        return saida
    ctx = contexto_atual(caminho)
    from .bastao import janela_efetiva                  # modelo com janela de 1 milhão: a conta é sobre ela
    jan = janela_efetiva(ctx, b["janela_tokens"])
    limite = int(jan * min(b["limite_pct"], 100) / 100)
    saida.update(contexto=ctx, pct=round(100 * ctx / jan, 1), mb=round(tam / 1_000_000, 1), longa=ctx >= limite, limite_tokens=limite)
    return saida


def recado_limite(slug, sessao_id, cfg=None, agora=None):
    """UserPromptSubmit da gestora: o recado de limpar, UMA vez por transcrição que passou do limite. None se nada a dizer."""
    cfg = cfg if cfg is not None else config.ler_config()
    if not sessao_id or sessao_id != _gestora(slug, cfg).get("conversa") or not parametros(cfg)["ativo"]:
        return None
    v = vigia(slug, cfg)
    if not v["longa"]:
        return None
    agora = agora or time.time()
    entregue = {}

    def mudar(d):
        d = _normalizar(d)
        if d["avisos_limite"].get(sessao_id):
            return d
        d["avisos_limite"][sessao_id] = agora
        for k in list(d["avisos_limite"])[:-50]:
            d["avisos_limite"].pop(k)
        entregue["sim"] = True
        return d

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    if not entregue:
        return None
    pct = str(round(v["pct"])).replace(".", ",")
    return (f"Contexto em {pct}%. Ao terminar este turno: rode `python {caminho_cli()} gestora limpar {slug}` e, se ele disser OK, "
            "chame clear_session com session_id \"self\". Antes de chamar, diga ao dono numa frase: \"Vou limpar a conversa agora; "
            "o capítulo está salvo. Mande qualquer mensagem (ex.: continue) e eu sigo de onde parei.\"")


def itens_fila(p, cfg=None):
    """'Precisa de você': transcrições antigas da gestora que só esperam a sua autorização para sair."""
    cfg = cfg if cfg is not None else config.ler_config()
    slug = p["slug"]
    itens = []
    try:
        completar_pendentes(slug, cfg)
    except (OSError, ValueError):
        pass
    from . import retencao_gestora
    try:
        cand = retencao_gestora.candidatos(slug, cfg)
    except (OSError, ValueError):
        cand = []
    if cand and not retencao_gestora.autorizado(slug, cfg):
        itens.append({"nivel": "info", "projeto": slug, "titulo": f"{p['nome']}: {len(cand)} transcrição(ões) antiga(s) da gestora podem sair",
                      "texto": "Fora de uso há mais de 7 dias. Só saem as que estiverem no backup mais novo, conferido e idêntico. "
                               "Autorize uma vez na aba Sessões; capítulos e decisões ficam para sempre.", "aba": "sessoes"})
    return itens


# ---------------------------------------------------------------------------------------------------------------
# Corrente
# ---------------------------------------------------------------------------------------------------------------
def _arq_corrente(slug):
    return config.pasta_projeto(slug) / "corrente.json"


def arq_apagamentos(slug):
    return config.pasta_projeto(slug) / "apagamentos.jsonl"


def _vazio():
    return {"elos": [], "pendentes": [], "limpezas": [], "avisos_limite": {}, "log": []}


def _normalizar(d):
    if not isinstance(d, dict):
        d = _vazio()
    for k in ("elos", "pendentes", "limpezas", "log"):
        if not isinstance(d.get(k), list):
            d[k] = []
    if not isinstance(d.get("avisos_limite"), dict):
        d["avisos_limite"] = {}
    d["elos"] = [e for e in d["elos"] if isinstance(e, dict) and ID_CONVERSA.match(str(e.get("conversa", "")))]
    d["pendentes"] = [x for x in d["pendentes"] if isinstance(x, dict) and ID_MARCA.match(str(x.get("marca", "")))]
    d["limpezas"] = [x for x in d["limpezas"] if isinstance(x, dict) and ID_CONVERSA.match(str(x.get("conversa", "")))]
    return d


def _log(d, texto, agora, **extra):
    d["log"].append({"em": agora, "texto": texto, **extra})
    del d["log"][:-200]


def _inicio_da_conversa(slug, conversa):
    ind = indice.indice_se_existe(slug, f"{conversa}.jsonl") or {}
    if ind.get("inicio"):
        return ind["inicio"]
    try:
        return (indice.pasta_claude(slug) / f"{conversa}.jsonl").stat().st_mtime
    except OSError:
        return None


def _sincronizar(d, slug, cfg, agora):
    """A corrente acompanha o config: gestora escolhida na página (ou trocada lá) vira o elo atual. Devolve True se mudou."""
    ges = _gestora(slug, cfg)
    conversa = ges.get("conversa", "")
    atuais = [e for e in d["elos"] if e.get("estado") == "atual"]
    if not conversa or not ID_CONVERSA.match(conversa):
        return False
    if len(atuais) == 1 and atuais[0]["conversa"] == conversa:
        return False
    for e in atuais:
        if e["conversa"] != conversa:
            e.update(estado="anterior", fim=agora, como_saiu="gestora trocada fora do Cérebro (página ou config)")
    existente = next((e for e in d["elos"] if e["conversa"] == conversa), None)
    if existente is None:
        d["elos"].append({"conversa": conversa, "sessao_app": "", "titulo": ges.get("nome", ""), "inicio": _inicio_da_conversa(slug, conversa),
                          "fim": None, "capitulo": "", "estado": "atual", "quem": "dono", "como": "gestora escolhida no Cérebro"})
    elif existente.get("estado") != "atual":
        existente.update(estado="atual", fim=None)
    _log(d, "corrente sincronizada com a gestora do config", agora, conversa=conversa)
    return True


def corrente(slug, cfg=None, agora=None):
    """Lê a corrente (e a sincroniza com a gestora do config, gravando só se mudou)."""
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    d = _normalizar(armazem.ler_json(_arq_corrente(slug), _vazio()))
    if _sincronizar(d, slug, cfg, agora):
        d = _normalizar(armazem.atualizar_json(_arq_corrente(slug), _vazio(), lambda x: _mudar_sincronizar(x, slug, cfg, agora)))
    return d


def _mudar_sincronizar(x, slug, cfg, agora):
    x = _normalizar(x)
    _sincronizar(x, slug, cfg, agora)
    return x


def _gravar_gestora(slug, nova, titulo=None):
    def mudar(c):
        g = c.setdefault("gestoras", {})
        antigo = g.get(slug) or {}
        g[slug] = {"conversa": nova, "nome": titulo if titulo is not None else antigo.get("nome", "")}
    config.atualizar_config(mudar)


# ---------------------------------------------------------------------------------------------------------------
# Limpeza na mesma sessão (padrão)
# ---------------------------------------------------------------------------------------------------------------
def conferir_capitulo(texto):
    """O capítulo tem tudo? Devolve a lista do que falta (vazia = ok)."""
    from . import capitulos
    falta = [s for s in SECOES_CAPITULO if s not in (texto or "")]
    if capitulos.FIM_RESUMO not in (texto or ""):
        falta.append("separador do resumo")
    elif len(texto.split(capitulos.FIM_RESUMO, 1)[1].strip()) < 50:
        falta.append("passa-bastão completo")
    return falta


def limpar(slug, cfg=None, agora=None):
    """`gestora limpar`: capítulo completo da transcrição gestora atual, relido e conferido; só então a limpeza fica pendente.
    Levanta ValueError (= "NÃO limpe") se algo falhar."""
    from . import capitulos
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    conversa = _gestora(slug, cfg).get("conversa", "")
    if not conversa:
        raise ValueError("o projeto não tem sessão gestora escolhida")
    destino = capitulos.gravar(slug, conversa, cfg, agora)
    if destino is None:
        raise ValueError("não consegui gravar o capítulo (a transcrição gestora não foi encontrada)")
    try:
        texto = Path(destino).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"o capítulo não pôde ser relido: {e}") from None
    falta = conferir_capitulo(texto)
    if falta:
        raise ValueError("o capítulo gravado está incompleto: falta " + ", ".join(falta))
    corrente(slug, cfg, agora)

    def mudar(d):
        d = _normalizar(d)
        d["limpezas"] = [x for x in d["limpezas"] if agora - (x.get("em") or 0) < JANELA_LIMPEZA][-9:]
        d["limpezas"].append({"conversa": conversa, "em": agora, "capitulo": Path(destino).name})
        _log(d, "limpeza pendente (capítulo gravado e conferido)", agora, conversa=conversa, capitulo=Path(destino).name)
        return d

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    return {"ok": True, "conversa": conversa, "capitulo": str(destino), "tamanho": len(texto)}


def _ultimo_capitulo(slug):
    from . import capitulos
    lista = capitulos.listar(slug, 1)
    return lista[0]["nome"] if lista else ""


def ao_iniciar_sessao(bruto, agora=None):
    """SessionStart "clear"/"compact" (síncrono, sem servidor): só para a gestora. Atualiza a corrente no /clear e devolve o
    additionalContext (linha do GESTOR.md + resumo do último capítulo) ou '' (nada a dizer)."""
    from . import capitulos, ganchos_eventos
    if not isinstance(bruto, dict) or bruto.get("hook_event_name") != "SessionStart":
        return ""
    fonte, sid = bruto.get("source"), str(bruto.get("session_id") or "")
    if fonte not in ("startup", "clear", "compact") or not ID_CONVERSA.match(sid):
        return ""
    slug = ganchos_eventos._slug_de(bruto)
    if not slug or not re.fullmatch(r"[A-Za-z0-9_\-]{1,200}", slug):
        return ""
    cfg = config.ler_config()
    ges = _gestora(slug, cfg)
    atual = ges.get("conversa", "")
    if not atual:
        return ""
    if fonte == "compact" or sid == atual:
        return capitulos.texto_contexto(config.CASA, slug) if sid == atual else ""
    agora = agora or time.time()
    d = _normalizar(armazem.ler_json(_arq_corrente(slug), _vazio()))
    pend = next((x for x in reversed(d["limpezas"]) if x["conversa"] == atual and 0 <= agora - (x.get("em") or 0) <= JANELA_LIMPEZA), None)
    if pend is not None:
        try:                                          # a gestora continuou trabalhando depois? então não foi ela que limpou
            if (indice.pasta_claude(slug) / f"{atual}.jsonl").stat().st_mtime > (pend.get("em") or 0) + FOLGA_FIM_TURNO:
                pend = None
        except OSError:
            pass
    if pend is None:
        if fonte == "startup":                        # sessão nova comum: só conta como da gestora com limpeza pendente
            return ""
        try:
            mexida = (indice.pasta_claude(slug) / f"{atual}.jsonl").stat().st_mtime
        except OSError:
            return ""
        if agora - mexida > JANELA_CLEAR_MANUAL:
            return ""                                 # /clear de outra sessão do projeto: não é a gestora
    corrente(slug, cfg, agora)

    def mudar(x):
        x = _normalizar(x)
        for e in x["elos"]:
            if e.get("estado") == "atual" and e["conversa"] != sid:
                e.update(estado="anterior", fim=agora, capitulo=(pend or {}).get("capitulo", "") or e.get("capitulo", ""),
                         como_saiu="limpeza pedida pela gestora (clear_session)" if pend else "/clear manual")
                if not pend:
                    e["capitulo_pendente"] = True          # o servidor grava o capítulo dela depois (ligacoes.py)
        if not any(e["conversa"] == sid for e in x["elos"]):
            x["elos"].append({"conversa": sid, "sessao_app": "", "titulo": ges.get("nome", ""), "inicio": agora, "fim": None,
                              "capitulo": "", "estado": "atual", "quem": "gestora" if pend else "dono",
                              "como": "limpeza na mesma sessão (clear_session)" if pend else "/clear manual"})
        x["limpezas"] = [y for y in x["limpezas"] if y["conversa"] != atual]
        _log(x, "nova transcrição da gestora (mesma sessão)", agora, antiga=atual, nova=sid, pendente=bool(pend))
        return x

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    _gravar_gestora(slug, sid)
    return AVISO_LIMPA + "\n\n" + capitulos.texto_contexto(config.CASA, slug)


def capitulos_pendentes(slug, cfg=None):
    """Elos que saíram por /clear manual sem capítulo: grava o capítulo da transcrição antiga (o servidor chama)."""
    from . import capitulos
    d = _normalizar(armazem.ler_json(_arq_corrente(slug), _vazio()))
    feitos = []
    for e in d["elos"]:
        if e.get("capitulo_pendente") and e.get("estado") == "anterior":
            destino = capitulos.gravar(slug, e["conversa"], cfg, forcar=True)
            feitos.append((e["conversa"], destino.name if destino else ""))
    if feitos:
        def mudar(x):
            x = _normalizar(x)
            for e in x["elos"]:
                for conversa, nome in feitos:
                    if e["conversa"] == conversa:
                        e.pop("capitulo_pendente", None)
                        e["capitulo"] = nome or e.get("capitulo", "")
            return x
        armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    return [c for c, _ in feitos]


# ---------------------------------------------------------------------------------------------------------------
# Títulos (troca por start_session, só CLI)
# ---------------------------------------------------------------------------------------------------------------
def nome_base(slug, cfg=None, titulo_atual=None):
    """Título atual sem " (sessão atual)" e sem " · até DD/MM". Configurável em gestora_rotacao.nomes_base[slug]."""
    cfg = cfg if cfg is not None else config.ler_config()
    fixo = parametros(cfg)["nomes_base"].get(slug)
    if fixo:
        return fixo.strip()
    t = titulo_atual if titulo_atual is not None else _gestora(slug, cfg).get("nome", "")
    t = (t or "").strip()
    if t.endswith(SUFIXO_ATUAL.strip()):
        t = t[: -len(SUFIXO_ATUAL.strip())].rstrip()
    t = _ATE.sub("", t).strip()
    return t or "Gestora"


def titulos(base, agora=None):
    agora = agora or time.time()
    return base + SUFIXO_ATUAL, f"{base} · até {time.strftime('%d/%m', time.localtime(agora))}"


# ---------------------------------------------------------------------------------------------------------------
# Peças do passa-bastão (usadas também pelos capítulos)
# ---------------------------------------------------------------------------------------------------------------
def _fim_da_conversa(caminho, n=3, cauda=600_000):
    """Os últimos textos do assistente (onde a conversa parou: o que foi feito e o que falta)."""
    textos = []
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - cauda))
            bruto = f.read()
    except OSError:
        return []
    for linha in bruto.split(b"\n")[1 if tam > cauda else 0:]:
        if not transcricao._tem_tipo(linha, b"assistant"):
            continue
        try:
            o = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get("isSidechain") or o.get("type") != "assistant":
            continue
        m = o.get("message") if isinstance(o.get("message"), dict) else {}
        t = transcricao._texto_do_conteudo(m.get("content")).strip()
        if t:
            textos.append(t)
    return textos[-n:]


def _ramos_git(caminho):
    """Ramo atual e ramos locais (só leitura)."""
    from . import projetos
    if not caminho or not Path(caminho).is_dir():
        return "", []
    atual = projetos._git(caminho, "rev-parse", "--abbrev-ref", "HEAD")
    lista = projetos._git(caminho, "for-each-ref", "--count=15", "--sort=-committerdate", "--format=%(refname:short)", "refs/heads")
    return atual, [x for x in lista.splitlines() if x.strip()]


def _regras_da_memoria(slug, caminho):
    from . import memoria
    try:
        itens = memoria.listar(slug, caminho or "")["itens"]
    except (OSError, ValueError):
        return []
    return [i for i in itens if i.get("origem") == "memoria" and (i.get("regra") or i.get("decisao")) and i.get("arquivo") != "MEMORY.md"][:10]


def gravar_texto(destino, texto):
    """Escrita atômica de um texto (temporário ao lado + troca)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + f".{os.getpid()}.tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(tmp, destino)


# ---------------------------------------------------------------------------------------------------------------
# Troca por start_session (alternativa, só pela CLI; não é o padrão)
# ---------------------------------------------------------------------------------------------------------------
def montar_bastao(slug, conversa, marca, p=None, cfg=None):
    """Texto do bastão de troca (mascarado): marca + instruções para a sessão nova + bastao.montar + o que a troca precisa."""
    from . import bastao, tarefas_gestor
    cfg = cfg if cfg is not None else config.ler_config()
    caminho_proj = (p or {}).get("caminho", "")
    nome = (p or {}).get("nome") or slug
    base = bastao.montar(slug, conversa, cfg)
    L = [marca_texto(marca), "",
         f"Você é a NOVA sessão gestora do projeto {nome}. A conversa gestora anterior ficou longa e passou o bastão para você.",
         "Antes de tudo: leia ~/.cerebro/GESTOR.md (manual do gestor) e confira o estado real (git status, testes) antes de mexer.", ""]
    fim = _fim_da_conversa(indice.pasta_claude(slug) / f"{conversa}.jsonl")
    L += ["## Onde a conversa anterior parou (últimas respostas do gestor: o que foi feito e o que falta)", ""]
    L += [f"{i}. " + encurtar(t, 700).replace("\n", " ") for i, t in enumerate(fim, 1)] or ["(não achei respostas de texto)"]
    L += ["", "## Tarefas do dono abertas (aba Tarefas do Cérebro)", ""]
    try:
        tarefas = tarefas_gestor.listar(slug, cfg, incluir_finais=False)
    except (OSError, ValueError):
        tarefas = []
    L += [f"- {t['id']} [{t.get('estado', '')}] {encurtar(t.get('titulo', ''), 160)}" for t in tarefas[:12]] or ["(nenhuma)"]
    L += ["", "## Regras e decisões da memória do projeto", ""]
    L += [f"- {i['arquivo']}: {encurtar(i.get('descricao') or i.get('titulo') or '', 200)}" for i in _regras_da_memoria(slug, caminho_proj)] or ["(nenhuma marcada)"]
    atual, ramos = _ramos_git(caminho_proj)
    L += ["", "## Git (só leitura)", ""]
    if atual or ramos:
        L += [f"- Ramo atual: {atual or '?'}", "- Ramos locais (mais recentes primeiro): " + (", ".join(ramos) or "(nenhum)")]
    else:
        L += ["(sem git ou git indisponível)"]
    L += ["", "---", "", base]
    return mascarar("\n".join(L))


def _pasta_bastao(slug):
    p = config.pasta_projeto(slug) / "bastao"
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho_bastao(slug, nome):
    """Arquivo de bastão desta pasta (recusa nome fora do padrão)."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,120}\.md", nome or ""):
        raise ValueError("nome de bastão inválido")
    return _pasta_bastao(slug) / nome


def preparar(slug, p=None, cfg=None, agora=None):
    """Gera o bastão de troca com uma marca nova, registra o pendente e devolve o texto + títulos."""
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    conversa = _gestora(slug, cfg).get("conversa", "")
    if not conversa:
        raise ValueError("o projeto não tem sessão gestora escolhida (aba Sessões > Definir gestora)")
    if not (indice.pasta_claude(slug) / f"{conversa}.jsonl").is_file():
        raise ValueError("a conversa gestora do config não existe mais neste projeto")
    corrente(slug, cfg, agora)
    marca = secrets.token_hex(5)
    texto = montar_bastao(slug, conversa, marca, p, cfg)
    nome_arq = time.strftime("troca-%Y%m%d-%H%M%S", time.localtime(agora)) + f"-{marca}.md"
    destino = caminho_bastao(slug, nome_arq)
    gravar_texto(destino, texto)
    nova, antiga = titulos(nome_base(slug, cfg), agora)
    pend = {"marca": marca, "criado_em": agora, "conversa_antiga": conversa, "titulo_nova": nova, "titulo_antiga": antiga,
            "bastao": nome_arq, "estado": "preparada"}

    def mudar(d):
        d = _normalizar(d)
        d["pendentes"] = [x for x in d["pendentes"] if agora - (x.get("criado_em") or 0) < PENDENTE_DIAS * 86400][-9:] + [pend]
        _log(d, "troca preparada", agora, marca=marca)
        return d

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    return {"marca": marca, "marca_texto": marca_texto(marca), "texto": texto, "arquivo": str(destino), "bastao": nome_arq,
            "titulo_nova": nova, "titulo_antiga": antiga, "conversa_antiga": conversa}


def primeira_mensagem(caminho):
    """Texto da primeira mensagem de usuário do JSONL (o 'prompt' com que a sessão foi aberta). '' se não houver."""
    try:
        with open(caminho, "rb") as f:
            for n, linha in enumerate(f):
                if n >= LER_PRIMEIRAS_LINHAS:
                    break
                if not transcricao._tem_tipo(linha, b"user") or len(linha) > 3_000_000:
                    continue
                try:
                    o = json.loads(linha)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain"):
                    continue
                m = o.get("message") if isinstance(o.get("message"), dict) else {}
                t = transcricao._texto_do_conteudo(m.get("content"))
                if t.strip():
                    return t
    except OSError:
        return ""
    return ""


def achar_pela_marca(slug, marca, desde=0, ignorar=()):
    """Conversa (id) do projeto cuja PRIMEIRA mensagem tem a marca. Só olha JSONL mexidos depois de 'desde' (folga de 2 min)."""
    alvo = marca_texto(marca)
    for a in sorted(indice.listar_arquivos(slug), key=lambda x: -x["mtime"]):
        if a["tipo"] != "sessao" or a["id"] in ignorar or a["mtime"] < desde - 120:
            continue
        if alvo in primeira_mensagem(indice.pasta_claude(slug) / a["rel"]):
            return a["id"]
    return ""


def _aplicar_troca(d, pend, nova, agora, quem, como):
    """Fecha o elo atual (anterior, fim=agora) e abre o novo (atual). Mexe só no dicionário 'd'."""
    for e in d["elos"]:
        if e.get("estado") == "atual" and e["conversa"] != nova:
            e.update(estado="anterior", fim=agora, titulo=pend.get("titulo_antiga") or e.get("titulo", ""))
            if e["conversa"] == pend.get("conversa_antiga") and pend.get("sessao_app_antiga"):
                e["sessao_app"] = pend["sessao_app_antiga"]
    elo = next((e for e in d["elos"] if e["conversa"] == nova), None)
    if elo is None:
        elo = {"conversa": nova}
        d["elos"].append(elo)
    elo.update(sessao_app=pend.get("sessao_app") or elo.get("sessao_app", ""), titulo=pend.get("titulo_nova", ""), inicio=agora,
               fim=None, bastao=pend.get("bastao", ""), capitulo="", estado="atual", quem=quem, como=como, marca=pend["marca"])
    d["pendentes"] = [x for x in d["pendentes"] if x.get("marca") != pend["marca"]]
    _log(d, "troca concluída", agora, marca=pend["marca"], nova=nova, antiga=pend.get("conversa_antiga", ""))


def trocar(slug, marca, sessao_app="", sessao_app_antiga="", quem="gestora", cfg=None, agora=None):
    """Registra a troca. Devolve {"feito": True, "conversa": nova} ou {"feito": False, "pendente": True} (o servidor completa)."""
    if not ID_MARCA.match(marca or ""):
        raise ValueError("marca inválida (10 letras/números, como mostra o `gestora preparar`)")
    for v in (sessao_app, sessao_app_antiga):
        if v and not ID_APP.match(v):
            raise ValueError("id de sessão do app inválido (começa com local_)")
    cfg = cfg if cfg is not None else config.ler_config()
    agora = agora or time.time()
    corrente(slug, cfg, agora)
    d = _normalizar(armazem.ler_json(_arq_corrente(slug), _vazio()))
    pend = next((x for x in d["pendentes"] if x["marca"] == marca), None)
    if pend is None:
        feito = next((e for e in d["elos"] if e.get("marca") == marca), None)
        if feito is not None:
            return {"feito": True, "ja_feito": True, "conversa": feito["conversa"]}
        raise ValueError("marca desconhecida neste projeto: rode antes `cerebro_cli.py gestora preparar <projeto>`")
    nova = achar_pela_marca(slug, marca, pend.get("criado_em") or 0, ignorar={pend.get("conversa_antiga", "")})
    resultado = {}

    def mudar(x):
        x = _normalizar(x)
        p2 = next((y for y in x["pendentes"] if y["marca"] == marca), None)
        if p2 is None:
            return x
        if sessao_app:
            p2["sessao_app"] = sessao_app
        if sessao_app_antiga:
            p2["sessao_app_antiga"] = sessao_app_antiga
        p2["pedido_em"], p2["quem"] = agora, quem
        if nova:
            _aplicar_troca(x, p2, nova, agora, quem, "gestora trocar")
            resultado.update(feito=True, conversa=nova, titulo=p2.get("titulo_nova", ""))
        else:
            p2["estado"] = "esperando"
            _log(x, "troca pedida; esperando a conversa nova aparecer", agora, marca=marca)
            resultado.update(feito=False, pendente=True)
        return x

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    if resultado.get("feito"):
        _gravar_gestora(slug, resultado["conversa"], resultado["titulo"])
    return resultado or {"feito": False, "pendente": False}


def completar_pendentes(slug, cfg=None, agora=None):
    """Trocas pedidas cuja conversa nova ainda não existia: procura de novo e conclui. Devolve as conversas novas achadas."""
    d = _normalizar(armazem.ler_json(_arq_corrente(slug), _vazio()))
    esperando = [x for x in d["pendentes"] if x.get("estado") == "esperando"]
    if not esperando:
        return []
    agora = agora or time.time()
    achadas = {}
    for x in esperando:
        nova = achar_pela_marca(slug, x["marca"], x.get("criado_em") or 0, ignorar={x.get("conversa_antiga", "")})
        if nova:
            achadas[x["marca"]] = nova
    if not achadas:
        return []
    feitas = []

    def mudar(y):
        y = _normalizar(y)
        for p2 in list(y["pendentes"]):
            nova = achadas.get(p2["marca"])
            if nova and p2.get("estado") == "esperando":
                _aplicar_troca(y, p2, nova, agora, p2.get("quem", "gestora"), "completada pelo Cérebro quando a conversa nova apareceu")
                feitas.append((nova, p2.get("titulo_nova", "")))
        return y

    armazem.atualizar_json(_arq_corrente(slug), _vazio(), mudar)
    for nova, titulo in feitas[-1:]:
        _gravar_gestora(slug, nova, titulo)
    return [n for n, _ in feitas]


# ---------------------------------------------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------------------------------------------
def resumo_para_tela(slug, cfg=None):
    """Para a aba Sessões: corrente (do mais antigo ao atual), vigia e retenção."""
    from . import retencao_gestora
    cfg = cfg if cfg is not None else config.ler_config()
    d = corrente(slug, cfg)
    elos = sorted(d["elos"], key=lambda e: (e.get("estado") == "atual", e.get("inicio") or 0))
    try:
        cand = retencao_gestora.candidatos(slug, cfg)
    except (OSError, ValueError):
        cand = []
    return {"elos": [{k: (mascarar(v) if k == "titulo" and isinstance(v, str) else v) for k, v in e.items()} for e in elos],
            "vigia": vigia(slug, cfg), "candidatos": cand, "autorizado": retencao_gestora.autorizado(slug, cfg),
            "dias_limpeza": parametros(cfg)["dias_limpeza"]}
