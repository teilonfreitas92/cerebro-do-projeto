"""Instalador dos ganchos (hooks) e da statusLine do Cérebro no settings.json do Claude Code. ESCREVE FORA DE ~/.cerebro:
só com confirmação explícita (botão "Ligar" na página ou CLI com --confirmar), sempre com cópia de segurança antes.

    previa(...)                     o que muda (diferença exata, linha a linha), sem gravar nada
    instalar(confirmar=True, ...)   mescla as entradas do Cérebro
    remover(confirmar=True, ...)    tira SÓ as entradas do Cérebro
    estado()                        o que está instalado agora

MESCLA, nunca sobrescreve: lê o JSON que existe, preserva TUDO (outros hooks, permissions, env, statusLine, chaves desconhecidas,
ordem das chaves) e só acrescenta entradas do Cérebro. "É do Cérebro" é conferido de forma EXATA (nunca por pedaço de texto,
para não apagar gancho de outra ferramenta com nome parecido):
  * gancho "command": o comando TERMINA no cerebro_hook.py DESTA instalação (qualquer Python antes dele);
  * gancho "http": a url é exatamente http://127.0.0.1:<porta>/api/hooks/evento (ou localhost);
  * statusLine: o comando TERMINA no cerebro_statusline.py DESTA instalação.
Instalar duas vezes não duplica. JSON atual inválido: recusa (não mexe). Cópia em ~/.cerebro/copias/settings/<data-hora>.json e
escrita atômica (arquivo temporário + troca). Se o arquivo mudou entre a leitura e a gravação (o Claude Code gravou no meio),
recusa sem trocar. O arquivo é ~/.claude/settings.json (ou CEREBRO_CLAUDE_SETTINGS, usada nos testes).

Dois modos para os ganchos (doc oficial: https://code.claude.com/docs/en/hooks):
  * "comando" (padrão): {"type": "command", "async": true} rodando cerebro_hook.py com pythonw. "async" faz o Claude Code
    seguir SEM esperar; o script lê a porta do servidor.json e, com o Cérebro fechado, sai na hora. Zero atraso.
  * "http": {"type": "http", "url": "http://127.0.0.1:<porta>/api/hooks/evento", "timeout": 2}. Mais leve, mas o Claude Code
    ESPERA a resposta: com o Cérebro fechado, no Windows, a recusa de conexão leva ~2 s por evento. Só para quem deixa o
    Cérebro sempre aberto. A porta fica gravada na url: mudou a porta, reinstale.
"""
import copy
import difflib
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

from . import armazem, config, ganchos_eventos
from .segredos import mascarar

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT_HOOK = RAIZ / "cerebro_hook.py"
SCRIPT_STATUS = RAIZ / "cerebro_statusline.py"
URL_DO_CEREBRO = re.compile(r"http://(?:127\.0\.0\.1|localhost):\d{1,5}" + re.escape(ganchos_eventos.ROTA))
MODOS = ("comando", "http")
MODOS_STATUS = ("instalar", "encadear", "substituir")


class SettingsInvalido(ValueError):
    """O settings.json atual não é um JSON válido (ou tem um formato que não reconheço): não mexo."""


class PrecisaDecidir(ValueError):
    """Já existe uma statusLine de outra pessoa/ferramenta: é preciso escolher encadear ou substituir."""


class SettingsMudou(ValueError):
    """O settings.json mudou entre a leitura e a gravação (o Claude Code ou outra ferramenta gravou no meio): não troco."""


def caminho_settings():
    extra = os.environ.get("CEREBRO_CLAUDE_SETTINGS")
    return Path(extra) if extra else config.CLAUDE / "settings.json"


def arquivo_estado():
    return config.CASA / "ganchos.json"


def ler_estado():
    d = armazem.ler_json(arquivo_estado(), {}) or {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------------------------------------------------------
# Leitura e escrita do settings.json
# ---------------------------------------------------------------------------------------------------------------
def ler_settings():
    """(dados, texto original, existe). Arquivo ausente = {} (será criado). JSON inválido ou que não é objeto: SettingsInvalido."""
    p = caminho_settings()
    try:
        texto = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}, "", False
    except OSError as e:
        raise SettingsInvalido(f"não consegui ler {p}: {e}") from None
    if not texto.strip():
        return {}, texto, True
    try:
        dados = json.loads(texto)
    except ValueError as e:
        raise SettingsInvalido(f"o {p.name} atual não é um JSON válido ({e}); conserte antes (nada foi alterado)") from None
    if not isinstance(dados, dict):
        raise SettingsInvalido(f"o {p.name} atual não é um objeto JSON; nada foi alterado")
    h = dados.get("hooks")
    if h is not None and (not isinstance(h, dict) or not all(isinstance(v, list) for v in h.values())):
        raise SettingsInvalido("a chave 'hooks' tem um formato que não reconheço; nada foi alterado")
    return dados, texto, True


