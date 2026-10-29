"""Instalar ferramentas de qualidade pelo painel (só com o clique do dono na tela de confirmação, ou a CLI com --confirmar).

Segurança:
  * Receitas FECHADAS aqui no código: a página manda só o id da ferramenta; pacote, instalador e argumentos vêm daqui.
    Id desconhecido = recusa.
  * O botão "Instalar" só aparece se o instalador (pip / cargo / winget / npm) existir neste PC.
  * Antes de rodar, a tela mostra o comando exato, de onde vem, onde instala, tamanho e tempo aproximados.
  * Sem shell (lista de argumentos), sem janela, com tempo limite, pasta de trabalho neutra (a casa do Cérebro, nunca a do
    projeto), saída mascarada (segredos) no MESMO histórico de execuções da aba Ferramentas. Uma instalação por vez no PC.
  * Depois de instalar, confere a versão de novo.
  * O instalador (pip / cargo / winget / npm) só é aceito por caminho ABSOLUTO achado em pasta absoluta do PATH (ou na pasta
    conhecida do programa), nunca na pasta atual: um "npm.cmd" plantado na pasta de onde o Cérebro foi aberto nunca roda.
  * Trava: com CEREBRO_TESTE_HOME, CEREBRO_SEM_AGENDADOR ou CEREBRO_SEM_EFEITOS definida (testes e CI) nada é instalado de verdade.
  * Python: instala no Python que roda o Cérebro (o mesmo dos comandos {python} dos projetos e da detecção), só para o seu
    usuário (--user, sem administrador); se o Cérebro roda num ambiente virtual, instala nele (lá --user não existe).
  * winget: --scope user; os termos do repositório e do pacote (--accept-*-agreements) só entram se o dono marcou que aceita.
"""
import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, ferramentas
from .segredos import mascarar

TEMPO_PADRAO = 900

# id da ferramenta (catálogo de ferramentas.py) -> receita. Nada aqui vem da página.
RECEITAS = {
    "ruff": {"via": "pip", "pacote": "ruff", "tamanho": "≈ 10 MB", "tempo": "menos de 1 min", "limite": 600},
    "pip-audit": {"via": "pip", "pacote": "pip-audit", "tamanho": "≈ 5 MB com as dependências", "tempo": "≈ 1 min", "limite": 600},
    "coverage": {"via": "pip", "pacote": "coverage", "tamanho": "≈ 1 MB", "tempo": "menos de 1 min", "limite": 600},
    "semgrep": {"via": "pip", "pacote": "semgrep", "tamanho": "≈ 150 MB", "tempo": "2 a 5 min", "limite": 1800,
                "aviso": "No Windows o Semgrep tem suporte limitado: pode instalar e mesmo assim não rodar (o caminho garantido é o WSL)."},
    "cargo-deny": {"via": "cargo", "pacote": "cargo-deny", "tamanho": "≈ 30 MB (compila do código-fonte no seu PC)", "tempo": "5 a 15 min", "limite": 2400},
    "gitleaks": {"via": "winget", "pacote": "Gitleaks.Gitleaks", "tamanho": "≈ 8 MB", "tempo": "≈ 1 min", "limite": 900},
    "lighthouse": {"via": "npm", "pacote": "lighthouse", "tamanho": "≈ 60 MB", "tempo": "1 a 3 min", "limite": 1200},
}
ORIGEM = {"pip": "PyPI (pypi.org), o repositório oficial de pacotes Python", "cargo": "crates.io, o repositório oficial de pacotes Rust",
          "winget": "repositório oficial do winget (Microsoft); o programa em si é baixado das versões publicadas pelo projeto",
          "npm": "npmjs.com, o repositório oficial de pacotes JavaScript"}

_trava = threading.Lock()
_instalando = {"id": None}
VARIAVEIS_SEM_EFEITOS = ("CEREBRO_TESTE_HOME", "CEREBRO_SEM_AGENDADOR", "CEREBRO_SEM_EFEITOS")


def sem_efeitos():
    """Testes e CI: nenhum instalador roda de verdade."""
    return any(os.environ.get(v) for v in VARIAVEIS_SEM_EFEITOS)


def _exe_seguro(caminho):
    """O caminho só vale se for absoluto, existir e não estiver na pasta atual."""
    caminho = str(caminho or "")
    if not caminho or not os.path.isabs(caminho):
        return None
    if not os.path.exists(caminho) or os.path.isdir(caminho):
        return None
    pasta = os.path.normcase(os.path.dirname(os.path.abspath(caminho)))
    if pasta == os.path.normcase(os.path.abspath(os.getcwd())):
        return None
    return caminho


