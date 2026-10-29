"""Subcomandos da linha de comando para backup, rotinas e agendamento no Windows (cerebro_cli.py chama adicionar_subcomandos).

    python cerebro_cli.py backup                     # situação: pasta, último backup, snapshots (o mesmo que --listar)
    python cerebro_cli.py backup --agora             # faz o backup de hoje
    python cerebro_cli.py backup --conferir 2026-10-29
    python cerebro_cli.py backup --restaurar 2026-10-29 [--projeto X] [--so-memoria]            # só MOSTRA o que mudaria
    python cerebro_cli.py backup --restaurar 2026-10-29 [--projeto X] [--so-memoria] [--trocar-diferentes] --confirmar
    python cerebro_cli.py backup --liberar           # o backup encolheu de propósito: devolve os protegidos à rotação
    python cerebro_cli.py rotina backup|analise|novidades|mapa       # o que a tarefa agendada roda (log em ~/.cerebro/rotinas)
    python cerebro_cli.py agendar backup --ligar [--hora 12:30]      # cria a tarefa CerebroDoProjeto\\backup no Windows
    python cerebro_cli.py agendar analise --ligar --hora 13:00 --dias 7
    python cerebro_cli.py agendar mapa --ligar --horas 6
    python cerebro_cli.py agendar backup --desligar | --estado
"""
import time

from . import agendador, backup, rotinas_windows

SAIDA_OK, SAIDA_ERRO = 0, 2


def _mb(n):
    return f"{(n or 0) / 1e6:.1f} MB"


