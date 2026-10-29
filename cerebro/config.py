"""Caminhos, configuração global e token do Cérebro.

Tudo que o Cérebro guarda fica em ~/.cerebro (nada dentro dos projetos):
    config.json              configuração global (projetos extras/ocultos, sessão gestora por projeto, preços...)
    token                    token aleatório que abre a página (ver servidor.py)
    projetos\\<slug>\\          estado e cache de cada projeto (índice das sessões, mapa gerado)
Para os testes, CEREBRO_HOME e CEREBRO_CLAUDE trocam as duas pastas por pastas de mentira.
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from pathlib import Path

CASA = Path(os.environ.get("CEREBRO_HOME") or (Path.home() / ".cerebro"))
CLAUDE = Path(os.environ.get("CEREBRO_CLAUDE") or (Path.home() / ".claude"))
PROJETOS_CLAUDE = CLAUDE / "projects"

HOST = "127.0.0.1"          # só local: o servidor NUNCA escuta em outro endereço
PORTA_PADRAO = 8188
# Portas que o Cérebro nunca usa: a 80/443 (sites) e as que a pessoa reservar em config.json > "portas_reservadas"
PORTAS_SEMPRE_PROIBIDAS = {80, 443}


def portas_proibidas(cfg=None):
    cfg = cfg if cfg is not None else ler_config()
    extra = {n for n in (cfg.get("portas_reservadas") or []) if isinstance(n, int) and not isinstance(n, bool)}
    return PORTAS_SEMPRE_PROIBIDAS | extra


FONTE_PRECOS = ("Tabela da Anthropic (cópia de 06/10/2026) e, onde ela não informa, regra geral do cache; a leitura de cache do Sonnet 5.5 "
                "foi calibrada pelo custo gravado nos transcritos. Itens marcados * estão a conferir. É estimativa pelo preço de lista.")


def _p(entrada, saida, leitura, w5=None, w1=None, derivados=()):
    """Preços em US$ por milhão de tokens. Campos em 'derivados' não vêm na tabela oficial: foram calculados pela
    regra geral (escrita de cache 5 min = 1,25x a entrada; 1 h = 2x; leitura de cache = 0,1x). A conferir."""
    return {"entrada": entrada, "saida": saida, "cache_leitura": leitura,
            "cache_escrita_5m": w5 if w5 is not None else round(entrada * 1.25, 4),
            "cache_escrita_1h": w1 if w1 is not None else round(entrada * 2, 4),
            "derivados": list(derivados)}


_D = ["cache_escrita_5m", "cache_escrita_1h"]
_DL = ["cache_leitura"] + _D
PRECOS_PADRAO = {
    "claude-opus-5-5": _p(4.0, 20.0, 0.20, derivados=_D),
    "claude-opus-5": _p(5.0, 25.0, 0.50, derivados=_DL),
    "claude-opus-4": _p(5.0, 25.0, 0.50, derivados=_DL),
    # leitura de cache do Sonnet 5.5: US$ 0,10 calibrado pelo custo (cost-state) gravado nos transcritos; a tabela da doc dizia 0,20
    "claude-sonnet-5-5": _p(2.0, 10.0, 0.10, derivados=_DL),
    "claude-sonnet-5": _p(2.0, 10.0, 0.10, derivados=_DL),
    "claude-sonnet-4": _p(3.0, 15.0, 0.30, derivados=_DL),
    "claude-haiku-5-5": _p(0.10, 0.50, 0.01, derivados=_DL),
    "claude-haiku-4": _p(1.0, 5.0, 0.10, derivados=_DL),
    "claude-fable-5": _p(10.0, 50.0, 0.25, derivados=_D),
}

# ---------------------------------------------------------------------------------------------------------------
# Agentes por tipo de tarefa (tipo -> modelo -> quem revisa). A primeira regra que casa vale; a ordem vai do mais
# arriscado para o mais simples (na dúvida, o modelo maior). TODO resultado passa pelo gestor, em qualquer tipo.
# ---------------------------------------------------------------------------------------------------------------
AGENTES_REGRAS_PADRAO = [
    {"id": "critico", "nome": "Arquitetura, segurança, login, pagamentos e revisão final", "modelo": "opus",
     "revisor": "Gestor (modelo maior) revisa linha a linha, com testes e fotos",
     "palavras": ["arquitetura", "segurança", "seguranca", "login", "senha", "pagamento", "cobrança", "cobranca", "token", "auditoria",
                  "revisão", "revisao", "revisar", "revisa", "deploy", "migração", "migracao", "banco de dados", "criptografia",
                  "security", "payment", "architecture", "review", "audit"]},
    {"id": "codigo", "nome": "Código comum e testes", "modelo": "sonnet",
     "revisor": "Gestor confere o diff, roda os testes e olha as fotos",
     "palavras": ["implementar", "implementação", "implementacao", "corrigir", "correção", "correcao", "teste", "testes", "refator",
                  "ajuste", "ajustar", "escrever", "criar", "construir", "bug", "tela", "função", "funcao", "módulo", "modulo",
                  "servidor", "painel", "página", "pagina", "api", "endpoint", "front", "build", "fix", "implement", "feature"]},
    {"id": "mecanico", "nome": "Mecânico: textos, buscas e documentação", "modelo": "haiku",
     "revisor": "Gestor confere uma amostra do resultado antes de aceitar",
     "palavras": ["buscar", "busca", "pesquisar", "procurar", "listar", "levantamento", "texto", "textos", "documentação", "documentacao",
                  "traduzir", "resumir", "resumo", "renomear", "formatar", "inventário", "inventario", "mapear", "ler", "contar",
                  "search", "find", "list", "summarize", "docs", "explore"]},
]
TIPOS_AGENTE_SO_BUSCA = ("explore", "plan", "statusline-setup")      # tipos de agente do Claude Code que só leem: tarefa mecânica
FAMILIAS_MODELO = ("haiku", "sonnet", "opus")

# Comandos que a aba Ferramentas pode rodar (SÓ quando a pessoa clica "Rodar"). Lista FECHADA por projeto: a página só
# manda o id; nada de comando livre. {python} vira o Python que roda o Cérebro. Estes são os PADRÕES iniciais: a lista que
# vale fica em ~/.cerebro/config.json > "comandos" (edite lá; a página nunca altera). Padrões novos de versões futuras
# entram uma única vez, na migração por "versao", sem apagar o que o dono mudou.
# Nenhum comando vem pronto: cada projeto começa com a lista VAZIA. A aba Ferramentas SUGERE comandos detectados no projeto
# (package.json, pytest/unittest, cargo, ruff, eslint) e eles só entram na lista fechada quando a pessoa aprova na página.
# A lista que vale fica em ~/.cerebro/config.json > "comandos" (a página nunca grava comando livre).
COMANDOS_PADRAO = {}

# Fontes do vigia de novidades: só páginas públicas de releases (GET, sem login, sem mandar nada do projeto).
FONTES_NOVIDADES_PADRAO = [
    {"id": "claude-code", "nome": "Claude Code", "repo": "anthropics/claude-code", "tipo": "plataforma",
     "o_que": "Novos recursos do Claude Code: ganchos, agentes, memória, comandos."},
    {"id": "graphify", "nome": "Graphify (motor do mapa)", "repo": "safishamsi/graphify", "tipo": "plataforma",
     "o_que": "O motor que desenha o mapa do código.", "ferramenta": "graphify"},
    {"id": "ruff", "nome": "ruff", "repo": "astral-sh/ruff", "tipo": "ferramenta", "ferramenta": "ruff", "o_que": "Verificação rápida de Python."},
    {"id": "eslint", "nome": "ESLint", "repo": "eslint/eslint", "tipo": "ferramenta", "ferramenta": "eslint", "o_que": "Verificação de JavaScript."},
    {"id": "gitleaks", "nome": "gitleaks", "repo": "gitleaks/gitleaks", "tipo": "ferramenta", "ferramenta": "gitleaks", "o_que": "Acha segredos antes do commit."},
    {"id": "semgrep", "nome": "Semgrep", "repo": "semgrep/semgrep", "tipo": "ferramenta", "ferramenta": "semgrep", "o_que": "Análise estática de segurança."},
    {"id": "osv-scanner", "nome": "OSV-Scanner", "repo": "google/osv-scanner", "tipo": "ferramenta", "ferramenta": "osv-scanner",
     "o_que": "Pacotes com falha de segurança conhecida."},
    {"id": "pip-audit", "nome": "pip-audit", "repo": "pypa/pip-audit", "tipo": "ferramenta", "ferramenta": "pip-audit", "o_que": "Falhas conhecidas nos pacotes Python."},
    {"id": "cargo-deny", "nome": "cargo-deny", "repo": "EmbarkStudios/cargo-deny", "tipo": "ferramenta", "ferramenta": "cargo-deny",
     "o_que": "Falhas e licenças nos pacotes Rust."},
    {"id": "lighthouse", "nome": "Lighthouse", "repo": "GoogleChrome/lighthouse", "tipo": "ferramenta", "ferramenta": "lighthouse",
     "o_que": "Desempenho e acessibilidade das páginas."},
    {"id": "coverage", "nome": "coverage.py", "repo": "nedbat/coveragepy", "tipo": "ferramenta", "ferramenta": "coverage", "o_que": "Cobertura dos testes em Python."},
]

CONFIG_PADRAO = {
    "versao": 5,
    "porta": PORTA_PADRAO,
    "tema": "escuro",                       # escuro | claro
    "projetos_extra": [],                   # pastas de projetos que não aparecem em ~/.claude/projects
    "ocultos": [],                          # slugs que o dono escondeu do painel geral
    "gestoras": {},                         # slug -> {"conversa": id da sessão, "nome": título}
    "portas_reservadas": [],                # portas que o Cérebro nunca usa (além de 80 e 443)
    "nunca_entrar": [],                     # pedaços de nome/caminho de projetos que NUNCA entram no painel (ex.: "financeiro-real")
    "arquivo_status": "",                   # JSON gravado pela sua statusLine com os limites do plano (opcional)
    "primeiro_uso_concluido": False,        # a tela "Bem-vindo" some depois que a pessoa conclui ou dispensa
    "precos": PRECOS_PADRAO,
    "fonte_precos": FONTE_PRECOS,
    # As rotinas só rodam enquanto o servidor está aberto (agendamento no Windows fica para depois, com a sua aprovação).
    "rotinas": {"autoevolucao_dias": 7, "vigia_novidades_dias": 3, "agendamento_ativo": False,
                "analise_automatica": True,      # análise sem IA, com o servidor aberto, a cada 'autoevolucao_dias'
                "novidades_automatica": False,   # consulta a internet: só roda sozinha se você ligar
                "mapa_automatico": True,         # refaz a página do mapa quando o graph.json do projeto fica mais novo
                "mapa_vigia_segundos": 30},
    "revisao_dias": 7,                      # subagentes que terminaram nos últimos N dias entram na fila "a conferir"
    "agentes_regras": AGENTES_REGRAS_PADRAO,
    "comandos": COMANDOS_PADRAO,
    "fontes_novidades": FONTES_NOVIDADES_PADRAO,
    # Departamentos do mapa por projeto. modo "regras" = lista abaixo; sem entrada = uma cor por pasta de primeiro nível
    "departamentos": {},
    "sem_pagina_minutos": 30,               # o servidor encerra sozinho depois disso sem nenhuma página aberta
    # Backup diário (backup.py): pasta "" = ~/CerebroBackup (sempre FORA de .cerebro e .claude); guarda N dias
    "backup": {"pasta": "", "manter_dias": 7},
    # Rotinas no Agendador do Windows (agendador.py): horário/intervalo de cada uma; só valem depois de "Ligar no Windows"
    "rotinas_windows": {},
    # Passa-bastão: avisa quando o contexto do último turno de uma sessão passa de limite_pct% de janela_tokens (ver bastao.py)
    "bastao": {"janela_tokens": 200000, "limite_pct": 60, "recentes_horas": 72},
    "memoria_avisos": {"dias_velha": 30},   # memória que fala de "estado" e não muda há N dias vira aviso "a conferir"
    # Sessão gestora na MESMA sessão + limpeza (gestora_troca.py): ativo = recado de "gestora limpar" + clear_session quando o
    # contexto passa de limite_pct% de janela_tokens; transcrições antigas saem depois de dias_limpeza dias SÓ nos projetos que o
    # dono autorizou (apagar_autorizado: slug -> quando) e com backup conferido (retencao_gestora.py)
    "gestora_rotacao": {"ativo": False, "janela_tokens": 200000, "limite_pct": 60, "dias_limpeza": 7, "nomes_base": {},
                        "apagar_autorizado": {}},
    "capitulos": {"manter_dias": 0},        # capítulos da gestora (capitulos.py): 0 = nunca apagar
}

_trava = threading.RLock()
_acl_feita = set()          # arquivos de token cujo acesso já foi restringido neste processo


class RemocaoRecusada(Exception):
    """Tentativa de apagar algo fora da casa do Cérebro (ou dentro das pastas do Claude / de um projeto)."""


def _dentro(filho, pai):
    try:
        filho.relative_to(pai)
        return True
    except ValueError:
        return False


def conferir_remocao_em(caminho, base, somente_nomes=None, permitir_base=False):
    """TRAVA DE SEGURANÇA ÚNICA do app: devolve o caminho resolvido se puder ser apagado, senão levanta RemocaoRecusada.

    Só vale apagar DENTRO de 'base' (nunca a própria base, salvo permitir_base) e nunca dentro de PROJETOS_CLAUDE / CLAUDE (conversas e
    memória do Claude Code) nem em pasta de projeto. Resolve links/junções antes de conferir, e confere também a pasta pai (um link
    apagado não pode levar o alvo junto). 'somente_nomes' limita o nome do que pode ser apagado (ex.: só o atalho ou só o .venv)."""
    bruto = Path(os.path.abspath(str(caminho)))
    alvo = bruto.resolve()
    base_r = Path(base).resolve()
    proibidas = [PROJETOS_CLAUDE.resolve(), CLAUDE.resolve()]
    pai = bruto.parent.resolve()
    for p in (alvo, pai):
        if any(_dentro(p, x) for x in proibidas):
            raise RemocaoRecusada(f"recusado: {caminho} está nas pastas do Claude Code")
    if (alvo == base_r and not permitir_base) or not _dentro(alvo, base_r) or not _dentro(pai, base_r):
        raise RemocaoRecusada(f"recusado: {caminho} está fora de {base}")
    if somente_nomes is not None and bruto.name not in somente_nomes:
        raise RemocaoRecusada(f"recusado: só posso apagar {', '.join(somente_nomes)} (pedido: {bruto.name})")
    return alvo


def conferir_remocao(caminho):
    """Remoção dentro da casa do Cérebro (CASA, nunca a própria CASA)."""
    return conferir_remocao_em(caminho, CASA)


def remover_em(base, caminho, pasta=False, ignorar_ausente=True, somente_nomes=None):
    """Apaga arquivo (ou, com pasta=True, a árvore inteira) DENTRO de 'base', passando por conferir_remocao_em."""
    import shutil
    alvo = conferir_remocao_em(caminho, base, somente_nomes)
    try:
        if pasta:
            shutil.rmtree(alvo)
        else:
            alvo.unlink()
    except FileNotFoundError:
        if not ignorar_ausente:
            raise


def remover(caminho, pasta=False, ignorar_ausente=True):
    """ÚNICO jeito de apagar dentro do app: arquivo (unlink) ou, com pasta=True, árvore inteira. Passa por conferir_remocao."""
    remover_em(CASA, caminho, pasta, ignorar_ausente)


def remover_casa():
    """Desinstalar: apaga a casa do Cérebro INTEIRA (o que ela guarda: config, dados dos projetos, token) e a própria pasta.
    Recusa se a casa for a pasta do usuário, o .claude ou algo que contenha o .claude, e só aceita uma pasta chamada .cerebro
    (ou a indicada de propósito em CEREBRO_HOME). Cada item passa por remover(), então a trava de sempre vale."""
    casa = CASA.resolve()
    claude = CLAUDE.resolve()
    if casa == Path.home().resolve() or casa == claude or _dentro(claude, casa) or _dentro(casa, claude) or casa.parent == casa:
        raise RemocaoRecusada(f"recusado: {CASA} não pode ser apagada")
    if not os.environ.get("CEREBRO_HOME") and casa.name != ".cerebro":
        raise RemocaoRecusada(f"recusado: {CASA} não parece a casa do Cérebro")
    if not casa.is_dir():
        return
    for filho in sorted(casa.iterdir()):
        remover(filho, pasta=filho.is_dir() and not filho.is_symlink(), ignorar_ausente=True)
    try:
        casa.rmdir()
    except OSError:
        pass


def garantir_casa():
    CASA.mkdir(parents=True, exist_ok=True)
    (CASA / "projetos").mkdir(exist_ok=True)


def pasta_projeto(slug):
    """Pasta de estado/cache do projeto. O slug vira nome de pasta: só letras, dígitos e '-'."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", slug or ""):
        raise ValueError("slug inválido")
    p = CASA / "projetos" / slug
    p.mkdir(parents=True, exist_ok=True)
    return p