def _texto_novo(dados, original):
    nl = "\r\n" if "\r\n" in original else "\n"
    return json.dumps(dados, ensure_ascii=False, indent=2).replace("\n", nl) + nl


def _diferenca(original, novo, segredos=()):
    linhas = difflib.unified_diff(original.splitlines(), novo.splitlines(), "settings.json (agora)", "settings.json (depois)", lineterm="", n=2)
    texto = "\n".join(linhas)
    for s in segredos:
        if s:
            texto = texto.replace(s, "[segredo dos ganchos]")
    return mascarar(texto)


def _copia_de_seguranca(original):
    pasta = config.CASA / "copias" / "settings"
    pasta.mkdir(parents=True, exist_ok=True)
    base = time.strftime("%Y%m%d-%H%M%S")
    alvo, n = pasta / f"{base}.json", 1
    while alvo.exists():
        n += 1
        alvo = pasta / f"{base}-{n}.json"
    alvo.write_text(original, encoding="utf-8", newline="")
    config._restringir_ao_dono(alvo)            # a cópia pode ter chaves do bloco env: só o dono lê
    return alvo


def _texto_atual(p):
    try:
        return p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


def _conferir_sem_mudanca(p, original):
    if original is not None and _texto_atual(p) != original:
        raise SettingsMudou(f"o {p.name} mudou enquanto eu preparava a mudança (o Claude Code pode ter gravado agora); "
                            "nada foi alterado: veja a prévia de novo e repita")


def _tirar_temporario(tmp):
    """Temporário que sobrou de uma gravação que falhou: sai de perto do settings.json (vai para a casa do Cérebro) e só então
    é apagado, pela trava de sempre (config.remover nunca apaga nada dentro do .claude)."""
    try:
        if not tmp.is_file():
            return
        lixo = config.CASA / "copias" / "settings" / "temporarios"
        lixo.mkdir(parents=True, exist_ok=True)
        destino = lixo / f"{tmp.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(tmp, destino)
        config.remover(destino)
    except (OSError, config.RemocaoRecusada):
        pass


def _gravar_atomico(texto, original=None):
    """Grava o texto novo no lugar do settings.json. 'original' = o texto lido no começo: se o arquivo não é mais esse, recusa."""
    json.loads(texto)                              # confere ANTES de criar qualquer arquivo: JSON quebrado nunca vira temporário
    p = caminho_settings()
    p.parent.mkdir(parents=True, exist_ok=True)
    _conferir_sem_mudanca(p, original)
    tmp = p.with_name(p.name + ".cerebro.tmp")     # nome fixo: nunca acumula temporários
    try:
        tmp.write_text(texto, encoding="utf-8", newline="")
        _conferir_sem_mudanca(p, original)         # de novo, logo antes de trocar (a janela fica de milissegundos)
        os.replace(tmp, p)
    except BaseException:
        _tirar_temporario(tmp)
        raise


# ---------------------------------------------------------------------------------------------------------------
# Entradas do Cérebro
# ---------------------------------------------------------------------------------------------------------------
def _caminho_cmd(p):
    """Barras normais (o Claude Code roda o comando pelo Git Bash no Windows, que come as contrabarras); aspas só se houver espaço."""
    s = str(p).replace("\\", "/")
    return f'"{s}"' if " " in s else s


def _python(sem_janela):
    exe = Path(sys.executable)
    if sem_janela and os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.is_file():
            return w
    return exe


def comando_hook():
    return f"{_caminho_cmd(_python(True))} {_caminho_cmd(SCRIPT_HOOK)}"


def comando_statusline():
    return f"{_caminho_cmd(_python(False))} {_caminho_cmd(SCRIPT_STATUS)}"


def entrada_hook(modo="comando", porta=None, token=""):
    if modo == "http":
        porta = porta or config.ler_config().get("porta") or config.PORTA_PADRAO
        return {"type": "http", "url": f"http://{config.HOST}:{porta}{ganchos_eventos.ROTA}", "timeout": 2,
                "headers": {ganchos_eventos.CABECALHO: token}}
    return {"type": "command", "command": comando_hook(), "async": True}


