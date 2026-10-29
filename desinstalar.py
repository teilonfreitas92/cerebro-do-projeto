#!/usr/bin/env python
"""Desinstalador do Cérebro do Projeto.

    python desinstalar.py          # explica e pergunta antes de cada coisa
    python desinstalar.py --sim    # tira o atalho e o .venv sem perguntar (a pasta de dados ~/.cerebro SEMPRE pergunta, salvo --apagar-dados)

O que faz:
  1. avisa para fechar o painel e encerra o servidor, se ele estiver no ar;
  2. tira o atalho "Cérebro do Projeto" da área de trabalho (só o atalho que o instalador criou);
  3. apaga o ambiente .venv desta pasta;
  4. PERGUNTA antes de apagar ~/.cerebro (config, decisões, análises, mapas e o token), mostrando o que tem lá.
  + oferece remover as tarefas agendadas do Cérebro no Windows (só as da pasta CerebroDoProjeto do Agendador E que rodam o
    cerebro_cli.py DESTA pasta: as de outra cópia do Cérebro ficam);
  + oferece tirar os ganchos e a statusLine do Cérebro do settings.json do Claude Code (devolvendo a statusLine que você tinha
    antes, com cópia de segurança). Enquanto o settings.json ainda chamar o Cérebro, ~/.cerebro NÃO é apagada: é lá que fica
    a statusLine antiga;
  + as cópias de segurança de ~/.cerebro/copias (versões antes de restaurar, memória antes de editar, settings.json original)
    têm pergunta própria (padrão: guardar): sem um "s", são copiadas para a pasta de backup antes de a casa ser apagada;
  + a pasta de BACKUP (~/CerebroBackup) tem pergunta própria e, sem um "s" explícito, fica (nem --sim nem
    --apagar-dados apagam o backup). Mesmo com "s", só saem os arquivos do backup (snapshots, estado); a pasta copias/ de lá
    tem outra pergunta, e o que não é do Cérebro fica.
Não apaga a pasta do Cérebro em si (para tirar de vez, apague a pasta depois) e nunca apaga nada em ~/.claude nem nos seus
projetos (o settings.json só é editado, com o seu sim, para tirar as entradas do Cérebro).
Pode rodar de novo: o que já foi tirado é só ignorado. Toda remoção passa pelas travas de config.remover_em / remover_casa.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from cerebro import agendador, backup, config, ganchos_claude  # noqa: E402

MARCAS_SETTINGS = ("cerebro_hook", "cerebro_statusline", "/api/hooks/")      # para um settings.json que não é JSON válido

NOME_ATALHO = "Cérebro do Projeto.lnk"
ARQ_REGISTRO = ".instalacao.json"


def _tamanho(pasta):
    total, n = 0, 0
    for p in Path(pasta).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
                n += 1
        except OSError:
            continue
    return n, total


def descrever_casa():
    """Lista curta do que existe em ~/.cerebro, para a pessoa decidir com informação."""
    casa = Path(config.CASA)
    if not casa.is_dir():
        return []
    linhas = []
    for f in sorted(casa.iterdir()):
        if f.is_dir():
            n, t = _tamanho(f)
            linhas.append(f"{f.name}\\  ({n} arquivos, {t // 1024} KB)")
        else:
            linhas.append(f"{f.name}  ({f.stat().st_size // 1024 or 1} KB)")
    return linhas


def entradas_no_settings():
    """O que do Cérebro está no settings.json do Claude Code (só lê; não cria ~/.cerebro). Lista de descrições curtas."""
    try:
        dados, _texto, _existe = ganchos_claude.ler_settings()
    except ganchos_claude.SettingsInvalido:
        try:
            texto = ganchos_claude.caminho_settings().read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""
        return ["algo do Cérebro (o arquivo não é um JSON válido)"] if any(m in texto for m in MARCAS_SETTINGS) else []
    achadas = []
    hooks = dados.get("hooks") if isinstance(dados.get("hooks"), dict) else {}
    for evento, grupos in hooks.items():
        for g in grupos if isinstance(grupos, list) else []:
            for x in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if ganchos_claude.eh_do_cerebro(x) and f"gancho {evento}" not in achadas:
                    achadas.append(f"gancho {evento}")
    if ganchos_claude.statusline_do_cerebro(dados.get("statusLine")):
        achadas.append("statusLine")
    return achadas


def tirar_do_settings(perguntar, saida):
    """Oferece tirar os ganchos e a statusLine do Cérebro do settings.json (a statusLine antiga volta). Devolve o que AINDA
    está lá depois (lista vazia = nada do Cérebro no settings.json)."""
    achadas = entradas_no_settings()
    arq = ganchos_claude.caminho_settings()
    if not achadas:
        saida("      O settings.json do Claude Code não chama o Cérebro: nada a tirar.")
        return []
    saida(f"      O {arq} ainda chama o Cérebro: {', '.join(achadas)}.")
    saida("      Sem o Cérebro, esses ganchos e a statusLine apontariam para arquivos que não existem mais.")
    if perguntar("Tirar só as entradas do Cérebro (a sua statusLine de antes volta; cópia do arquivo antes)?"):
        try:
            r = ganchos_claude.remover(True, True, True)
            saida("      Entradas do Cérebro tiradas do settings.json." + (f" Cópia de antes: {r['copia']}" if r.get("copia") else ""))
        except (OSError, ValueError) as e:
            saida(f"      Não mexi no settings.json: {e}")
    return entradas_no_settings()


def guardar_copias(perguntar, saida):
    """Antes de apagar ~/.cerebro: as cópias de segurança (copias/) e a statusLine antiga (ganchos.json) vão para a pasta de
    backup, salvo "s" explícito para apagá-las. Devolve True se a casa pode ser apagada."""
    casa = Path(config.CASA)
    if not any((casa / n).exists() for n in backup.GUARDAR_DA_CASA):
        return True
    saida("      Em copias/ ficam as versões guardadas antes de restaurar um backup ou editar a memória, os arquivos tirados dos")
    saida("      projetos e o settings.json original do Claude Code (e em ganchos.json, a statusLine que você tinha antes).")
    if perguntar("Apagar também essas cópias? (o padrão é guardá-las na pasta de backup)", padrao_sim=False, ignora_sim=True):
        saida("      As cópias vão junto com a pasta de dados.")
        return True
    try:
        destino = backup.guardar_copias_da_casa()
    except (OSError, backup.BackupErro) as e:
        saida(f"      Não consegui guardar as cópias ({e}): NÃO apaguei a pasta de dados.")
        return False
    if destino:
        saida(f"      Cópias guardadas em {destino}")
    return True


def encerrar_servidor(saida=print):
    arq = Path(config.CASA) / "servidor.json"
    try:
        porta = json.loads(arq.read_text(encoding="utf-8")).get("porta")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(porta, int):
        return False
    try:
        token = (Path(config.CASA) / "token").read_text(encoding="ascii").strip()
        # abre a sessão (cookie) e pede para encerrar, como a própria página faz
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(f"http://{config.HOST}:{porta}/?t={token}", timeout=3).read()
        req = urllib.request.Request(f"http://{config.HOST}:{porta}/api/encerrar", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json", "Origin": f"http://{config.HOST}:{porta}"})
        op.open(req, timeout=3).read()
        saida("      O servidor do Cérebro foi encerrado.")
        return True
    except Exception:
        return False


def main(argv=None, entrada=input, saida=print, raiz=RAIZ, area=None):
    ap = argparse.ArgumentParser(description="Desinstala o Cérebro do Projeto")
    ap.add_argument("--sim", action="store_true", help="tira o atalho e o .venv sem perguntar")
    ap.add_argument("--apagar-dados", action="store_true", help="apaga também ~/.cerebro sem perguntar (CUIDADO: perde decisões e histórico)")
    ap.add_argument("--manter-dados", action="store_true", help="não apaga ~/.cerebro e não pergunta")
    ap.add_argument("--sem-encerrar", action="store_true", help="não tenta encerrar o servidor (para testes)")
    a = ap.parse_args(argv)
    raiz = Path(raiz)

    def perguntar(texto, padrao_sim=True, ignora_sim=False):
        if a.sim and not ignora_sim:
            saida(f"      {texto} -> sim (--sim)")
            return True
        try:
            r = entrada(f"      {texto} {'[S/n]' if padrao_sim else '[s/N]'} ").strip().lower()
        except EOFError:
            r = ""
        return padrao_sim if not r else r[0] in ("s", "y")

    saida("Desinstalador do Cérebro do Projeto")
    try:
        registro = json.loads((raiz / ARQ_REGISTRO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registro = {}

    saida("\n[1/4] Fechando o servidor")
    saida("      Feche a página do Cérebro no navegador. Se o servidor estiver no ar, eu peço para ele encerrar.")
    if not a.sem_encerrar and not encerrar_servidor(saida):
        saida("      O servidor não estava no ar (ou já fechou).")

    saida("\n[2/4] Atalho da área de trabalho")
    atalho = registro.get("atalho")
    if not atalho and area is not None:
        atalho = str(Path(area) / NOME_ATALHO)
    if atalho and Path(atalho).name == NOME_ATALHO and Path(atalho).exists():
        if perguntar(f"Tirar o atalho {atalho}?"):
            try:
                config.remover_em(Path(atalho).parent, atalho, somente_nomes=(NOME_ATALHO,))
                saida("      Atalho removido.")
            except (OSError, config.RemocaoRecusada) as e:
                saida(f"      Não removi o atalho: {e}")
    else:
        saida("      Nenhum atalho do Cérebro registrado: nada a tirar.")

    saida("\n[3/4] Ambiente .venv")
    venv = raiz / ".venv"
    if venv.is_dir():
        if perguntar(f"Apagar o ambiente {venv} (você reinstala com python instalar.py)?"):
            try:
                config.remover_em(raiz, venv, pasta=True, somente_nomes=(".venv",))
                saida("      .venv removido.")
            except (OSError, config.RemocaoRecusada) as e:
                saida(f"      Não removi o .venv: {e}")
    else:
        saida("      Não há .venv nesta pasta.")

    saida("\n[+] Tarefas agendadas do Cérebro no Windows")
    try:
        tarefas = agendador.listar_do_prefixo()
    except agendador.AgendadorErro as e:
        tarefas = []
        saida(f"      Não consegui consultar o Agendador de Tarefas: {e}")
    if not tarefas:
        saida("      Nenhuma tarefa do Cérebro no Agendador: nada a tirar.")
    else:
        saida("      Tarefas na pasta CerebroDoProjeto do Agendador: " + ", ".join(tarefas))
        if perguntar("Remover as tarefas desta instalação (as rotinas param de rodar sozinhas)?"):
            try:
                saida("      Removidas: " + (", ".join(agendador.remover_todas()) or "nenhuma"))
                outras = agendador.outras_copias()
                if outras:
                    saida("      Ficaram (rodam outra cópia do Cérebro, não esta pasta): " + ", ".join(outras))
            except agendador.AgendadorErro as e:
                saida(f"      Não removi as tarefas: {e}")

    saida("\n[+] Manual do gestor nos projetos (bloco no CLAUDE.local.md)")
    from cerebro import manual_projeto                  # tira só o bloco do Cérebro, com cópia antes (precisa do ~/.cerebro: vem antes)
    manual_projeto.desinstalar_passo(lambda t: perguntar(t, ignora_sim=True), saida)

    saida("\n[+] Ganchos e statusLine do Cérebro no Claude Code")
    pendentes = tirar_do_settings(perguntar, saida)

    saida("\n[4/4] Dados do Cérebro (~/.cerebro)")
    itens = descrever_casa()
    if not itens:
        saida("      Não há pasta de dados.")
    else:
        saida(f"      A pasta {config.CASA} guarda a SUA configuração, decisões, análises, mapas e o token de acesso:")
        for linha in itens:
            saida(f"        - {linha}")
        if a.manter_dados:
            saida("      Mantida (--manter-dados).")
        elif a.apagar_dados or perguntar("Apagar tudo isso? (não dá para desfazer)", padrao_sim=False, ignora_sim=True):
            if pendentes:
                saida("      NÃO apaguei os dados: o settings.json do Claude Code ainda chama o Cérebro e a sua statusLine de antes")
                saida("      está guardada aqui. Tire as entradas (rode de novo e responda sim) e depois apague.")
            elif guardar_copias(perguntar, saida):
                try:
                    config.remover_casa()
                    saida("      Dados apagados.")
                except (OSError, config.RemocaoRecusada) as e:
                    saida(f"      Não apaguei os dados: {e}")
        else:
            saida("      Dados mantidos: se você reinstalar, tudo continua como estava.")

    saida("\n[+] Cópias de segurança (backup)")
    try:
        pasta_bk = backup.pasta_backup()
        snaps = backup.listar(pasta_bk)[0] if pasta_bk.is_dir() else []
    except backup.BackupErro as e:
        pasta_bk, snaps = None, []
        saida(f"      {e}")
    if pasta_bk is None or not pasta_bk.is_dir():
        saida("      Não há pasta de backup.")
    else:
        saida(f"      A pasta {pasta_bk} guarda {len(snaps)} backup(s) das suas conversas e memória do Claude Code.")
        if perguntar("Apagar também os backups? (não dá para desfazer; o padrão é guardar)", padrao_sim=False, ignora_sim=True):
            copias = (pasta_bk / "copias").is_dir() and perguntar(
                f"Apagar também as cópias guardadas em {pasta_bk / 'copias'} (versões antes de restaurar, cópias da desinstalação)?",
                padrao_sim=False, ignora_sim=True)
            try:
                n = backup.apagar_tudo(copias=copias)
                saida(f"      Backups apagados ({n} item(ns)).")
                sobra = backup.sobras(pasta_bk)
                if sobra:
                    saida(f"      Ficaram na pasta (não são snapshots do backup, ou você quis guardar): {', '.join(sobra[:10])}")
            except (OSError, config.RemocaoRecusada, backup.BackupErro) as e:
                saida(f"      Não apaguei os backups: {e}")
        else:
            saida("      Backups mantidos.")
    saida("\nPronto. Para tirar o Cérebro de vez, apague a pasta dele depois de fechar este terminal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