def _no_path(nome):
    """Como o shutil.which, mas só em pastas ABSOLUTAS do PATH e nunca na pasta atual (o which do Windows olha ela primeiro)."""
    extensoes = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e] if os.name == "nt" else [""]
    for pasta in os.environ.get("PATH", "").split(os.pathsep):
        pasta = pasta.strip().strip('"')
        if not pasta or not os.path.isabs(pasta):
            continue
        for ext in extensoes:
            achado = _exe_seguro(os.path.join(pasta, nome + ext))
            if achado:
                return achado
    return None


def _em_ambiente_virtual():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _achar(via):
    """Caminho do instalador neste PC (ou None). pip: o do Python do Cérebro (sem rodar nada)."""
    if via == "pip":
        return sys.executable if importlib.util.find_spec("pip") is not None else None
    if via == "cargo":
        return _no_path("cargo") or _exe_seguro(Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo"))
    if via == "winget":
        return _no_path("winget") if os.name == "nt" else None
    if via == "npm":
        return _no_path("npm")
    return None


def _argv(receita, exe, aceitar_termos):
    via, pacote = receita["via"], receita["pacote"]
    if via == "pip":
        return [exe, "-m", "pip", "install", *([] if _em_ambiente_virtual() else ["--user"]), "--disable-pip-version-check", "--no-input", pacote]
    if via == "cargo":
        return [exe, "install", "--locked", pacote]
    if via == "winget":
        return [exe, "install", "--id", pacote, "--exact", "--source", "winget", "--scope", "user", "--silent", "--disable-interactivity",
                *(["--accept-source-agreements", "--accept-package-agreements"] if aceitar_termos else [])]
    if via == "npm":
        return [exe, "install", "-g", "--no-fund", "--no-audit", pacote]
    raise ValueError("instalador desconhecido")


def _onde(via):
    if via == "pip":
        if _em_ambiente_virtual():
            return f"no ambiente virtual do Python que roda o Cérebro ({sys.prefix})"
        return (f"no Python que roda o Cérebro ({sys.executable}), só para o seu usuário (--user: sem administrador e sem mexer no Python "
                "dos projetos). É o mesmo Python que a detecção e os comandos {python} usam.")
    if via == "cargo":
        return "na pasta de programas do Rust do seu usuário (~/.cargo/bin)"
    if via == "winget":
        return "só para o seu usuário (--scope user)"
    return "na pasta global do npm do seu usuário (npm install -g)"


def _receita(fid):
    r = RECEITAS.get(fid)
    if r is None:
        raise ValueError(f"não há receita de instalação para {fid!r}: o Cérebro só instala o que está na lista fechada")
    return r


def _nome(fid):
    return next((f["nome"] for f in ferramentas.CATALOGO if f["id"] == fid), fid)


def previa(fid, aceitar_termos=False):
    """O que vai acontecer se o dono confirmar. Não roda nada."""
    r = _receita(fid)
    exe = _achar(r["via"])
    d = {"id": fid, "nome": _nome(fid), "via": r["via"], "pacote": r["pacote"], "disponivel": bool(exe), "de_onde": ORIGEM[r["via"]],
         "onde": _onde(r["via"]), "tamanho": r["tamanho"], "tempo": r["tempo"], "limite": r.get("limite", TEMPO_PADRAO), "aviso": r.get("aviso", ""),
         "precisa_termos": r["via"] == "winget", "comando": "", "argv": []}
    if exe:
        argv = _argv(r, exe, aceitar_termos or r["via"] == "winget")      # a prévia mostra o comando completo que vai rodar
        d.update(argv=argv, comando=" ".join(f'"{a}"' if " " in a else a for a in argv))
    else:
        d["motivo"] = {"pip": "o pip não está disponível no Python do Cérebro", "cargo": "o cargo (Rust) não está instalado neste PC",
                       "winget": "o winget não foi encontrado (só existe no Windows 10/11)", "npm": "o npm (Node.js) não foi encontrado"}[r["via"]]
    return d


def disponiveis():
    """{id: {disponivel, via}} para a aba Ferramentas mostrar (ou não) o botão Instalar. Não roda nada."""
    return {fid: {"disponivel": bool(_achar(r["via"])), "via": r["via"]} for fid, r in RECEITAS.items()}


def _rodar_processo(argv, limite):
    """Roda o instalador (sem shell, sem janela, pasta neutra). Devolve (código, texto, resultado). Os testes trocam esta função.
    TRAVA: em teste/CI nunca roda; programa sem caminho absoluto é recusado."""
    if sem_efeitos():
        raise ValueError("em teste/CI nenhum instalador roda de verdade")
    if not argv or not os.path.isabs(str(argv[0])):
        raise ValueError(f"recusado: o instalador precisa de caminho absoluto ({argv[0] if argv else 'vazio'})")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1", "PIP_NO_INPUT": "1"}
    proc = subprocess.Popen(argv, cwd=ferramentas._cwd_neutro(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=ferramentas.SEM_JANELA | ferramentas.NOVO_GRUPO, env=env)
    try:
        saida, _ = proc.communicate(timeout=limite)
        return proc.returncode, saida.decode("utf-8", "replace"), ("ok" if proc.returncode == 0 else "falha")
    except subprocess.TimeoutExpired:
        ferramentas._matar_arvore(proc)
        try:
            saida, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            saida = b""
        return None, (saida or b"").decode("utf-8", "replace"), "tempo"


def _reconferir(fid, caminho):
    """Detecção de novo (pergunta --version). Os testes trocam esta função."""
    f = next(x for x in ferramentas.CATALOGO if x["id"] == fid)
    with ferramentas._trava:
        ferramentas._cache_det.clear()
    return ferramentas._detectar_uma(f, caminho)


def _executar(slug, caminho, fid, argv, limite, registro):
    codigo, texto, resultado = None, "", "erro"
    try:
        codigo, texto, resultado = _rodar_processo(argv, limite)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        texto, resultado = f"Não consegui iniciar o instalador: {e}\n", "erro"
    try:
        depois = _reconferir(fid, caminho)
    except Exception as e:                        # a conferência nunca derruba o registro
        depois = {"instalada": False, "versao": f"(não consegui conferir: {type(e).__name__})"}
    texto = mascarar(texto[-ferramentas.LIMITE_SAIDA:])
    conf = ("Conferência depois: instalada, " + (depois.get("versao") or "versão não informada")) if depois.get("instalada") else \
        "Conferência depois: o programa ainda não foi encontrado (pode precisar fechar e abrir o Cérebro, ou a pasta não está no PATH)."
    texto = f"$ {' '.join(argv)}\n\n{texto}\n\n{conf}\n"
    fim = time.time()
    registro.update(fim=fim, duracao=round(fim - registro["inicio"], 1), codigo=codigo, resultado=resultado, rodando=False,
                    linhas=texto.count("\n"), versao_depois=depois.get("versao", ""), instalada_depois=bool(depois.get("instalada")),
                    resumo=(("instalado: " + (depois.get("versao") or "ok")) if resultado == "ok" and depois.get("instalada") else
                            "o instalador terminou, mas o programa ainda não aparece (veja a saída)" if resultado == "ok" else
                            "passou do tempo limite e foi interrompido" if resultado == "tempo" else
                            f"terminou com código {codigo}" if resultado != "erro" else "não iniciou")[:160])
    try:
        (ferramentas._pasta_exec(slug) / "saidas" / f"{registro['id']}.txt").write_text(texto, encoding="utf-8", newline="\n")
        ferramentas._guardar_registro(slug, registro)
    except (OSError, config.RemocaoRecusada):
        pass
    finally:
        with ferramentas._trava:
            ferramentas._rodando.pop(slug, None)
        with _trava:
            _instalando["id"] = None
    return registro


def instalar(slug, caminho, fid, confirmar=False, aceitar_termos=False, esperar=False):
    """Instala a ferramenta (receita fechada). confirmar=True é o clique do dono. Em segundo plano, salvo esperar=True (CLI)."""
    if confirmar is not True:
        raise ValueError("instalar precisa da confirmação do dono")
    r = _receita(fid)
    exe = _achar(r["via"])
    if not exe:
        raise ValueError(previa(fid)["motivo"])
    if r["via"] == "winget" and not aceitar_termos:
        raise ValueError("o winget exige aceitar os termos do repositório e do pacote: marque 'aceito os termos' na tela (ou --aceitar-termos)")
    argv = _argv(r, exe, aceitar_termos)
    limite = r.get("limite", TEMPO_PADRAO)
    inicio = time.time()
    registro = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(inicio)) + "-instalar-" + fid, "comando": "instalar-" + fid,
                "nome": "Instalar " + _nome(fid), "ferramenta": fid, "inicio": inicio, "fim": None, "duracao": None, "codigo": None,
                "resultado": "rodando", "resumo": "", "rodando": True, "linhas": 0, "instalacao": True}
    with _trava:
        if _instalando["id"]:
            raise ValueError(f"já há uma instalação em andamento ({_instalando['id']}); espere terminar")
        with ferramentas._trava:
            if slug in ferramentas._rodando:
                raise ValueError("já há um comando rodando neste projeto; espere terminar")
            ferramentas._rodando[slug] = {"proc": None, "registro": registro}
        _instalando["id"] = fid
    if esperar:
        return _executar(slug, caminho, fid, argv, limite, registro)
    threading.Thread(target=_executar, args=(slug, caminho, fid, argv, limite, registro), daemon=True, name=f"instalar-{fid}").start()
    return registro


def saida(slug, registro):
    return ferramentas.saida_da_execucao(slug, registro.get("id", "")) or ""
