"""Aba Ferramentas: o que existe no PC, o que cada projeto pode rodar e o histórico das execuções.

Segurança:
  * Detecção é SÓ LEITURA: procura o programa e pergunta a versão (`--version`). Nada é instalado.
  * Comando só roda quando a pessoa clica "Rodar" (nunca sozinho), de uma lista FECHADA por projeto no config.json
    (`comandos`). A página manda só o id do comando; o config não aceita comandos vindos da página.
  * Sem shell (lista de argumentos), pasta de trabalho = pasta do projeto, tempo limite, sem janela, saída guardada
    e mascarada (segredos). Um comando por projeto de cada vez.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import armazem, config
from .segredos import mascarar

SEM_JANELA = 0x08000000 if os.name == "nt" else 0
NOVO_GRUPO = 0x00000200 if os.name == "nt" else 0
LIMITE_SAIDA = 200_000              # bytes de saída guardados por execução (o final)
MAX_EXECUCOES = 20
CACHE_DETECCAO = 90                 # segundos

# id, nome, grupo, o que faz, como instalar (SÓ MOSTRADO: instalar precisa da sua aprovação), quando é relevante
CATALOGO = [
    {"id": "ruff", "nome": "ruff", "grupo": "Qualidade do código", "o_que": "Verifica o código Python (erros, nomes indefinidos, exceções engolidas).",
     "instalar": "pip install ruff", "relevante": "py"},
    {"id": "eslint", "nome": "ESLint", "grupo": "Qualidade do código", "o_que": "Verifica o JavaScript (código inalcançável, chave repetida, erros de módulo).",
     "instalar": "npm install  (na pasta do projeto, usa o package.json dele)", "relevante": "js"},
    {"id": "cargo", "nome": "cargo + clippy", "grupo": "Qualidade do código", "o_que": "Compila o programa em Rust e roda o clippy (avisos de qualidade).",
     "instalar": "rustup component add clippy", "relevante": "rust"},
    {"id": "gitleaks", "nome": "gitleaks", "grupo": "Segurança", "o_que": "Acha senhas, chaves e tokens esquecidos no código antes do commit.",
     "instalar": "winget install Gitleaks.Gitleaks   (ou baixar o .exe em github.com/gitleaks/gitleaks/releases)", "relevante": "sempre"},
    {"id": "semgrep", "nome": "Semgrep", "grupo": "Segurança", "o_que": "Análise estática de segurança: padrões perigosos no código.",
     "instalar": "pip install semgrep   (no Windows o suporte é limitado; pode exigir WSL)", "relevante": "sempre"},
    {"id": "pip-audit", "nome": "pip-audit", "grupo": "Dependências", "o_que": "Avisa pacotes Python com falha de segurança conhecida.",
     "instalar": "pip install pip-audit", "relevante": "py"},
    {"id": "cargo-deny", "nome": "cargo-deny", "grupo": "Dependências", "o_que": "Avisa pacotes Rust com falha conhecida e confere licenças.",
     "instalar": "cargo install cargo-deny", "relevante": "rust"},
    {"id": "osv-scanner", "nome": "OSV-Scanner", "grupo": "Dependências", "o_que": "Cruza todos os pacotes do projeto com a base pública de falhas (OSV).",
     "instalar": "baixar o .exe em github.com/google/osv-scanner/releases", "relevante": "sempre"},
    {"id": "coverage", "nome": "coverage.py", "grupo": "Testes", "o_que": "Mede quanto do código os testes realmente executam.",
     "instalar": "pip install coverage", "relevante": "py"},
    {"id": "lighthouse", "nome": "Lighthouse", "grupo": "Desempenho e acessibilidade", "o_que": "Nota de desempenho, acessibilidade e boas práticas das páginas.",
     "instalar": "npm install -g lighthouse", "relevante": "js"},
]

_cache_det = {}
_trava = threading.Lock()
_rodando = {}               # slug -> {"proc": Popen, "registro": {...}}


# ---------------------------------------------------------------------------------------------------------------
# Detecção (só leitura)
# ---------------------------------------------------------------------------------------------------------------
def _exe(nome, caminho_projeto=None):
    """Caminho de um programa DO PC (PATH, ~/.cargo/bin, Scripts do Python) ou None. NUNCA olha dentro do projeto: a detecção
    pergunta `--version` ao que acha, e rodar um binário que veio no projeto seria executar código dele."""
    achado = shutil.which(nome)
    if achado:
        return achado
    pastas = [Path.home() / ".cargo" / "bin", Path(sys.executable).parent / "Scripts"]
    try:
        import sysconfig
        pastas.append(Path(sysconfig.get_path("scripts", f"{os.name}_user")))      # onde o pip --user instala (o instalador do Cérebro usa)
    except (KeyError, OSError):
        pass
    for pasta in pastas:
        for suf in (".exe", ".cmd", ".bat", ""):
            c = pasta / (nome + suf)
            if c.is_file():
                return str(c)
    return None


def _no_node_modules(nome, caminho_projeto):
    """ESLint e afins instalados NO PROJETO: só lê arquivos (existe? qual versão no package.json?); não executa nada."""
    raiz = Path(caminho_projeto) / "node_modules"
    try:
        achou = any((raiz / ".bin" / (nome + suf)).is_file() for suf in (".cmd", ".exe", ".bat", ""))
        versao = ""
        if achou:
            try:
                versao = str(json.loads((raiz / nome / "package.json").read_text(encoding="utf-8")).get("version") or "")[:30]
            except (OSError, ValueError, AttributeError):
                versao = ""
        return achou, versao
    except OSError:
        return False, ""


def _cwd_neutro():
    """Pasta onde as perguntas de versão rodam: a casa do Cérebro (só tem dados), nunca a pasta do usuário nem a do projeto."""
    config.garantir_casa()
    return str(config.CASA)


def _versao(argv, timeout=8):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=SEM_JANELA, stdin=subprocess.DEVNULL, cwd=_cwd_neutro())
        if r.returncode != 0:
            return ""
        linha = (r.stdout.strip() or r.stderr.strip()).splitlines()
        return mascarar(linha[0].strip())[:80] if linha else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _modulo_python(nome):
    """`python -I -m nome --version` -> versão ou '' (módulo ausente). -I: o Python ignora a pasta atual e as variáveis PYTHON*."""
    return _versao([sys.executable, "-I", "-m", nome, "--version"])


def _existe_arquivo(raiz, padrao, profundidade=3):
    raiz = Path(raiz)
    try:
        for p in raiz.glob(padrao):
            return True
        for sub in ("*", "*/*"):
            for d in raiz.glob(sub):
                if d.is_dir() and d.name not in ("node_modules", ".git", "target", "__pycache__", "graphify-out") and any(d.glob(padrao)):
                    return True
    except OSError:
        pass
    return False


def tipo_do_projeto(caminho):
    """Que tipo de código o projeto tem: py / js / rust (só olha nomes de arquivo, rápido)."""
    raiz = Path(caminho)
    tipos = set()
    try:
        if any(raiz.glob("*.py")) or any(raiz.glob("*/*.py")) or (raiz / "requirements.txt").is_file() or (raiz / "pyproject.toml").is_file():
            tipos.add("py")
        if (raiz / "package.json").is_file() or any(raiz.glob("*.js")) or any(raiz.glob("public/*.js")) or any(raiz.glob("*/*.js")):
            tipos.add("js")
        if (raiz / "Cargo.toml").is_file() or _existe_arquivo(raiz, "Cargo.toml"):
            tipos.add("rust")
    except OSError:
        pass
    return tipos


def _detectar_uma(ferr, caminho):
    fid = ferr["id"]
    r = {"instalada": False, "versao": "", "onde": ""}
    if fid == "ruff":
        exe = _exe("ruff", caminho)
        v = _versao([exe, "--version"]) if exe else _modulo_python("ruff")
        r.update(instalada=bool(v), versao=v, onde=exe or ("python -m ruff" if v else ""))
    elif fid == "eslint":
        exe = _exe("eslint", caminho)
        v = _versao([exe, "--version"], 15) if exe else ""
        if v:
            r.update(instalada=True, versao="v" + v.lstrip("v"), onde=exe)
        else:                                            # do projeto: só lê node_modules, não executa
            achou, ver = _no_node_modules("eslint", caminho)
            r.update(instalada=achou, versao=(("v" + ver + " · ") if ver else "") + "encontrado em node_modules do projeto" if achou else "",
                     onde=str(Path(caminho) / "node_modules" / ".bin") if achou else "")
    elif fid == "cargo":
        exe = _exe("cargo", caminho)
        v = _versao([exe, "--version"]) if exe else ""
        clippy = _exe("cargo-clippy", caminho)
        r.update(instalada=bool(v), versao=(v + (" · clippy ok" if clippy else " · sem clippy")) if v else "", onde=exe or "")
    elif fid in ("gitleaks", "semgrep", "osv-scanner", "cargo-deny", "lighthouse"):
        exe = _exe(fid, caminho)
        v = _versao([exe, "--version"], 20) if exe else ""
        r.update(instalada=bool(exe), versao=v or ("encontrado" if exe else ""), onde=exe or "")
    elif fid == "pip-audit":
        exe = _exe("pip-audit", caminho)
        v = _versao([exe, "--version"]) if exe else _modulo_python("pip_audit")
        r.update(instalada=bool(v), versao=v, onde=exe or ("python -m pip_audit" if v else ""))
    elif fid == "coverage":
        v = _modulo_python("coverage")
        r.update(instalada=bool(v), versao=v.splitlines()[0] if v else "", onde="python -m coverage" if v else "")
    return r


def detectar(caminho_projeto, forcar=False):
    """Lista do catálogo com instalada/versão e se faz sentido para este projeto. Cache de 90 s (roda alguns `--version`)."""
    chave = str(caminho_projeto)
    with _trava:
        c = _cache_det.get(chave)
        if c and not forcar and time.time() - c[0] < CACHE_DETECCAO:
            return c[1]
    tipos = tipo_do_projeto(caminho_projeto)
    saida = []
    for f in CATALOGO:
        d = _detectar_uma(f, caminho_projeto)
        rel = f["relevante"]
        d.update(id=f["id"], nome=f["nome"], grupo=f["grupo"], o_que=f["o_que"], instalar=f["instalar"],
                 relevante=(rel == "sempre" or rel in tipos), tipos=sorted(tipos))
        saida.append(d)
    with _trava:
        _cache_det[chave] = (time.time(), saida)
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Graphify e baterias de teste
# ---------------------------------------------------------------------------------------------------------------
def exe_graphify():
    """Caminho do Graphify instalado (PATH, ou ~/.local/bin onde o `uv tool` instala) ou None."""
    exe = shutil.which("graphify")
    if exe:
        return exe
    pastas = [Path.home() / ".local" / "bin", Path(sys.executable).parent / "Scripts", Path(sys.executable).parent]
    try:
        import sysconfig
        pastas.append(Path(sysconfig.get_path("scripts", f"{os.name}_user")))      # onde o pip --user instala programas
    except (KeyError, OSError):
        pass
    for pasta in pastas:
        for nome in ("graphify.exe", "graphify"):
            alt = pasta / nome
            if alt.is_file():
                return str(alt)
    return None


def versao_graphify():
    """Versão do Graphify instalado ('' se não achar). Só leitura: pergunta `--version`."""
    exe = exe_graphify()
    return _versao([exe, "--version"]) if exe else ""


def estado_graphify(caminho_projeto, slug):
    versao = versao_graphify()
    graph = Path(caminho_projeto) / "graphify-out" / "graph.json"
    d = {"instalado": bool(versao), "versao": versao, "mapa": graph.is_file(), "graph_em": None, "graph_tam": None, "totais": None,
         "pagina_em": None}
    try:
        if graph.is_file():
            st = graph.stat()
            d.update(graph_em=st.st_mtime, graph_tam=st.st_size)
    except OSError:
        pass
    dados = config.CASA / "projetos" / slug / "mapa" / "dados.js"
    try:
        if dados.is_file():
            d["pagina_em"] = dados.stat().st_mtime
            with open(dados, "rb") as f:
                cab = f.read(6000).decode("utf-8", "replace")
            m = re.search(r'"totais":(\{[^}]*\})', cab)
            if m:
                d["totais"] = json.loads(m.group(1))
    except (OSError, ValueError):
        pass
    return d


RESULTADOS_CONHECIDOS = {
    "testes": ["testes/resultado.json", "testes/ultimo_resultado.json", ".cerebro/testes.json", "test-results.json"],
    "lint": ["testes/resultado_lint.json", ".cerebro/lint.json", "lint-resultado.json"],
}


def _resumo_resultado(d):
    if not isinstance(d, dict):
        return ""
    for chave in ("resumo", "summary", "status", "resultado"):
        if isinstance(d.get(chave), str):
            return d[chave][:200]
    partes = [f"{k}: {d[k]}" for k in ("passou", "passed", "falhou", "failed", "erros", "errors", "total") if k in d]
    return ", ".join(partes)[:200]


def baterias(caminho_projeto):
    """Arquivos de resultado conhecidos + quantos scripts de teste o projeto tem e como se rodam."""
    raiz = Path(caminho_projeto)
    resultados = {}
    for tipo, nomes in RESULTADOS_CONHECIDOS.items():
        for n in nomes:
            f = raiz / n
            try:
                if f.is_file():
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        d = None
                    resultados[tipo] = {"arquivo": n, "atualizado": f.stat().st_mtime, "resumo": _resumo_resultado(d)}
                    break
            except OSError:
                continue
    info = {"resultados": resultados, "scripts": 0, "como_rodar": "", "pasta": ""}
    for pasta in ("testes", "tests", "test"):
        p = raiz / pasta
        if p.is_dir():
            try:
                info["scripts"] = sum(1 for f in p.iterdir() if f.is_file() and re.match(r"^(t_\d+|test_).*\.(py|js)$", f.name))
            except OSError:
                pass
            info["pasta"] = pasta
            for runner in ("rodar_testes.py", "run_tests.py"):
                if (p / runner).is_file():
                    info["como_rodar"] = f"python {pasta}/{runner}"
                    break
            if not info["como_rodar"] and (p / "__init__.py").is_file():
                info["como_rodar"] = "python -m unittest discover"
            break
    if not info["como_rodar"] and (raiz / "pytest.ini").is_file():
        info["como_rodar"] = "pytest"
    return info


# ---------------------------------------------------------------------------------------------------------------
# Comandos permitidos e execução
# ---------------------------------------------------------------------------------------------------------------
def comandos_do_projeto(cfg, slug):
    """Lista fechada (validada) de comandos que a página pode pedir para este projeto."""
    saida = []
    for c in ((cfg.get("comandos") or {}).get(slug) or []):
        try:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id", ""))
            argv = c.get("argv")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,40}", cid) or not isinstance(argv, list) or not 1 <= len(argv) <= 12:
                continue
            if not all(isinstance(a, str) and 0 < len(a) <= 300 and "\x00" not in a for a in argv):
                continue
            timeout = c.get("timeout", 600)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 5 <= timeout <= 3600:
                timeout = 600
            saida.append({"id": cid, "nome": str(c.get("nome") or cid)[:80], "descricao": str(c.get("descricao") or "")[:300],
                          "ferramenta": str(c.get("ferramenta") or ""), "argv": [str(a) for a in argv], "timeout": timeout})
        except (TypeError, ValueError):
            continue
    return saida


def _resolver_argv(argv, raiz):
    """{python} -> Python do Cérebro. O primeiro item (npm, cargo...) é procurado no PATH do PC (sem shell, funciona com npm.cmd no
    Windows). Caminho relativo de script tem de ficar dentro do projeto e existir."""
    saida = []
    for i, a in enumerate(argv):
        a = sys.executable if a == "{python}" else a
        if i == 0 and a != sys.executable and not os.path.isabs(a):
            achado = shutil.which(a)
            if achado is None:
                raise ValueError(f"o programa {a!r} não foi encontrado neste PC (instale-o ou tire este comando da lista)")
            a = achado
        if i > 0 and re.search(r"\.(py|js|mjs|bat|cmd|ps1)$", a, re.I) and not os.path.isabs(a):
            alvo = (Path(raiz) / a).resolve()
            try:
                alvo.relative_to(Path(raiz).resolve())
            except ValueError:
                raise ValueError(f"o script {a!r} fica fora do projeto")
            if not alvo.is_file():
                raise ValueError(f"o script {a!r} não existe neste projeto")
        saida.append(a)
    return saida


def _pasta_exec(slug):
    p = config.pasta_projeto(slug) / "ferramentas"
    (p / "saidas").mkdir(parents=True, exist_ok=True)
    return p


def _arq_exec(slug):
    return _pasta_exec(slug) / "execucoes.json"


def _resumo_saida(texto, codigo, resultado):
    linhas = [l for l in texto.splitlines() if l.strip()]
    ok = sum(1 for l in linhas if re.match(r"^OK\b", l))
    falha = sum(1 for l in linhas if re.match(r"^FALHA\b", l))
    if ok or falha:
        return f"{ok} etapa(s) OK, {falha} com falha"
    if resultado == "tempo":
        return "passou do tempo limite e foi interrompido"
    return (linhas[-1][:160] if linhas else "(sem saída)")


def _matar_arvore(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=SEM_JANELA)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def _executar(slug, caminho, cmd, argv, registro):
    """Roda o comando (thread). Guarda o final da saída, mascarada."""
    bufer = bytearray()
    codigo, resultado = None, "erro"
    proc = None
    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(argv, cwd=str(caminho), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=SEM_JANELA | NOVO_GRUPO, env=env)
        with _trava:
            if slug in _rodando:
                _rodando[slug]["proc"] = proc

        def ler():
            for bloco in iter(lambda: proc.stdout.read(4096), b""):
                bufer.extend(bloco)
                if len(bufer) > LIMITE_SAIDA * 2:
                    del bufer[:len(bufer) - LIMITE_SAIDA]

        leitor = threading.Thread(target=ler, daemon=True)
        leitor.start()
        try:
            codigo = proc.wait(timeout=cmd["timeout"])
            resultado = "ok" if codigo == 0 else "falha"
        except subprocess.TimeoutExpired:
            _matar_arvore(proc)
            resultado = "tempo"
            try:
                codigo = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                codigo = None
        leitor.join(timeout=5)
        try:
            proc.stdout.close()
        except OSError:
            pass
    except (OSError, ValueError) as e:
        bufer.extend(f"Não consegui iniciar o comando: {e}\n".encode("utf-8"))
        resultado = "erro"
    finally:
        try:
            texto = mascarar(bytes(bufer[-LIMITE_SAIDA:]).decode("utf-8", "replace"))
            fim = time.time()
            registro.update(fim=fim, duracao=round(fim - registro["inicio"], 1), codigo=codigo, resultado=resultado,
                            resumo=_resumo_saida(texto, codigo, resultado), rodando=False, linhas=texto.count("\n"))
            (_pasta_exec(slug) / "saidas" / f"{registro['id']}.txt").write_text(texto, encoding="utf-8", newline="\n")
            _guardar_registro(slug, registro)
        except (OSError, config.RemocaoRecusada):         # não consegui guardar: o comando já terminou, a trava abaixo TEM de soltar
            pass
        finally:
            with _trava:
                _rodando.pop(slug, None)


def _guardar_registro(slug, registro):
    def mudar(d):
        d["itens"] = [x for x in d["itens"] if x.get("id") != registro["id"]]
        d["itens"].insert(0, {k: v for k, v in registro.items() if k != "proc"})
        for velho in d["itens"][MAX_EXECUCOES:]:
            try:
                config.remover(_pasta_exec(slug) / "saidas" / f"{velho.get('id')}.txt")
            except (OSError, config.RemocaoRecusada):
                pass
        d["itens"] = d["itens"][:MAX_EXECUCOES]
        return d

    armazem.atualizar_json(_arq_exec(slug), {"itens": []}, mudar)


def rodar(slug, caminho, cfg, comando_id):
    """Inicia o comando da lista fechada em segundo plano. Levanta ValueError se não puder."""
    cmd = next((c for c in comandos_do_projeto(cfg, slug) if c["id"] == comando_id), None)
    if cmd is None:
        raise ValueError("este comando não está na lista permitida do projeto")
    if not Path(caminho).is_dir():
        raise ValueError("a pasta do projeto não existe")
    argv = _resolver_argv(cmd["argv"], caminho)
    inicio = time.time()
    registro = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(inicio)) + "-" + cmd["id"], "comando": cmd["id"], "nome": cmd["nome"],
                "ferramenta": cmd["ferramenta"], "inicio": inicio, "fim": None, "duracao": None, "codigo": None, "resultado": "rodando",
                "resumo": "", "rodando": True, "linhas": 0}
    with _trava:
        if slug in _rodando:
            raise ValueError("já há um comando rodando neste projeto; espere terminar")
        if len(_rodando) >= 2:
            raise ValueError("já há dois comandos rodando em outros projetos; espere um terminar")
        _rodando[slug] = {"proc": None, "registro": registro}
    threading.Thread(target=_executar, args=(slug, caminho, cmd, argv, registro), daemon=True, name=f"ferr-{slug}").start()
    return registro


def estado_execucoes(slug):
    d = armazem.ler_json(_arq_exec(slug), {"itens": []})
    itens = d.get("itens", []) if isinstance(d, dict) else []
    with _trava:
        atual = dict(_rodando[slug]["registro"]) if slug in _rodando else None
    return {"rodando": atual, "historico": itens}


def saida_da_execucao(slug, exec_id):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z0-9_\-]{1,41}", exec_id or ""):
        return None
    f = _pasta_exec(slug) / "saidas" / f"{exec_id}.txt"
    try:
        return f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def ultima_por_ferramenta(slug):
    """ferramenta (id do catálogo) -> execução mais recente. Também 'cmd:<id>' por comando."""
    saida = {}
    for x in estado_execucoes(slug)["historico"]:
        for chave in (x.get("ferramenta"), "cmd:" + str(x.get("comando"))):
            if chave and chave not in saida:
                saida[chave] = x
    return saida


def parar_todos():
    """Chamado ao encerrar o servidor: não deixa comando órfão."""
    with _trava:
        itens = [v.get("proc") for v in _rodando.values()]
    for p in itens:
        if p is not None:
            _matar_arvore(p)


def montar(slug, caminho, cfg, forcar=False):
    """Tudo que a aba Ferramentas mostra."""
    cmds = comandos_do_projeto(cfg, slug)
    ex = estado_execucoes(slug)
    ultimas = ultima_por_ferramenta(slug)
    det = detectar(caminho, forcar)
    cartoes = []
    for d in det:
        meus = [c for c in cmds if c["ferramenta"] == d["id"]]
        cartoes.append({**d, "comandos": [{"id": c["id"], "nome": c["nome"], "descricao": c["descricao"]} for c in meus],
                        "ultima": ultimas.get(d["id"])})
    return {"cartoes": cartoes, "comandos": [{k: c[k] for k in ("id", "nome", "descricao", "ferramenta", "timeout")} for c in cmds],
            "rodando": ex["rodando"], "historico": ex["historico"], "graphify": estado_graphify(caminho, slug), "baterias": baterias(caminho)}