def _mesclar(base, extra):
    """O que está gravado vale; o que faltar vem do padrão."""
    saida = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict) and k not in ("precos", "gestoras", "comandos", "departamentos"):
            saida[k] = _mesclar(saida[k], v)
        else:
            saida[k] = v
    return saida


def _migrar(gravada):
    """Config gravada com 'versao' menor: junta os padrões NOVOS sem apagar nada do que o dono mudou. Devolve True se mudou algo.
    Roda uma vez por versão (depois grava 'versao'), então o que o dono apagar de propósito não volta."""
    if not isinstance(gravada.get("versao"), int) or gravada["versao"] >= CONFIG_PADRAO["versao"]:
        return False
    for chave, id_ in (("agentes_regras", "id"), ("fontes_novidades", "id")):
        atual = gravada.get(chave)
        if isinstance(atual, list):
            ids = {x.get(id_) for x in atual if isinstance(x, dict)}
            atual.extend(copy.deepcopy(x) for x in CONFIG_PADRAO[chave] if x[id_] not in ids)
    atual = gravada.get("precos")
    if isinstance(atual, dict):
        for k, v in CONFIG_PADRAO["precos"].items():
            atual.setdefault(k, copy.deepcopy(v))
    deps = gravada.get("departamentos")
    if isinstance(deps, dict):
        for slug_dep in [k for k, v in deps.items() if not isinstance(v, dict) or v.get("modo") not in ("regras", "pastas")]:
            deps.pop(slug_dep)                                   # modos antigos (regras embutidas que saíram do programa): sem entrada = pelas pastas
    for chave in ("portas_reservadas", "nunca_entrar"):         # v4: listas que a pessoa preenche; nunca apaga o que já estiver lá
        if not isinstance(gravada.get(chave), list):
            gravada[chave] = []
    rot = gravada.get("gestora_rotacao")                         # v5: padrão = só compactação automática (zero toque); a limpeza é opcional, desligada
    if not isinstance(rot, dict):
        gravada["gestora_rotacao"] = copy.deepcopy(CONFIG_PADRAO["gestora_rotacao"])
    else:
        rot.setdefault("ativo", False)
        if not isinstance(rot.get("apagar_autorizado"), dict):
            rot["apagar_autorizado"] = {}                        # apagar continua exigindo o sim do dono, projeto a projeto
    gravada["versao"] = CONFIG_PADRAO["versao"]
    return True