def _data(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "-"


def _listar():
    r = backup.resumo()
    if r.get("erro"):
        print(f"Erro: {r['erro']}")
        return SAIDA_ERRO
    print(f"Pasta do backup: {r['pasta']}  (guarda {r['manter_dias']} dias; total {_mb(r['bytes_total'])})")
    u = r.get("ultimo")
    if u:
        print(f"Último: {_data(u.get('em'))} · " + (f"ok, {u.get('arquivos')} arquivos, {_mb(u.get('bytes_zip'))} no zip"
                                                   if u.get("ok") else f"FALHOU: {u.get('erro')}"))
    else:
        print("Nenhum backup feito ainda. Faça o primeiro: python cerebro_cli.py backup --agora")
    for s in r["snapshots"]:
        marca = "  (protegido: o backup seguinte encolheu)" if s["nome"] in r["protegidos"] else ""
        print(f"  {s['nome']:<24} {_mb(s['bytes_zip']):>10} no zip · {s['arquivos']} arquivos · {len(s['projetos'])} projeto(s)"
              + (f" · {s['falhas']} não lido(s)" if s["falhas"] else "") + marca)
    for s in r["incompletos"]:
        print(f"  {s['nome']:<24} NÃO CONTA: {s['motivo']}")
    return SAIDA_OK


def _mostrar_plano(pl, limite=40):
    t = pl["totais"]
    print(f"Snapshot {pl['snapshot']} ({_data(pl['criado_em'])}): faltam {t['faltam']}, diferentes {t['diferentes']}, "
          f"cresceram depois do backup {t['cresceram']} (ficam como estão), iguais {t['iguais']}")
    for g in pl["grupos"]:
        if not (g["faltam"] or g["diferentes"] or g["cresceram"]):
            continue
        print(f"\n  {g['grupo']}: faltam {len(g['faltam'])} · diferentes {len(g['diferentes'])} · cresceram {len(g['cresceram'])} · iguais {g['iguais']}")
        for rotulo, chave in (("falta", "faltam"), ("diferente", "diferentes")):
            for it in g[chave][:limite]:
                print(f"    [{rotulo}] {it['arq']}")
            if len(g[chave]) > limite:
                print(f"    ... e mais {len(g[chave]) - limite}")


def cmd_backup(a):
    if a.agora:
        r = backup.fazer_backup()
        print(f"Backup feito: {r['nome']} · {r['arquivos']} arquivos ({_mb(r['bytes'])}) · {_mb(r['bytes_zip'])} no zip · {r['duracao']} s")
        for f in r["falhas"][:20]:
            print(f"  não lido (aberto ou sem permissão): {f['arq']} ({f['erro']})")
        if r["encolheu"]:
            print("  ATENÇÃO: bem menor que o anterior. O anterior ficou protegido (não sai na rotação). Confira e use --liberar.")
        if r["removidos"]:
            print("  Rotação removeu: " + ", ".join(r["removidos"]))
        return SAIDA_OK
    if a.liberar:
        print("Liberados: " + (", ".join(backup.liberar_protegidos()) or "nenhum"))
        return SAIDA_OK
    if a.conferir:
        nome = backup.achar_snapshot(a.conferir)
        r = backup.conferir(nome)
        print(f"{nome}: " + (f"confere ({r['conferidos']} arquivos)" if r["ok"] else "NÃO confere:\n  " + "\n  ".join(r["problemas"])))
        return SAIDA_OK if r["ok"] else SAIDA_ERRO
    if a.restaurar:
        nome = backup.achar_snapshot(a.restaurar)
        pl = backup.plano(nome, a.projeto, a.so_memoria)
        _mostrar_plano(pl)
        if not a.confirmar:
            print("\nNada foi escrito. Para restaurar (copia o que falta; nada é apagado) acrescente --confirmar"
                  + ("" if a.trocar_diferentes else "; para trocar também os diferentes (a versão de hoje é guardada antes), --trocar-diferentes") + ".")
            return SAIDA_OK
        r = backup.restaurar(nome, True, (), a.trocar_diferentes, a.projeto, a.so_memoria)
        print(f"\nRestaurado: {len(r['copiados'])} copiado(s), {len(r['trocados'])} trocado(s), {len(r['pulados'])} deixado(s) como estão.")
        if r["copias"]:
            print(f"A versão de hoje dos trocados ficou em: {r['copias']}")
        for e in r["erros"][:20]:
            print(f"  erro: {e}")
        return SAIDA_ERRO if r["erros"] else SAIDA_OK
    return _listar()


def cmd_rotina(a):
    r = rotinas_windows.executar(a.nome)
    print(("ok: " if r["ok"] else "ERRO: ") + r["texto"])
    return SAIDA_OK if r["ok"] else SAIDA_ERRO


def _mostrar_estado(rotina):
    e = agendador.estado(rotina)
    if not e["disponivel"]:
        print("O agendamento só existe no Windows.")
        return
    u = rotinas_windows.ultimo(rotina)
    print(f"{e['tarefa']}: " + ("LIGADA" if e["ligada"] else "desligada")
          + (f" · próxima: {e['proxima']} · última: {e['ultima']} (resultado {e['resultado']})" if e["ligada"] else "")
          + (f" · erro: {e['erro']}" if e.get("erro") else ""))
    print(f"Parâmetros: {agendador.parametros(rotina)}")
    if u:
        print(f"Última execução (log do Cérebro): {_data(u['em'])} · " + ("ok" if u["ok"] else "ERRO") + f" · {u['texto'][:200]}")


def cmd_agendar(a):
    if a.ligar:
        p = agendador.parametros(a.rotina)
        for k in ("hora", "dias", "horas"):
            v = getattr(a, k)
            if v is not None:
                p[k] = v
        agendador.ligar(a.rotina, p)
        print(f"Tarefa {agendador.nome_tarefa(a.rotina)} criada no Agendador de Tarefas (usuário atual, sem senha, sem administrador).")
    elif a.desligar:
        print("Tarefa removida." if agendador.desligar(a.rotina) else "A tarefa não existia: nada a fazer.")
    _mostrar_estado(a.rotina)
    return SAIDA_OK


def adicionar_subcomandos(sub):
    s = sub.add_parser("backup", help="cópia de segurança das conversas e da memória (fora de .claude e .cerebro)")
    s.add_argument("--agora", action="store_true", help="faz o backup de hoje")
    s.add_argument("--listar", action="store_true", help="mostra os snapshots (padrão)")
    s.add_argument("--conferir", metavar="DATA", help="relê o snapshot e compara com o manifesto")
    s.add_argument("--restaurar", metavar="DATA", help="mostra o que mudaria; com --confirmar, restaura sem apagar nada")
    s.add_argument("--projeto", help="restaura só este projeto (slug ou trecho do nome da pasta)")
    s.add_argument("--so-memoria", action="store_true", help="restaura só a memória (pastas memory)")
    s.add_argument("--trocar-diferentes", action="store_true", help="troca também os arquivos diferentes (a versão de hoje é guardada antes)")
    s.add_argument("--confirmar", action="store_true", help="sem isto a restauração só mostra o que faria")
    s.add_argument("--liberar", action="store_true", help="devolve à rotação os snapshots protegidos depois de um backup que encolheu")
    s.set_defaults(f=cmd_backup)
    s = sub.add_parser("rotina", help="roda uma rotina agora (é o que a tarefa agendada chama)")
    s.add_argument("nome", choices=agendador.ROTINAS)
    s.set_defaults(f=cmd_rotina)
    s = sub.add_parser("agendar", help="liga/desliga a rotina no Agendador de Tarefas do Windows")
    s.add_argument("rotina", choices=agendador.ROTINAS)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--ligar", action="store_true")
    g.add_argument("--desligar", action="store_true")
    g.add_argument("--estado", action="store_true")
    s.add_argument("--hora", help="HH:MM")
    s.add_argument("--dias", type=int, help="intervalo em dias (analise, novidades)")
    s.add_argument("--horas", type=int, help="intervalo em horas (mapa)")
    s.set_defaults(f=cmd_agendar)


ERROS = (backup.BackupErro, agendador.AgendadorErro)
