"""Subcomandos da CLI que ESCREVEM num projeto ou instalam programas. Sem --confirmar só mostram a prévia (nada muda).

    python cerebro_cli.py instalar-ferramenta MeuProjeto gitleaks                     # prévia: comando, de onde vem, tamanho
    python cerebro_cli.py instalar-ferramenta MeuProjeto gitleaks --confirmar --aceitar-termos
    python cerebro_cli.py encaixe MeuProjeto --previa                                 # todas as ações do plano, com a diferença
    python cerebro_cli.py encaixe MeuProjeto --aplicar instrucoes --confirmar
    python cerebro_cli.py encaixe MeuProjeto --desfazer --confirmar                   # volta a última aplicação
    python cerebro_cli.py encaixe MeuProjeto --desfazer --confirmar --mesmo-com-mudancas   # idem, se você mexeu depois (mostra a diferença)
    python cerebro_cli.py agentes-copiar MeuProjeto [--gravar-ao-lado] --confirmar
"""
from . import config, encaixe, instalador

OK, ERRO = 0, 2


def _mostrar_previa(pv, com_diff=True):
    print(f"== {pv['titulo']} ({pv['acao']})")
    if not pv.get("aplicavel"):
        print("   nada a aplicar" + (f": {pv['motivo']}" if pv.get("motivo") else ""))
    for a in pv.get("arquivos", []):
        print(f"   [{a['tipo']}] {a['rel']} — {a['nota']}")
        if com_diff and a.get("diff"):
            for linha in a["diff"].splitlines():
                print("      " + linha)
    if pv.get("resumo"):
        print("   " + pv["resumo"])


def cmd_instalar(a, achar_projeto):
    p = achar_projeto(a.projeto)
    pv = instalador.previa(a.ferramenta, a.aceitar_termos)
    print(f"Ferramenta: {pv['nome']}  (via {pv['via']}, pacote {pv['pacote']})")
    print(f"De onde vem: {pv['de_onde']}")
    print(f"Onde instala: {pv['onde']}")
    print(f"Tamanho: {pv['tamanho']} · tempo: {pv['tempo']} (limite {pv['limite'] // 60} min)")
    if pv["aviso"]:
        print("Aviso: " + pv["aviso"])
    if not pv["disponivel"]:
        print("Não dá para instalar daqui: " + pv.get("motivo", ""))
        return ERRO
    print("Comando: " + pv["comando"])
    if not a.confirmar:
        print("\nNada foi instalado. Para instalar, repita com --confirmar" + (" --aceitar-termos" if pv["precisa_termos"] else "") + ".")
        return OK
    print("\nInstalando (pode demorar)...")
    reg = instalador.instalar(p["slug"], p["caminho"], a.ferramenta, True, a.aceitar_termos, esperar=True)
    print(instalador.saida(p["slug"], reg))
    print(f"Resultado: {reg['resultado']} · {reg['resumo']}")
    return OK if reg["resultado"] == "ok" else ERRO


def cmd_encaixe(a, achar_projeto):
    p = achar_projeto(a.projeto)
    cfg = config.ler_config()
    if a.desfazer:
        if not a.confirmar:
            print("Desfazer volta a última aplicação (arquivo criado vai para a pasta de cópias). Repita com --confirmar.")
            return OK
        pv = encaixe.previa_desfazer(p, cfg)
        for m in pv["mexidos"]:
            print(f"{m['rel']}: {m['motivo']}. Diferença (agora → depois de desfazer):\n{m['diff'] or '(sem diferença de texto)'}\n")
        if pv["mexidos"] and not a.mesmo_com_mudancas:
            print("Nada foi desfeito: o(s) arquivo(s) acima mudaram depois da aplicação. Se quer desfazer mesmo assim (a versão de "
                  "agora vai para a pasta de cópias), repita com --confirmar --mesmo-com-mudancas.")
            return ERRO
        r = encaixe.desfazer(p, True, cfg, aceitar_mexidos=pv["assinatura_mexidos"])
        print(f"Desfeito: {r['titulo']}")
        for f in r["feito"]:
            print("  " + f)
        print(f"Cópias em: {r['pasta_copia']}")
        return OK
    if a.aplicar:
        opcoes = {"conflito": "cerebro_md" if a.gravar_ao_lado else "pular"}
        if a.modo:
            opcoes["modo"] = a.modo
        pv = encaixe.previa(p, a.aplicar, opcoes, cfg)
        _mostrar_previa(pv)
        if not a.confirmar:
            print("\nNada foi aplicado. Para aplicar, repita com --confirmar.")
            return OK
        r = encaixe.aplicar(p, a.aplicar, True, opcoes, pv["assinatura"], cfg)
        if r["nada_a_fazer"]:
            print("\nNada a fazer: tudo já estava aplicado.")
        else:
            print(f"\nAplicado. Cópias de segurança em: {r['copia']}  (desfazer: encaixe {a.projeto} --desfazer --confirmar)")
        return OK
    d = encaixe.previa_tudo(p, cfg)
    if d["bloqueado"]:
        print("O Cérebro não escreve neste projeto: " + d["bloqueado"])
        return ERRO
    for pv in d["acoes"].values():
        _mostrar_previa(pv, com_diff=a.previa)
        print()
    print("Nada foi aplicado. Aplicar um item: encaixe <projeto> --aplicar <ação> --confirmar")
    return OK


def cmd_agentes_copiar(a, achar_projeto):
    a.aplicar, a.desfazer, a.modo = "agentes", False, None
    return cmd_encaixe(a, achar_projeto)


def registrar(sub, achar_projeto):
    s = sub.add_parser("instalar-ferramenta", help="instala uma ferramenta da lista fechada (sem --confirmar: só a prévia)")
    s.add_argument("projeto")
    s.add_argument("ferramenta", help=", ".join(instalador.RECEITAS))
    s.add_argument("--confirmar", action="store_true")
    s.add_argument("--aceitar-termos", action="store_true", help="winget: aceitar os termos do repositório e do pacote")
    s.set_defaults(f=lambda a: cmd_instalar(a, achar_projeto))
    s = sub.add_parser("encaixe", help="plano de encaixe: prévia, aplicar um item, desfazer a última aplicação")
    s.add_argument("projeto")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--previa", action="store_true", help="mostra a diferença de cada ação (padrão: só o resumo)")
    g.add_argument("--aplicar", choices=list(encaixe.ACOES))
    g.add_argument("--desfazer", action="store_true")
    s.add_argument("--confirmar", action="store_true")
    s.add_argument("--mesmo-com-mudancas", action="store_true",
                   help="desfazer: segue mesmo se o arquivo mudou depois da aplicação (mostra a diferença; a versão de agora vai para as cópias)")
    s.add_argument("--gravar-ao-lado", action="store_true", help="agentes: se já existir diferente, grava <nome>.cerebro.md ao lado")
    s.add_argument("--modo", choices=["config", "encadear", "novo"], help="segredos: como ligar o gitleaks")
    s.set_defaults(f=lambda a: cmd_encaixe(a, achar_projeto))
    s = sub.add_parser("agentes-copiar", help="copia os agentes da prévia para .claude/agents do projeto (sem --confirmar: só a prévia)")
    s.add_argument("projeto")
    s.add_argument("--confirmar", action="store_true")
    s.add_argument("--gravar-ao-lado", action="store_true")
    s.set_defaults(f=lambda a: cmd_agentes_copiar(a, achar_projeto), previa=True)