ARGS_DO_CEREBRO = ("--sincrono",)      # únicos argumentos que o Cérebro põe DEPOIS do script (grupo SessionStart síncrono)
# "startup" também: no app do Claude, a conversa que nasce depois do clear_session chega como "startup" (visto em 29/10/2026).
# O hook sai na hora em sessão que não é a gestora com limpeza pendente (ver gestora_troca.ao_iniciar_sessao).
MATCHER_SINCRONO = "startup|clear|compact"


def _ultimo_argumento(comando):
    """O script que o comando roda (último pedaço, ignorando um argumento final conhecido do Cérebro), sem as aspas.
    '' se não der para separar."""
    try:
        partes = shlex.split(comando.replace("\\", "/"), posix=True)     # contrabarra do Windows não é escape aqui
    except ValueError:
        return ""
    if len(partes) > 1 and partes[-1] in ARGS_DO_CEREBRO:
        partes = partes[:-1]
    return partes[-1] if partes else ""


def _mesmo_arquivo(a, b):
    a = str(a or "")
    if not os.path.isabs(a):
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(str(b)))


def _roda_o_script(comando, script):
    """O comando termina no script DESTA instalação? (o formato que o Cérebro grava: '<python> <script>', aspas só com espaço)."""
    return isinstance(comando, str) and _mesmo_arquivo(_ultimo_argumento(comando), script)


def eh_do_cerebro(h):
    if not isinstance(h, dict):
        return False
    url, cmd = h.get("url"), h.get("command")
    if url is not None:
        return h.get("type") in (None, "http") and isinstance(url, str) and bool(URL_DO_CEREBRO.fullmatch(url))
    return h.get("type") in (None, "command") and _roda_o_script(cmd, SCRIPT_HOOK)


def statusline_do_cerebro(sl):
    return isinstance(sl, dict) and _roda_o_script(sl.get("command"), SCRIPT_STATUS)


# ---------------------------------------------------------------------------------------------------------------
# Mescla (funções puras: recebem e devolvem dicionários, sem tocar em arquivo)
# ---------------------------------------------------------------------------------------------------------------
def _tirar_hooks(dados):
    h = dados.get("hooks")
    if not isinstance(h, dict):
        return dados
    for ev in list(h.keys()):
        grupos = h[ev]
        novos = []
        for g in grupos:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                novos.append(g)
                continue
            restantes = [x for x in g["hooks"] if not eh_do_cerebro(x)]
            if len(restantes) == len(g["hooks"]):
                novos.append(g)
            elif restantes:
                g2 = dict(g)
                g2["hooks"] = restantes
                novos.append(g2)
        if novos:
            h[ev] = novos
        elif grupos:                       # a lista só tinha coisa do Cérebro
            del h[ev]
    if not h:
        del dados["hooks"]
    return dados


def mesclar_hooks(dados, entrada, eventos=ganchos_eventos.EVENTOS):
    """Cópia de 'dados' com UMA entrada do Cérebro em cada evento. Já igual: não muda nada. Diferente (porta/modo): troca no lugar."""
    novo = copy.deepcopy(dados)
    h = novo.get("hooks") if isinstance(novo.get("hooks"), dict) else {}
    ja_igual = all(sum(1 for g in h.get(ev, []) if isinstance(g, dict) for x in (g.get("hooks") or []) if eh_do_cerebro(x)) == 1
                   and any(x == entrada for g in h.get(ev, []) if isinstance(g, dict) for x in (g.get("hooks") or [])) for ev in eventos)
    if ja_igual:
        return novo
    novo = _tirar_hooks(novo)
    h = novo.setdefault("hooks", {})
    for ev in eventos:
        h.setdefault(ev, []).append({"hooks": [copy.deepcopy(entrada)]})
    return novo


def entrada_sincrona():
    """Grupo SÍNCRONO só para SessionStart "clear"/"compact": a sessão gestora recebe o resumo do último capítulo logo após a
    limpeza ou a compactação (gancho async só entregaria no turno seguinte). python (não pythonw: precisa de saída), timeout 5 s."""
    return {"matcher": MATCHER_SINCRONO, "hooks": [{"type": "command", "command": f"{comando_hook_sincrono()}", "timeout": 5}]}


