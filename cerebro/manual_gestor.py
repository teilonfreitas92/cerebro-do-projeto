"""Manual do gestor automático: ~/.cerebro/GESTOR.md, gerado pelo Cérebro e lido pela sessão gestora de cada projeto.

  * gerar(): escreve o GESTOR.md (atômico) com cabeçalho "<!-- cerebro:gestor versao=X hash=Y -->". Só reescreve quando a
    versão do Cérebro ou o conteúdo (hash) muda. Roda ao subir o servidor e por `cerebro_cli.py manual --gerar`.
  * Menos de 1.500 tokens (estimativa caracteres/4) e sem dado pessoal: o caminho da instalação aparece com a pasta do
    usuário trocada por "~".
  * Quando a VERSÃO muda: a página mostra a faixa "Cérebro atualizado para X: o que mudou para o gestor" (fecha com um clique)
    e a sessão gestora de cada projeto recebe, UMA vez por versão por sessão, a linha "Cérebro atualizado para X — leia
    ~/.cerebro/GESTOR.md (mudou: …)" pelo gancho UserPromptSubmit (ver ligacoes.py). Quem já recebeu fica em
    ~/.cerebro/gestor_manual.json.
  * "O que mudou para o gestor" vem do CHANGELOG.md: as linhas "- Para o gestor: ..." da seção da versão atual.
"""
import hashlib
import os
import re
import threading
import time
from pathlib import Path

from . import __version__, armazem, config

RAIZ = Path(__file__).resolve().parent.parent
LIMITE_TOKENS = 1500
_CAB = re.compile(r"^<!-- cerebro:gestor versao=(\S+) hash=([0-9a-f]{12})")
_trava = threading.Lock()


def _curto(texto, limite=90):
    """Encurta na última palavra inteira (nunca no meio), com reticências."""
    texto = " ".join(str(texto or "").split())
    if len(texto) <= limite:
        return texto
    return texto[:limite].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def arquivo():
    return config.CASA / "GESTOR.md"


def _arq_estado():
    return config.CASA / "gestor_manual.json"


def estimar_tokens(texto):
    return (len(texto) + 3) // 4


def _caminho_curto(p):
    """Caminho com a pasta do usuário trocada por ~ (nada de nome de usuário no manual)."""
    s = str(p).replace("\\", "/")
    casa = str(Path.home()).replace("\\", "/")
    if s.lower().startswith(casa.lower() + "/"):
        s = "~" + s[len(casa):]
    return s


