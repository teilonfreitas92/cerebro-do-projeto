"""Outras IAs (OpenAI, DeepSeek, Grok, Gemini) trabalhando como subagentes do gestor.

O gestor (a sessão do Claude Code) chama:  python cerebro_cli.py ia rodar <projeto> --ia deepseek --tarefa "..."
e a IA escolhida faz o serviço como um subagente do Claude: lê, procura, edita arquivos e roda comandos. Regras:

* Trabalha numa CÓPIA do projeto (git worktree em ~/.cerebro/ias_trabalho/<slug>/<id>, ramo ia/<ia>-<id>). Nunca mexe na
  pasta do projeto; o gestor confere o que mudou (git diff) e só então junta (`ia juntar`) ou joga fora (`ia descartar`).
* Caminhos presos à cópia (nada fora dela, nada dentro de .git). Comandos só os da lista permitida (testes, build, git de
  leitura), sem ; & | < > ` $ % (nada encadeado nem redirecionado).
* As quatro falam o mesmo formato (chat completions com ferramentas, compatível com a OpenAI): um laço só serve para todas.
* A conversa é gravada no formato dos subagentes do Claude Code em ~/.cerebro/ias/<slug>/<sessão do gestor>/agent-ia-*.jsonl:
  Agentes ao vivo (terminal), Custos e a conferência do gestor funcionam sem nada a mais (indice.py lista essa pasta).
* As chaves ficam em ~/.cerebro/ias_chaves.json, legível só pela conta do dono (config._restringir_ao_dono); nunca vão
  para a tela (só os 4 últimos caracteres), para o backup nem para o GitHub. Quem cola a chave é o dono, em Configurações.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .segredos import mascarar

PROVEDORES = {
    "openai": {"nome": "OpenAI", "url": "https://api.openai.com/v1/chat/completions", "modelo": "gpt-5"},
    "deepseek": {"nome": "DeepSeek", "url": "https://api.deepseek.com/chat/completions", "modelo": "deepseek-chat"},
    "grok": {"nome": "Grok (xAI)", "url": "https://api.x.ai/v1/chat/completions", "modelo": "grok-4"},
    "gemini": {"nome": "Gemini (Google)", "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "modelo": "gemini-2.5-pro"},
}
COMANDOS_PADRAO = [
    "python -m unittest", "python -m pytest", "pytest", "py -m unittest", "py -m pytest",
    "npm test", "npm run test", "npm run build", "npm run lint", "node --check", "npx tsc --noEmit",
    "cargo build", "cargo test", "cargo check", "go build", "go test", "go vet", "dotnet build", "dotnet test",
    "git status", "git diff", "git log",
]
ARQ_CHAVES = "ias_chaves.json"
MAX_VOLTAS = 40
MAX_MINUTOS = 30
LIMITE_SAIDA = 8000          # caracteres de cada resultado devolvidos à IA
LIMITE_ARQUIVO = 1_000_000   # bytes que a IA pode ler ou escrever de uma vez
TEMPO_COMANDO = 300
PROIBIDO_NO_COMANDO = re.compile(r"[;&|<>`$%\r\n]")
PULAR_PASTAS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".next"}

SISTEMA = """Você é um subagente de programação comandado por um gestor. Trabalhe na pasta do projeto (uma cópia separada;
caminhos relativos a ela). Use as ferramentas para ler, procurar, editar e testar. Faça só o que a tarefa pede, mantenha o
estilo do código ao redor e não invente arquivos que não precisa. Comandos permitidos (só estes, sem ; & | < > ` $ %):
{comandos}
Quando terminar, responda SEM chamar ferramentas com um resumo curto em português: o que mudou, em quais arquivos, o que
testou e o que ficou pendente. O gestor vai conferir tudo antes de aceitar."""

FERRAMENTAS = [
    {"type": "function", "function": {"name": "Read", "description": "Lê um arquivo de texto (linhas numeradas).",
     "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "offset": {"type": "integer", "description": "primeira linha (1 = início)"},
                    "limit": {"type": "integer", "description": "quantas linhas (padrão 2000)"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "Write", "description": "Cria ou substitui um arquivo inteiro.",
     "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}}},
    {"type": "function", "function": {"name": "Edit", "description": "Troca um trecho exato (que aparece uma única vez) por outro.",
     "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
                    "required": ["file_path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "Glob", "description": "Lista arquivos por padrão (ex.: src/**/*.py).",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "Grep", "description": "Procura uma expressão regular no conteúdo dos arquivos.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "description": "pasta (padrão: todo o projeto)"},
                    "glob": {"type": "string", "description": "filtro de nome, ex.: *.js"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "Bash", "description": "Roda um comando da lista permitida na pasta do projeto.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]


class ErroIA(Exception):
    """Erro que o gestor precisa ler (sem chave nenhuma no texto)."""


# ---------------------------------------------------------------------------------------------------------------- pastas
def pasta_conversas(slug):
    return config.CASA / "ias" / slug


def pasta_trabalho(slug):
    return config.CASA / "ias_trabalho" / slug


def pasta_resultados(slug):
    return config.CASA / "ias" / slug / "_resultados"


# ---------------------------------------------------------------------------------------------------------------- chaves
def _arq_chaves():
    return config.CASA / ARQ_CHAVES


def _ler_chaves():
    try:
        d = json.loads(_arq_chaves().read_text(encoding="ascii"))
        return {k: v for k, v in d.items() if k in PROVEDORES and isinstance(v, str)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_chaves(chaves):
    config.garantir_casa()
    arq = _arq_chaves()
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(chaves), encoding="ascii")
    os.replace(tmp, arq)
    config._restringir_ao_dono(arq)


def guardar_chave(ia, chave):
    if ia not in PROVEDORES:
        raise ErroIA(f"IA desconhecida: {ia}")
    chave = (chave or "").strip()
    if not (10 <= len(chave) <= 400) or not chave.isascii() or any(c.isspace() for c in chave):
        raise ErroIA("chave inválida (cole só a chave, sem espaços)")
    chaves = _ler_chaves()
    chaves[ia] = chave
    _gravar_chaves(chaves)


def remover_chave(ia):
    chaves = _ler_chaves()
    if chaves.pop(ia, None) is not None:
        _gravar_chaves(chaves)


def chave(ia):
    return _ler_chaves().get(ia, "")


def opcoes(cfg=None):
    """config.json > ias: {"modelos": {ia: modelo}, "comandos": [...], "max_voltas": N, "max_minutos": N}."""
    cfg = cfg if cfg is not None else config.ler_config()
    o = cfg.get("ias") if isinstance(cfg.get("ias"), dict) else {}
    modelos = {k: (o.get("modelos") or {}).get(k) or p["modelo"] for k, p in PROVEDORES.items()}
    comandos = [c for c in (o.get("comandos") or COMANDOS_PADRAO) if isinstance(c, str) and c.strip()]
    return {"modelos": modelos, "comandos": comandos,
            "max_voltas": int(o.get("max_voltas") or MAX_VOLTAS), "max_minutos": int(o.get("max_minutos") or MAX_MINUTOS)}


def situacao(cfg=None):
    """Para a tela de Configurações: nunca a chave, só se existe e o final dela."""
    chaves, op = _ler_chaves(), opcoes(cfg)
    return {"ias": [{"id": k, "nome": p["nome"], "modelo": op["modelos"][k], "modelo_padrao": p["modelo"],
                     "configurada": bool(chaves.get(k)), "final": chaves[k][-4:] if chaves.get(k) else ""}
                    for k, p in PROVEDORES.items()],
            "comandos": op["comandos"], "max_voltas": op["max_voltas"], "max_minutos": op["max_minutos"]}


# ---------------------------------------------------------------------------------------------------------------- git
def _git(pasta, *args, timeout=120):
    r = subprocess.run(["git", "-C", str(pasta), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode != 0:
        raise ErroIA(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


# ---------------------------------------------------------------------------------------------------------------- conversa gravada
def _agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


class Conversa:
    """Grava no formato dos subagentes do Claude Code (transcricao.py lê sem saber que é outra IA)."""

    def __init__(self, arquivo, sessao, agente, modelo):
        self.arquivo, self.sessao, self.agente, self.modelo = Path(arquivo), sessao, agente, modelo
        self.ultimo = None
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)

    def _linha(self, tipo, mensagem):
        u = str(uuid.uuid4())
        obj = {"parentUuid": self.ultimo, "isSidechain": True, "type": tipo, "uuid": u, "timestamp": _agora_iso(),
               "sessionId": self.sessao, "agentId": self.agente, "message": mensagem}
        with open(self.arquivo, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.ultimo = u

    def usuario(self, texto):
        self._linha("user", {"role": "user", "content": texto})

    def assistente(self, ident, texto, chamadas, uso):
        conteudo = [{"type": "text", "text": texto}] if texto else []
        conteudo += [{"type": "tool_use", "id": c["id"], "name": c["nome"], "input": c["entrada"]} for c in chamadas]
        self._linha("assistant", {"id": ident, "model": self.modelo, "role": "assistant", "content": conteudo, "usage": uso})

    def resultados(self, lista):
        self._linha("user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": t, "is_error": e}
                                                          for i, t, e in lista]})


def _uso(u):
    """usage no formato da OpenAI -> no do Claude (para o Custos)."""
    u = u if isinstance(u, dict) else {}
    cache = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or u.get("prompt_cache_hit_tokens") or 0)
    entrada = int(u.get("prompt_tokens") or 0)
    return {"input_tokens": max(0, entrada - cache), "output_tokens": int(u.get("completion_tokens") or 0),
            "cache_read_input_tokens": cache, "cache_creation_input_tokens": 0}


# ---------------------------------------------------------------------------------------------------------------- ferramentas
def _caminho(raiz, nome):
    if not isinstance(nome, str) or not nome.strip():
        raise ErroIA("caminho vazio")
    p = Path(nome)
    alvo = (p if p.is_absolute() else raiz / p).resolve()
    if alvo != raiz and raiz not in alvo.parents:
        raise ErroIA("caminho fora da pasta do projeto")
    if ".git" in alvo.relative_to(raiz).parts:
        raise ErroIA("a pasta .git não pode ser mexida")
    return alvo


def comando_permitido(cmd, permitidos):
    if not isinstance(cmd, str) or PROIBIDO_NO_COMANDO.search(cmd):
        return False
    norm = " ".join(cmd.split())
    return any(norm == p or norm.startswith(p + " ") for p in (" ".join(x.split()) for x in permitidos))


def _arquivos(raiz, base=None):
    for pasta, pastas, nomes in os.walk(base or raiz):
        pastas[:] = sorted(d for d in pastas if d not in PULAR_PASTAS)
        for n in sorted(nomes):
            yield Path(pasta) / n


def executar(nome, entrada, raiz, comandos):
    """Roda uma ferramenta. Devolve (texto, erro?). Nunca levanta: o erro volta para a IA corrigir."""
    try:
        e = entrada if isinstance(entrada, dict) else {}
        if nome == "Read":
            p = _caminho(raiz, e.get("file_path"))
            if p.stat().st_size > LIMITE_ARQUIVO * 4:
                return "arquivo grande demais; use Grep para achar o trecho", True
            linhas = p.read_text(encoding="utf-8", errors="replace").splitlines()
            ini = max(1, int(e.get("offset") or 1))
            qtd = max(1, min(int(e.get("limit") or 2000), 4000))
            corpo = "\n".join(f"{i:6}\t{t}" for i, t in enumerate(linhas[ini - 1:ini - 1 + qtd], ini))
            return corpo[:LIMITE_ARQUIVO] or "(arquivo vazio)", False
        if nome == "Write":
            p = _caminho(raiz, e.get("file_path"))
            conteudo = e.get("content")
            if not isinstance(conteudo, str) or len(conteudo.encode("utf-8")) > LIMITE_ARQUIVO:
                return "conteúdo inválido ou grande demais", True
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(conteudo, encoding="utf-8", newline="")
            return f"arquivo gravado: {p.relative_to(raiz).as_posix()}", False
        if nome == "Edit":
            p = _caminho(raiz, e.get("file_path"))
            antigo, novo = e.get("old_string"), e.get("new_string")
            if not isinstance(antigo, str) or not isinstance(novo, str) or not antigo:
                return "old_string e new_string são obrigatórios", True
            texto = p.read_text(encoding="utf-8")
            n = texto.count(antigo)
            if n != 1:
                return f"o trecho aparece {n} vezes; precisa aparecer exatamente 1 (inclua mais contexto)", True
            p.write_text(texto.replace(antigo, novo), encoding="utf-8", newline="")
            return f"arquivo editado: {p.relative_to(raiz).as_posix()}", False
        if nome == "Glob":
            padrao = str(e.get("pattern") or "")
            if not padrao or ".." in Path(padrao).parts or Path(padrao).is_absolute():
                return "padrão inválido", True
            achados = [x.relative_to(raiz).as_posix() for x in raiz.glob(padrao)
                       if x.is_file() and not (PULAR_PASTAS & set(x.relative_to(raiz).parts))]
            return "\n".join(sorted(achados)[:300]) or "(nada encontrado)", False
        if nome == "Grep":
            rx = re.compile(str(e.get("pattern") or ""))
            base = _caminho(raiz, e.get("path") or ".")
            filtro = str(e.get("glob") or "")
            saida = []
            for arq in _arquivos(raiz, base if base.is_dir() else None):
                if filtro and not arq.match(filtro):
                    continue
                try:
                    if arq.stat().st_size > LIMITE_ARQUIVO:
                        continue
                    for i, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
                        if rx.search(linha):
                            saida.append(f"{arq.relative_to(raiz).as_posix()}:{i}: {linha.strip()[:200]}")
                            if len(saida) >= 200:
                                break
                except (OSError, UnicodeDecodeError):
                    continue
                if len(saida) >= 200:
                    break
            return "\n".join(saida) or "(nada encontrado)", False
        if nome == "Bash":
            cmd = e.get("command")
            if not comando_permitido(cmd, comandos):
                return "comando não permitido. Permitidos: " + ", ".join(comandos), True
            args = shlex.split(cmd, posix=True)
            exe = shutil.which(args[0])
            if not exe:
                return f"programa não encontrado: {args[0]}", True
            r = subprocess.run([exe, *args[1:]], cwd=str(raiz), capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=TEMPO_COMANDO, stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)
            texto = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
            if len(texto) > LIMITE_SAIDA:
                texto = "…(início cortado)\n" + texto[-LIMITE_SAIDA:]
            return (texto or "(sem saída)") + f"\n[código de saída {r.returncode}]", r.returncode != 0
        return f"ferramenta desconhecida: {nome}", True
    except subprocess.TimeoutExpired:
        return f"o comando passou de {TEMPO_COMANDO} s e foi parado", True
    except (ErroIA, OSError, ValueError, re.error) as x:
        return f"erro: {x}", True


# ---------------------------------------------------------------------------------------------------------------- chamada à IA
def chamar_api(url, chave_api, corpo, timeout=300):
    """POST no formato chat completions. Tenta de novo em 429/5xx. Erros saem sem a chave."""
    dados = json.dumps(corpo).encode("utf-8")
    for tentativa in range(4):
        req = urllib.request.Request(url, data=dados, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + chave_api})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as x:
            texto = x.read(4000).decode("utf-8", "replace")
            if x.code in (429, 500, 502, 503, 504) and tentativa < 3:
                time.sleep(5 * (tentativa + 1))
                continue
            raise ErroIA(f"a IA respondeu {x.code}: {mascarar(texto)[:600]}")
        except (urllib.error.URLError, TimeoutError, OSError) as x:
            if tentativa < 3:
                time.sleep(5 * (tentativa + 1))
                continue
            raise ErroIA(f"sem conexão com a IA: {x}")
    raise ErroIA("a IA não respondeu")


# ---------------------------------------------------------------------------------------------------------------- o serviço
def rodar(slug, projeto_dir, ia, tarefa, sessao, cfg=None, chamar=None, avisar=None):
    """Faz a tarefa com a IA escolhida numa cópia do projeto. Devolve o resultado (também gravado em _resultados/<id>.json)."""
    avisar = avisar or (lambda _t: None)
    if ia not in PROVEDORES:
        raise ErroIA(f"IA desconhecida: {ia}. Use uma destas: {', '.join(PROVEDORES)}")
    tarefa = (tarefa or "").strip()
    if not tarefa:
        raise ErroIA("a tarefa está vazia")
    chave_api = chave(ia)
    if not chave_api and chamar is None:
        raise ErroIA(f"falta a chave da {PROVEDORES[ia]['nome']}: o dono cola em Configurações › Outras IAs")
    op = opcoes(cfg)
    modelo = op["modelos"][ia]
    projeto = Path(projeto_dir).resolve()
    _git(projeto, "rev-parse", "--is-inside-work-tree")
    base = _git(projeto, "rev-parse", "HEAD").strip()
    ident = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    ramo = f"ia/{ia}-{ident}"
    trabalho = pasta_trabalho(slug) / ident
    trabalho.parent.mkdir(parents=True, exist_ok=True)
    _git(projeto, "worktree", "add", "-b", ramo, str(trabalho), base)
    raiz = trabalho.resolve()
    agente = f"ia-{ia}-{ident}"
    arq = pasta_conversas(slug) / sessao / f"agent-{agente}.jsonl"
    conversa = Conversa(arq, sessao, agente, modelo)
    meta = {"agentType": f"ia:{ia}", "description": tarefa[:300], "model": modelo}
    arq.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    conversa.usuario(tarefa)
    mensagens = [{"role": "system", "content": SISTEMA.format(comandos="\n".join("  " + c for c in op["comandos"]))},
                 {"role": "user", "content": tarefa}]
    chamar = chamar or (lambda corpo: chamar_api(PROVEDORES[ia]["url"], chave_api, corpo))
    resultado = {"id": ident, "ia": ia, "nome": PROVEDORES[ia]["nome"], "modelo": modelo, "ramo": ramo, "pasta": str(raiz),
                 "base": base, "projeto": str(projeto), "tarefa": tarefa, "conversa": arq.name, "inicio": time.time(),
                 "estado": "erro", "resumo": "", "voltas": 0, "tokens_entrada": 0, "tokens_saida": 0}
    limite = time.time() + op["max_minutos"] * 60
    try:
        for volta in range(op["max_voltas"]):
            resultado["voltas"] = volta + 1
            resp = chamar({"model": modelo, "messages": mensagens, "tools": FERRAMENTAS})
            escolha = ((resp or {}).get("choices") or [{}])[0]
            msg = escolha.get("message") or {}
            texto = msg.get("content") if isinstance(msg.get("content"), str) else ""
            brutas = msg.get("tool_calls") or []
            uso = _uso(resp.get("usage"))
            resultado["tokens_entrada"] += uso["input_tokens"] + uso["cache_read_input_tokens"]
            resultado["tokens_saida"] += uso["output_tokens"]
            chamadas = []
            for c in brutas:
                f = c.get("function") or {}
                try:
                    entrada = json.loads(f.get("arguments") or "{}")
                except ValueError:
                    entrada = {"_bruto": str(f.get("arguments"))[:2000]}
                chamadas.append({"id": c.get("id") or uuid.uuid4().hex, "nome": str(f.get("name") or "?"), "entrada": entrada})
            conversa.assistente(resp.get("id") or uuid.uuid4().hex, texto, chamadas, uso)
            # devolve à IA a mensagem como veio (o Gemini exige as assinaturas que vêm junto das chamadas), sem o raciocínio
            mensagens.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
            if not chamadas:
                resultado.update(estado="pronto", resumo=texto or "(a IA terminou sem resumo)")
                break
            saidas = []
            for c in chamadas:
                avisar(f"● {c['nome']}")
                out, erro = executar(c["nome"], c["entrada"], raiz, op["comandos"])
                saidas.append((c["id"], out, erro))
                mensagens.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            conversa.resultados(saidas)
            if time.time() > limite:
                resultado["resumo"] = f"parou: passou de {op['max_minutos']} min"
                break
        else:
            resultado["resumo"] = f"parou: passou de {op['max_voltas']} voltas sem terminar"
    except ErroIA as x:
        resultado["resumo"] = str(x)
        conversa.usuario(f"[Cérebro] {x}")
    finally:
        meta["finished"] = True
        arq.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    # o que mudou fica num commit do ramo da IA: o gestor confere com git diff antes de juntar
    try:
        _git(raiz, "add", "-A")
        if _git(raiz, "status", "--porcelain").strip():
            _git(raiz, "-c", f"user.name=IA {PROVEDORES[ia]['nome']}", "-c", "user.email=ia-do-cerebro",
                 "commit", "-q", "--no-verify", "-m", f"IA {PROVEDORES[ia]['nome']}: {tarefa[:70]}")
        resultado["mudancas"] = _git(projeto, "diff", "--stat", f"{base}..{ramo}").strip()
    except ErroIA as x:
        resultado["mudancas"] = f"(não consegui ler as mudanças: {x})"
    resultado["fim"] = time.time()
    pasta_resultados(slug).mkdir(parents=True, exist_ok=True)
    (pasta_resultados(slug) / f"{ident}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado


def listar(slug):
    saida = []
    for f in sorted(pasta_resultados(slug).glob("*.json"), reverse=True):
        try:
            saida.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return saida


def _achar(slug, ident):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", ident or ""):
        raise ErroIA("id inválido (veja: python cerebro_cli.py ia listar <projeto>)")
    try:
        return json.loads((pasta_resultados(slug) / f"{ident}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErroIA(f"não achei o serviço {ident}")


def juntar(slug, ident):
    """Junta o ramo da IA no ramo atual do projeto (depois de o gestor conferir). Não junta com o projeto sujo."""
    r = _achar(slug, ident)
    projeto = Path(r["projeto"])
    if _git(projeto, "status", "--porcelain", "--untracked-files=no").strip():
        raise ErroIA("o projeto tem mudanças não salvas em commit; salve ou guarde antes de juntar")
    _git(projeto, "merge", "--no-ff", "-m", f"Junta o serviço da IA {r['nome']} ({ident})", r["ramo"])
    _descartar_copia(r)
    r["estado"] = "juntado"
    (pasta_resultados(slug) / f"{ident}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def descartar(slug, ident):
    """Joga fora a cópia e o ramo da IA (só coisas que o próprio Cérebro criou)."""
    r = _achar(slug, ident)
    _descartar_copia(r, apagar_ramo=True)
    r["estado"] = "descartado"
    (pasta_resultados(slug) / f"{ident}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def _descartar_copia(r, apagar_ramo=False):
    projeto, pasta = Path(r["projeto"]), Path(r["pasta"])
    if (config.CASA / "ias_trabalho").resolve() not in pasta.resolve().parents:
        raise ErroIA("a cópia não está na pasta de trabalho das IAs; não mexo nela")
    if pasta.exists():
        _git(projeto, "worktree", "remove", "--force", str(pasta))
    if apagar_ramo and r["ramo"].startswith("ia/"):
        _git(projeto, "branch", "-D", r["ramo"])