def comando_hook_sincrono():
    return f"{_caminho_cmd(_python(False))} {_caminho_cmd(SCRIPT_HOOK)} --sincrono"


def mesclar_sincrono(dados):
    """Acrescenta o grupo síncrono do SessionStart(startup|clear|compact), uma vez só (o tirar_hooks tira junto: é cerebro_hook)."""
    novo = copy.deepcopy(dados)
    grupos = novo.setdefault("hooks", {}).setdefault("SessionStart", [])
    if not any(isinstance(g, dict) and "--sincrono" in str(x.get("command") or "") for g in grupos for x in (g.get("hooks") or [])
               if isinstance(x, dict)):
        grupos.append(entrada_sincrona())
    return novo


def tirar_hooks(dados):
    return _tirar_hooks(copy.deepcopy(dados))


def mesclar_statusline(dados, modo):
    """(novo, anterior). 'anterior' = a statusLine que existia (para desfazer/encadear) ou None.
    instalar: só se não houver statusLine (ou já for a do Cérebro); outra existente -> PrecisaDecidir.
    encadear/substituir: guarda a antiga; a do Cérebro herda padding/refreshInterval dela."""
    if modo not in MODOS_STATUS:
        raise ValueError("modo da statusLine inválido (instalar, encadear ou substituir)")
    novo = copy.deepcopy(dados)
    atual = novo.get("statusLine")
    if statusline_do_cerebro(atual):
        return novo, None
    if atual is not None and modo == "instalar":
        raise PrecisaDecidir("você já tem uma statusLine: escolha 'encadear' (o Cérebro chama a sua e mostra a saída dela) ou 'substituir'")
    base = dict(atual) if isinstance(atual, dict) else {}
    base.update(type="command", command=comando_statusline())
    novo["statusLine"] = base
    return novo, (copy.deepcopy(atual) if atual is not None else None)


def tirar_statusline(dados, anterior=None):
    novo = copy.deepcopy(dados)
    if not statusline_do_cerebro(novo.get("statusLine")):
        return novo
    if anterior is not None:
        novo["statusLine"] = copy.deepcopy(anterior)
    else:
        del novo["statusLine"]
    return novo


# ---------------------------------------------------------------------------------------------------------------
# Operações
# ---------------------------------------------------------------------------------------------------------------
def _planejar_instalacao(hooks, modo, statusline):
    if modo not in MODOS:
        raise ValueError("modo inválido (comando ou http)")
    dados, original, existe = ler_settings()
    if hooks:
        ganchos_eventos.token_hooks()            # o segredo existe nos dois modos (o cerebro_hook.py lê do arquivo)
    token = ganchos_eventos.token_hooks() if (hooks and modo == "http") else ""
    novo, anterior = dados, None
    if hooks:
        novo = mesclar_hooks(novo, entrada_hook(modo, token=token))
        novo = mesclar_sincrono(novo)            # gestora: capítulo depois de /clear e compactação (ver mesclar_sincrono)
    if statusline:
        novo, anterior = mesclar_statusline(novo, statusline)
    texto = _texto_novo(novo, original) if (novo != dados or not existe) else original
    return {"dados": dados, "novo": novo, "original": original, "texto": texto, "existe": existe, "anterior": anterior, "token": token}


def previa(hooks=True, modo="comando", statusline=None):
    """O que mudaria, sem gravar nada. Nunca levanta PrecisaDecidir: devolve 'precisa_decidir' = True."""
    plano, decidir = None, False
    try:
        plano = _planejar_instalacao(hooks, modo, statusline)
    except PrecisaDecidir:
        decidir = True
        plano = _planejar_instalacao(hooks, modo, None)
    muda = plano["novo"] != plano["dados"]
    return {"arquivo": str(caminho_settings()), "existe": plano["existe"], "muda": muda, "precisa_decidir": decidir,
            "diferenca": _diferenca(plano["original"], plano["texto"], [plano["token"]]) if muda else "",
            "statusline_atual": _descrever_statusline(plano["dados"].get("statusLine")), "modo": modo,
            "eventos": list(ganchos_eventos.EVENTOS) if hooks else []}


def _descrever_statusline(sl):
    if sl is None:
        return "nenhuma"
    return "cerebro" if statusline_do_cerebro(sl) else "outra"