def mudancas_do_changelog(versao=__version__, raiz=None, limite=5):
    """Linhas "Para o gestor:" da seção da versão no CHANGELOG.md (texto depois dos dois-pontos)."""
    try:
        texto = (Path(raiz or RAIZ) / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return []
    secao, dentro = [], False
    for linha in texto.splitlines():
        if linha.startswith("## "):
            if dentro:
                break
            dentro = linha[3:].strip().startswith(versao)
            continue
        if dentro:
            secao.append(linha)
    saida = []
    for linha in secao:
        m = re.match(r"^\s*-\s*Para o gestor:\s*(.+)$", linha)
        if m:
            s = re.sub(r"\*\*|`", "", m.group(1)).strip()
            saida.append(s[:1].upper() + s[1:])
    return saida[:limite]


def _tabela_agentes(cfg):
    linhas = ["| tipo | modelo | revisão |", "|---|---|---|"]
    for r in (cfg.get("agentes_regras") or [])[:6]:
        linhas.append(f"| {_curto(r.get('nome', ''))} | {r.get('modelo', '')} | {_curto(r.get('revisor', ''))} |")
    return linhas


def montar(cfg=None, raiz=None):
    """Corpo do manual (sem o cabeçalho)."""
    cfg = cfg if cfg is not None else config.ler_config()
    raiz = Path(raiz or RAIZ)
    cli = "cerebro_cli.py"
    L = [f"# Manual do gestor — Cérebro do Projeto {__version__}", "",
         "Você é a sessão GESTORA do projeto: planeja, delega a subagentes, confere TUDO antes de entrar e registra decisões. "
         "Este arquivo é refeito pelo Cérebro a cada versão; não edite.", "",
         "## Painel e linha de comando",
         f"- Pasta do Cérebro: `{_caminho_curto(raiz)}`. Painel: `python abrir_cerebro.py` (só 127.0.0.1).",
         f"- CLI (funciona com o painel fechado), rodada NA pasta do Cérebro (cd nela antes, ~ = pasta do usuário): "
         f"`python {cli} <comando>`; <projeto> = nome da pasta do projeto.", "",
         "## Comandos do gestor",
         "- `estado <projeto>` · `a-conferir <projeto>` · `conferir <projeto> <id> --resultado aprovado|corrigido|recusado --nota \"...\"`",
         "- `decisao <projeto> \"texto\" --tipo decisao|regra|ideia --origem dono|gestor` · `decisoes <projeto>`",
         "- `tarefas <projeto> --novas` · `tarefa <projeto> <id> --estado recebida|andamento|conferir|feita --agente X --nota \"...\"`",
         "- `memoria <projeto> --avisos` · `bastao <projeto> <sessao>` · `analisar <projeto>`",
         "- `gestora limpar <projeto>` (antes do clear_session, abaixo) · `gestora estado <projeto>` · `gestora limpeza <projeto>`",
         "- `manual <projeto> --previa` (liga este manual no CLAUDE.local.md; gravar só com o dono: `--instalar --confirmar`)", "",
         "## Delegação e revisão",
         "Qualidade acima de economia: todo resultado de subagente é conferido pelo gestor antes de entrar "
         "(diff, testes, fotos) e marcado com `conferir`. Modelo por tipo de tarefa:", ""]
    L += _tabela_agentes(cfg)
    L += ["", "Registre na hora toda decisão do dono e toda regra nova com `decisao` (o Cérebro guarda e mostra na linha do tempo).", "",
          "## Conversa longa: a gestora nunca é trocada",
          "1. Padrão, sem toque do dono: quando a conversa enche, o Claude Code compacta sozinho; o Cérebro grava antes um capítulo "
          "(feito, falta, decisões, arquivos, ramo) e, logo depois, devolve o resumo aqui. Confira o estado real e continue.",
          "2. Opcional (desligada; o dono liga em Configurações): limpeza na MESMA sessão. Quando o contexto passa do limite, "
          "você recebe o recado. Ao terminar o turno:",
          f"   a) `python {cli} gestora limpar <projeto>`: grava e confere o capítulo. Só siga se ele disser OK;",
          "   b) chame clear_session com session_id \"self\" (o app pede o ok do dono);",
          "   c) a conversa limpa só recomeça com uma mensagem do dono; na primeira resposta diga que foi limpa e que ele pode prosseguir.",
          "   Se disser \"NÃO limpe\", não chame o clear_session: avise o dono.",
          "3. /clear digitado pelo dono funciona igual (o capítulo é gravado depois).",
          "Transcrições antigas saem só com a autorização do dono, após 7 dias e com backup conferido. Capítulos e decisões ficam para sempre.", ""]
    mud = mudancas_do_changelog(raiz=raiz)
    L += [f"## O que mudou para o gestor na {__version__}"]
    L += [f"- {m}" for m in mud] or ["- (nada específico nesta versão)"]
    return "\n".join(L) + "\n"


def _cabecalho(versao, h):
    return f"<!-- cerebro:gestor versao={versao} hash={h} (gerado pelo Cérebro do Projeto; não edite: é refeito sozinho) -->\n"


def ler_cabecalho(caminho=None):
    try:
        with open(caminho or arquivo(), encoding="utf-8") as f:
            m = _CAB.match(f.readline())
    except OSError:
        return None, None
    return (m.group(1), m.group(2)) if m else (None, None)


def gerar(cfg=None, agora=None, forcar=False):
    """Escreve o GESTOR.md se a versão ou o hash mudou. Devolve {mudou, versao, versao_anterior, hash, caminho, tokens}."""
    agora = agora or time.time()
    corpo = montar(cfg)
    h = hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:12]
    with _trava:
        config.garantir_casa()
        versao_ant, hash_ant = ler_cabecalho()
        mudou = forcar or versao_ant != __version__ or hash_ant != h
        if mudou:
            destino = arquivo()
            tmp = destino.with_name(f"GESTOR.md.{os.getpid()}.tmp")
            tmp.write_text(_cabecalho(__version__, h) + corpo, encoding="utf-8", newline="\n")
            os.replace(tmp, destino)
        if versao_ant != __version__:
            def mudar(e):
                if e.get("versao") != __version__:
                    e.update(versao=__version__, anterior=versao_ant or "", mudou_em=agora, visto=False,
                             mudancas=mudancas_do_changelog()[:5])
                return e
            armazem.atualizar_json(_arq_estado(), {}, mudar)
    return {"mudou": mudou, "versao": __version__, "versao_anterior": versao_ant or "", "hash": h, "caminho": str(arquivo()),
            "tokens": estimar_tokens(_cabecalho(__version__, h) + corpo)}


def estado():
    """Para a página: versão do manual e se a faixa "Cérebro atualizado" ainda aparece."""
    e = armazem.ler_json(_arq_estado(), {}) or {}
    versao, h = ler_cabecalho()
    return {"versao": versao or "", "hash": h or "", "arquivo": str(arquivo()), "existe": arquivo().is_file(),
            "mostrar_faixa": bool(e.get("versao") and not e.get("visto")), "atualizado_para": e.get("versao", ""),
            "anterior": e.get("anterior", ""), "mudancas": e.get("mudancas") or []}


def marcar_visto():
    armazem.atualizar_json(_arq_estado(), {}, lambda e: e.update(visto=True, visto_em=time.time()) or e)
    return estado()


def recado_para_sessao(sessao_id):
    """Texto curto para a sessão gestora UMA vez por versão por sessão (None se já recebeu ou se não há manual)."""
    if not sessao_id:
        return None
    versao, _ = ler_cabecalho()
    if not versao:
        return None
    e = armazem.ler_json(_arq_estado(), {}) or {}
    mudancas = e.get("mudancas") or mudancas_do_changelog(versao)
    entregue = {}

    def mudar(d):
        rec = d.setdefault("recebido", {})
        if rec.get(sessao_id) == versao:
            return d
        rec[sessao_id] = versao
        if len(rec) > 300:                                   # guarda só as sessões mais recentes
            for k in list(rec)[:-300]:
                rec.pop(k)
        entregue["sim"] = True
        return d

    armazem.atualizar_json(_arq_estado(), {}, mudar)
    if not entregue:
        return None
    resumo = "; ".join(m.rstrip(".") for m in mudancas[:3])[:500]
    return f"Cérebro atualizado para {versao} — leia ~/.cerebro/GESTOR.md" + (f" (mudou: {resumo})" if resumo else "")
