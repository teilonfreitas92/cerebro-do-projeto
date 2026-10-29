"""Subcomandos da CLI para a sessão gestora (mesma sessão + limpeza) e o manual do gestor (registrados por cerebro_cli.py).

    python cerebro_cli.py gestora estado MeuProjeto               # corrente de transcrições, vigia, capítulos
    python cerebro_cli.py gestora limpar MeuProjeto               # capítulo conferido + limpeza pendente; "OK" = pode chamar clear_session
    python cerebro_cli.py gestora limpeza MeuProjeto              # transcrições antigas que podem sair (com a prova do backup)
    python cerebro_cli.py gestora limpeza MeuProjeto --autorizar --confirmar    # o "sim" do dono: liga e roda agora
    python cerebro_cli.py gestora limpeza MeuProjeto --desautorizar
    python cerebro_cli.py manual --gerar                          # refaz o ~/.cerebro/GESTOR.md
    python cerebro_cli.py manual MeuProjeto --previa              # Ligar/Desligar no CLAUDE.local.md: prévia
    python cerebro_cli.py manual MeuProjeto --instalar --confirmar | --remover --confirmar
Alternativa (não é o padrão): troca por sessão nova do app, `gestora preparar` e `gestora trocar --marca <id>`.
"""
import time

from . import config, gestora_troca, manual_gestor, manual_projeto

_achar = None