def ler_config():
    garantir_casa()
    caminho = CASA / "config.json"
    gravada = None
    try:
        gravada = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(gravada, dict):
            gravada = None
    except (OSError, ValueError):
        gravada = None
    if gravada is None:
        cfg = copy.deepcopy(CONFIG_PADRAO)
        salvar_config(cfg)
        return cfg
    if _migrar(gravada):
        try:
            salvar_config(_mesclar(CONFIG_PADRAO, gravada))
        except OSError:
            pass
    return _mesclar(CONFIG_PADRAO, gravada)


def salvar_config(cfg):
    with _trava:
        garantir_casa()
        caminho = CASA / "config.json"
        tmp = caminho.with_name("config.json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, caminho)


def atualizar_config(mudar):
    """Lê, aplica mudar(cfg) e grava, tudo sob trava."""
    with _trava:
        cfg = ler_config()
        mudar(cfg)
        salvar_config(cfg)
        return cfg


def ler_token():
    """Token aleatório da instalação; criado na primeira vez. O arquivo fica só para o dono (tira a herança de acesso)."""
    garantir_casa()
    caminho = CASA / "token"
    try:
        t = caminho.read_text(encoding="ascii").strip()
        if len(t) >= 32:
            if str(caminho) not in _acl_feita:       # token que já existia: reaplica o acesso só do dono (1x por processo)
                _acl_feita.add(str(caminho))
                _restringir_ao_dono(caminho)
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    caminho.write_text(t, encoding="ascii")
    _acl_feita.add(str(caminho))
    _restringir_ao_dono(caminho)
    return t


def _restringir_ao_dono(caminho):
    """Tira a herança de acesso e deixa só o usuário atual (pelo SID). Se algo der errado e o arquivo ficar ilegível,
    volta ao padrão do Windows: nunca deixa o dono sem acesso ao próprio token. No macOS/Linux: chmod 600 (só o dono lê)."""
    if os.name != "nt":
        try:
            os.chmod(caminho, 0o600)
        except OSError:
            pass
        return
    import subprocess

    from . import acesso_windows
    try:
        sid = acesso_windows.sid_do_usuario()
        if not sid.startswith("S-"):            # reserva: o whoami (lido em bytes; o SID é sempre ASCII, a língua não importa)
            sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=10,
                                 creationflags=0x08000000).stdout.decode("ascii", "replace").strip().split(",")[-1].strip('"')
        if not sid.startswith("S-"):
            return
        subprocess.run(["icacls", str(caminho), "/inheritance:r", "/grant:r", f"*{sid}:F"], capture_output=True, timeout=10,
                       creationflags=0x08000000)
        caminho.read_text(encoding="ascii")
    except Exception:
        try:
            subprocess.run(["icacls", str(caminho), "/reset"], capture_output=True, timeout=10, creationflags=0x08000000)
        except Exception:
            pass


def acesso_so_do_dono(caminho):
    """Confere que só o usuário atual acessa o arquivo. Windows: toda entrada que dá acesso é do SID do usuário (lido pela
    API do Windows, não pelo texto do icacls, que muda com a língua e a codificação). macOS/Linux: modo 600."""
    if os.name != "nt":
        try:
            return (os.stat(caminho).st_mode & 0o077) == 0
        except OSError:
            return False
    from . import acesso_windows
    return acesso_windows.so_do_dono(caminho)


def valor_cookie(token):
    """O cookie não guarda o token: guarda um HMAC dele (estável entre reinícios do servidor)."""
    return hmac.new(token.encode("ascii"), b"cerebro-sessao-v1", hashlib.sha256).hexdigest()