def instalar(confirmar=False, hooks=True, modo="comando", statusline=None):
    """Grava as entradas do Cérebro. Sem confirmar=True não faz nada (ValueError)."""
    if not confirmar:
        raise ValueError("nada foi alterado: confirme (botão Ligar na página ou --confirmar na CLI) depois de ver a prévia")
    plano = _planejar_instalacao(hooks, modo, statusline)
    muda = plano["novo"] != plano["dados"]
    copia = None
    if muda:
        if plano["existe"]:
            copia = _copia_de_seguranca(plano["original"])
        _gravar_atomico(plano["texto"], plano["original"])

    def mudar(e):
        if hooks:
            e.update(modo=modo, porta=(config.ler_config().get("porta") if modo == "http" else None), instalado_em=time.time())
        if statusline and plano["dados"].get("statusLine") != plano["novo"].get("statusLine"):   # só quando a statusLine mudou agora
            if plano["anterior"] is not None:
                e["statusline_anterior"] = plano["anterior"]
            else:
                e.pop("statusline_anterior", None)
            e["statusline_modo"] = "encadear" if (statusline == "encadear" and plano["anterior"] is not None) else "proprio"
    armazem.atualizar_json(arquivo_estado(), {}, mudar)
    return {"ok": True, "mudou": muda, "copia": str(copia) if copia else None, "arquivo": str(caminho_settings()),
            "diferenca": _diferenca(plano["original"], plano["texto"], [plano["token"]]) if muda else ""}


def remover(confirmar=False, hooks=True, statusline=True):
    """Tira SÓ as entradas do Cérebro (e devolve a statusLine antiga, se o Cérebro tinha substituído/encadeado uma)."""
    if not confirmar:
        raise ValueError("nada foi alterado: confirme (botão Desligar na página ou --confirmar na CLI)")
    dados, original, existe = ler_settings()
    est = ler_estado()
    novo = dados
    if hooks:
        novo = tirar_hooks(novo)
    if statusline:
        novo = tirar_statusline(novo, est.get("statusline_anterior"))
    muda = novo != dados
    copia = None
    if muda:
        copia = _copia_de_seguranca(original)
        _gravar_atomico(_texto_novo(novo, original), original)

    def mudar(e):
        if hooks:
            for k in ("modo", "porta", "instalado_em"):
                e.pop(k, None)
        if statusline and not statusline_do_cerebro(novo.get("statusLine")):
            e.pop("statusline_anterior", None)
            e.pop("statusline_modo", None)
    armazem.atualizar_json(arquivo_estado(), {}, mudar)
    return {"ok": True, "mudou": muda, "copia": str(copia) if copia else None, "arquivo": str(caminho_settings()),
            "diferenca": _diferenca(original, _texto_novo(novo, original), [ganchos_eventos.token_hooks(criar=False)]) if muda else ""}


def estado():
    """O que está no settings.json agora (só leitura), sem mostrar conteúdo de fora do Cérebro."""
    saida = {"arquivo": str(caminho_settings()), "existe": False, "valido": True, "eventos": [], "modo": "", "statusline": "nenhuma",
             "outros_ganchos": 0, "porta_instalada": None, "porta_config": config.ler_config().get("porta"), "precisa_reinstalar": False,
             "statusline_encadeada": False, "erro": ""}
    try:
        dados, _, existe = ler_settings()
    except SettingsInvalido as e:
        saida.update(valido=False, erro=str(e))
        return saida
    saida["existe"] = existe
    modos = set()
    for ev, grupos in (dados.get("hooks") or {}).items():
        for g in grupos:
            for x in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if eh_do_cerebro(x):
                    saida["eventos"].append(ev)
                    modos.add("http" if x.get("type") == "http" else "comando")
                    if x.get("type") == "http":
                        try:
                            saida["porta_instalada"] = int(str(x.get("url")).split(":")[2].split("/")[0])
                        except (IndexError, ValueError):
                            pass
                else:
                    saida["outros_ganchos"] += 1
    saida["modo"] = "/".join(sorted(modos))
    saida["statusline"] = _descrever_statusline(dados.get("statusLine"))
    est = ler_estado()
    saida["statusline_encadeada"] = saida["statusline"] == "cerebro" and est.get("statusline_modo") == "encadear"
    if saida["porta_instalada"] and saida["porta_instalada"] != saida["porta_config"]:
        saida["precisa_reinstalar"] = True
    if saida["eventos"]:
        faltam = [e for e in ganchos_eventos.EVENTOS if e not in saida["eventos"]]
        saida["incompleto"] = faltam
    return saida