def _data(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "-"


def cmd_gestora(a):
    p = _achar(a.projeto)
    slug = p["slug"]
    cfg = config.ler_config()
    if a.acao == "preparar":
        r = gestora_troca.preparar(slug, p, cfg)
        print(f"Marca: {r['marca']}   Bastão: {r['arquivo']}")
        print(f"Título da sessão NOVA:   {r['titulo_nova']}")
        print(f"Título da sessão ANTIGA: {r['titulo_antiga']}")
        print("\n----- texto para o start_session (prompt) -----\n")
        print(r["texto"])
        print("\n----- fim do texto -----")
        print(f"Depois do start_session: python cerebro_cli.py gestora trocar {a.projeto} --marca {r['marca']} "
              "--sessao-app <local_nova> --sessao-app-antiga <local_antiga>")
        return 0
    if a.acao == "trocar":
        if not a.marca:
            raise ValueError("informe --marca (a do `gestora preparar`)")
        r = gestora_troca.trocar(slug, a.marca, a.sessao_app or "", a.sessao_app_antiga or "", a.por, cfg)
        if r.get("feito"):
            print(f"Troca registrada: a gestora agora é a conversa {r['conversa']}" + (" (já estava feita)" if r.get("ja_feito") else "") + ".")
        else:
            print("A conversa nova ainda não apareceu nos arquivos do Claude Code. Fica pendente: o Cérebro completa sozinho "
                  "assim que ela aparecer (ou rode este comando de novo daqui a pouco).")
        return 0
    if a.acao == "limpar":
        try:
            r = gestora_troca.limpar(slug, cfg)
        except ValueError as e:
            print(f"NÃO limpe: {e}")
            return 2
        print(f"OK — capítulo gravado e conferido ({r['tamanho']} caracteres): {r['capitulo']}")
        print('Pode chamar clear_session com session_id "self". A conversa recomeça com o resumo deste capítulo.')
        return 0
    if a.acao == "limpeza":
        from . import retencao_gestora
        if a.desautorizar:
            retencao_gestora.autorizar(slug, ligar=False)
            print("Limpeza automática desligada neste projeto.")
            return 0
        if a.autorizar:
            if not a.confirmar:
                raise ValueError("nada foi alterado: repita com --autorizar --confirmar (o seu sim)")
            retencao_gestora.autorizar(slug, confirmar=True)
            print("Autorizado. Rodando agora:")
        cand = retencao_gestora.candidatos(slug, cfg)
        if not cand:
            print(f"Nenhuma transcrição antiga da gestora fora de uso há mais de {gestora_troca.parametros(cfg)['dias_limpeza']} dias.")
            return 0
        cfg = config.ler_config()
        for c in cand:
            try:
                if a.autorizar:
                    r = retencao_gestora.apagar(slug, c["conversa"], "dono", cfg)
                    print(f"- {c['conversa']}: apagada ({r['arquivos']} arquivo(s); guardada no backup {r['snapshot']})")
                else:
                    snap = retencao_gestora.conferir(slug, c["conversa"], cfg)["snapshot"]
                    print(f"- {c['conversa']} · fora de uso desde {_data(c['fim'])} · pode sair (backup {snap} conferido)")
            except retencao_gestora.ApagarRecusado as e:
                print(f"- {c['conversa']} · fica: {e}")
        if not a.autorizar:
            print("\n" + ("Autorizado: a rotina do servidor apaga uma vez por dia." if retencao_gestora.autorizado(slug, cfg)
                          else f"Para autorizar (uma vez): python cerebro_cli.py gestora limpeza {a.projeto} --autorizar --confirmar"))
        return 0
    from . import capitulos
    r = gestora_troca.resumo_para_tela(slug, cfg)
    v = r["vigia"]
    print(f"Gestora: {v['conversa'] or '(não escolhida)'} · ≈ {v['contexto'] // 1000} mil tokens ({v['pct']}%) · {v['mb']} MB"
          + (" · HORA DE LIMPAR (gestora limpar + clear_session)" if v["longa"] else ""))
    for e in r["elos"]:
        print(f"  [{e.get('estado')}] {e.get('titulo') or '(sem título)'} · {e['conversa']}" + (f" · {e['sessao_app']}" if e.get("sessao_app") else "")
              + f" · {_data(e.get('inicio'))} → {_data(e.get('fim')) if e.get('fim') else 'agora'}")
    for c in capitulos.listar(slug, 5):
        print(f"  capítulo {_data(c['em'])}: {c['resumo'][:100]}")
    return 0


def cmd_manual(a):
    if a.gerar:
        r = manual_gestor.gerar(forcar=True)
        print(f"GESTOR.md {r['versao']} (≈ {r['tokens']} tokens) em {r['caminho']}")
        return 0
    if not a.projeto:
        raise ValueError("informe o projeto (ou --gerar)")
    p = _achar(a.projeto)
    acao = "remover" if a.remover else "instalar"
    if a.instalar or a.remover:
        if not a.confirmar:
            raise ValueError("nada foi alterado: veja antes com --previa e repita com --confirmar")
        r = manual_projeto.aplicar(p, acao, confirmar=True)
        for f in r["feito"]:
            print(f"{f['rel']}: {f['tipo']} — {f['nota']}")
        print("Nada a fazer." if r["nada_a_fazer"] else f"Feito. Cópia de segurança em: {r['copia']}")
        return 0
    pv = manual_projeto.previa(p, "remover" if manual_projeto.instalado(p) else "instalar")
    print(f"{pv['titulo']} — {'ligado' if pv['instalado'] else 'desligado'} hoje")
    for f in pv["arquivos"]:
        print(f"\n{f['rel']}: {f['tipo']} — {f['nota']}")
        if f["diff"]:
            print(f["diff"])
    print("\nSó a prévia. Para gravar: --" + pv["acao"] + " --confirmar")
    return 0


def registrar(sub, achar_projeto):
    global _achar
    _achar = achar_projeto
    s = sub.add_parser("gestora", help="sessão gestora: estado, limpar (antes do clear_session), limpeza (transcrições antigas)")
    s.add_argument("acao", choices=("estado", "limpar", "limpeza", "preparar", "trocar"))
    s.add_argument("projeto")
    s.add_argument("--autorizar", action="store_true", help="limpeza: o sim do dono para apagar as transcrições antigas (com --confirmar)")
    s.add_argument("--desautorizar", action="store_true", help="limpeza: desliga a remoção automática")
    s.add_argument("--confirmar", action="store_true")
    s.add_argument("--marca", help="trocar: a marca do `gestora preparar`")
    s.add_argument("--sessao-app", help="trocar: id da sessão NOVA no app (local_...)")
    s.add_argument("--sessao-app-antiga", help="trocar: id da sessão ANTIGA no app (local_...)")
    s.add_argument("--por", default="gestora")
    s.set_defaults(f=cmd_gestora)
    s = sub.add_parser("manual", help="manual do gestor: gerar o GESTOR.md ou ligar/desligar no CLAUDE.local.md do projeto")
    s.add_argument("projeto", nargs="?")
    g = s.add_mutually_exclusive_group()
    for op in ("--gerar", "--previa", "--instalar", "--remover"):
        g.add_argument(op, action="store_true")
    s.add_argument("--confirmar", action="store_true", help="obrigatório para gravar no projeto")
    s.set_defaults(f=cmd_manual)
