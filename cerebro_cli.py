#!/usr/bin/env python
"""Linha de comando do Cérebro do Projeto: é o que o GESTOR (a conversa principal) usa para conferir subagentes e registrar decisões.

Funciona sem o servidor aberto (lê e grava os mesmos arquivos em ~/.cerebro). <projeto> = nome da pasta
(MeuProjeto), apelido que identifica um só projeto, caminho ou o slug do Claude Code.

    python cerebro_cli.py projetos
    python cerebro_cli.py estado MeuProjeto                       # gestora, fila a conferir, tarefas, propostas, mapa
    python cerebro_cli.py a-conferir MeuProjeto                   # subagentes terminados que ainda esperam o gestor
    python cerebro_cli.py conferir MeuProjeto a1b2c3 --resultado aprovado --nota "diff e testes ok"
    python cerebro_cli.py conferir MeuProjeto "lint do mapa" --resultado corrigido --nota "refiz o teste"
    python cerebro_cli.py conferir MeuProjeto --dispensar-antigos # limpa de uma vez os terminados mais velhos que a janela
    python cerebro_cli.py decisao MeuProjeto "Botões com 28 px de altura" --tipo decisao --origem dono
    python cerebro_cli.py decisoes MeuProjeto
    python cerebro_cli.py tarefas MeuProjeto                      # tarefas abertas (propostas aprovadas e as criadas pelo dono na página)
    python cerebro_cli.py tarefas MeuProjeto --novas              # só as novas, em texto pronto para o gestor ler
    python cerebro_cli.py tarefa MeuProjeto n-ab12cd34 --estado recebida --agente "Gestor"
    python cerebro_cli.py tarefa MeuProjeto n-ab12cd34 --estado conferir --agente "agente-codigo" --nota "diff e testes ok"
    python cerebro_cli.py tarefa-feita MeuProjeto t-ab12cd34ef --nota "feito no commit 123abc"
    python cerebro_cli.py orcamento                               # orçamento geral e dos projetos com limite
    python cerebro_cli.py orcamento MeuProjeto --dia 5 --semana 25 --mes 80   # limites em US$ (0 tira o limite); --aviso 80
    python cerebro_cli.py analisar MeuProjeto                     # análise sem IA + propostas
    python cerebro_cli.py backup [--agora] [--listar] [--restaurar DATA [--projeto X] [--so-memoria] [--trocar-diferentes] --confirmar]
    python cerebro_cli.py rotina backup|analise|novidades|mapa      # o que a tarefa agendada do Windows roda
    python cerebro_cli.py agendar backup --ligar|--desligar|--estado
(detalhes do backup e do agendamento: cerebro/cli_backup.py)
    python cerebro_cli.py memoria MeuProjeto --compactar          # proposta de compactação do MEMORY.md (só mostra)
    python cerebro_cli.py memoria MeuProjeto --compactar --aplicar --confirmar   # grava (cópia de segurança antes)
    python cerebro_cli.py memoria MeuProjeto --avisos             # memória velha, contraditória ou citando o que não existe
    python cerebro_cli.py bastao MeuProjeto <sessao>              # resumo de passa-bastão de uma conversa longa
    python cerebro_cli.py hooks --estado                          # ganchos do Claude Code e statusLine do Cérebro
    python cerebro_cli.py hooks --previa [--statusline encadear]  # o que mudaria no ~/.claude/settings.json (nada é gravado)
    python cerebro_cli.py hooks --instalar --confirmar            # liga (cópia de segurança antes; mescla, não apaga nada)
    python cerebro_cli.py hooks --remover --confirmar             # tira só o que é do Cérebro
    python cerebro_cli.py encaixe MeuProjeto --previa             # plano de encaixe (aplicar/desfazer: ver cerebro/cli_encaixe.py)
    python cerebro_cli.py explicar MeuProjeto --estimar           # quantos pontos do mapa, chamadas e tokens (não gasta nada)
    python cerebro_cli.py explicar MeuProjeto --rodar --limite 200   # IA (Haiku) escreve 1 frase para os pontos sem texto
    python cerebro_cli.py gestora estado|preparar|trocar|limpeza|apagada|arquivada MeuProjeto   # troca da sessão gestora
    python cerebro_cli.py manual --gerar | manual MeuProjeto --previa|--instalar --confirmar|--remover --confirmar
(detalhes da troca da gestora e do manual do gestor: cerebro/cli_gestora.py)
"""
import argparse
import sys
import threading
import time
from pathlib import Path

from cerebro import analise, bastao, cli_backup, cli_encaixe, cli_gestora, config, decisoes, explicar_ia, indice, mapa_auto, memoria_avisos, memoria_compactar, memoria_edicao, orcamento, projetos, propostas, revisoes, tarefas_gestor

SAIDA_OK, SAIDA_ERRO = 0, 2


def achar_projeto(ref):
    """Resolve o projeto pelo slug, nome, trecho único do nome ou caminho. Levanta ValueError com a lista se ficar ambíguo."""
    lista = projetos.descobrir(forcar=True)
    baixo = (ref or "").strip().lower().rstrip("\\/")
    if not baixo:
        raise ValueError("informe o projeto")
    for chave in (lambda p: p["slug"].lower(), lambda p: p["nome"].lower(), lambda p: p["caminho"].lower().rstrip("\\/")):
        achados = [p for p in lista if chave(p) == baixo]
        if len(achados) == 1:
            return achados[0]
    achados = [p for p in lista if baixo in p["nome"].lower() or baixo in p["slug"].lower()]
    if len(achados) == 1:
        return achados[0]
    if not achados:
        raise ValueError(f"nenhum projeto casa com {ref!r}. Veja: python cerebro_cli.py projetos")
    raise ValueError(f"vários projetos casam com {ref!r}: " + ", ".join(p["nome"] for p in achados))


def _quando(t):
    if not t:
        return "-"
    d = time.time() - t
    if d < 3600:
        return f"{int(d // 60)} min"
    if d < 86400:
        return f"{int(d // 3600)} h"
    return f"{int(d // 86400)} d"


def cmd_projetos(a):
    for p in projetos.descobrir(forcar=True):
        print(f"{p['nome']:<28} {p['slug']}" + ("  (oculto)" if p["oculto"] else ""))
    return SAIDA_OK


def cmd_estado(a):
    p = achar_projeto(a.projeto)
    cfg = config.ler_config()
    slug = p["slug"]
    ges = (cfg.get("gestoras") or {}).get(slug) or {}
    print(f"Projeto: {p['nome']}  ({p['caminho']})")
    print(f"Gestora: {ges.get('nome') or '(não escolhida)'}")
    f = revisoes.fila(slug, cfg)
    c = f["contadores"]
    print(f"A conferir: {c['a_conferir']} (parados há mais de 24 h: {c['parados']}) · conferidos: {c['conferidos']} "
          f"(aprovados {c['aprovados']}, corrigidos {c['corrigidos']}, recusados {c['recusados']})")
    for m in f["por_modelo"]:
        print(f"  {m['modelo']:<8} {m['pct_primeira']}% aprovado de primeira ({m['aprovado']}/{m['total']})")
    tarefas = tarefas_gestor.listar(slug, cfg, incluir_finais=False)
    print(f"Tarefas abertas: {len(tarefas)} (novas: {sum(1 for t in tarefas if t['estado'] == 'nova')})")
    for t in tarefas[:8]:
        print(f"  {t['id']}  [{t['estado']}] {t['titulo']}")
    print(f"Propostas novas: {propostas.contagem(slug)['novas']}")
    m = projetos.estado_mapa(p["caminho"], slug)
    if m["graphify"]:
        print(f"Mapa: Graphify de {_quando(m['graph_em'])} atrás; página {'gerada há ' + _quando(m['gerado_em']) if m['gerado'] else 'não gerada'}"
              + ("; MAIS VELHO que o último commit" if m["defasado"] else ""))
    else:
        print("Mapa: sem Graphify neste projeto")
    for d in decisoes.listar(slug, 5):
        print(f"Decisão ({d['tipo']}, {d['origem']}, {_quando(d['em'])}): {d['texto'][:120]}")
    return SAIDA_OK


def cmd_a_conferir(a):
    p = achar_projeto(a.projeto)
    f = revisoes.fila(p["slug"], config.ler_config())
    if not f["gestora"]:
        print("O projeto não tem sessão gestora escolhida (Configurações do Cérebro).")
        return SAIDA_OK
    if not f["pendentes"]:
        print(f"Nada a conferir (janela de {f['janela_dias']} dias; {f['antigos']} mais antigos fora da fila).")
        return SAIDA_OK
    for it in f["pendentes"]:
        marca = " PARADO" if it["parado"] else ""
        print(f"{it['id'][:12]}  há {_quando(it['terminou_em']):<6} {it['familia'] or '?':<7} {it['descricao'][:70]}{marca}")
    print(f"\n{len(f['pendentes'])} a conferir. Marque com: python cerebro_cli.py conferir {a.projeto} <id> --resultado aprovado|corrigido|recusado")
    return SAIDA_OK


def cmd_conferir(a):
    p = achar_projeto(a.projeto)
    cfg = config.ler_config()
    if a.dispensar_antigos:
        n = revisoes.dispensar_antigos(p["slug"], cfg)
        print(f"{n} subagente(s) antigo(s) marcados como dispensados.")
        return SAIDA_OK
    if not a.ref or not a.resultado:
        raise ValueError("informe o subagente (id ou trecho da descrição) e --resultado aprovado|corrigido|recusado")
    it = revisoes.conferir(p["slug"], cfg, a.ref, a.resultado, a.nota or "", a.por)
    print(f"Conferido: {it['id'][:12]} · {it['descricao'][:60]} → {it['resultado']}" + (f" ({it['nota']})" if it["nota"] else ""))
    return SAIDA_OK


def cmd_decisao(a):
    p = achar_projeto(a.projeto)
    d = decisoes.registrar(p["slug"], a.texto, a.tipo, a.origem)
    print(f"Registrado ({d['tipo']}, {d['origem']}): {d['texto'][:100]}")
    return SAIDA_OK


def cmd_decisoes(a):
    p = achar_projeto(a.projeto)
    for d in decisoes.listar(p["slug"], a.limite):
        print(f"{time.strftime('%d/%m %H:%M', time.localtime(d['em']))}  [{d['tipo']}/{d['origem']}]  {d['texto']}")
    return SAIDA_OK


def _slug_tarefas(ref):
    return propostas.ESCOPO_CEREBRO if ref == propostas.ESCOPO_CEREBRO else achar_projeto(ref)["slug"]


def cmd_tarefas(a):
    slug = _slug_tarefas(a.projeto)
    if a.novas:
        print(tarefas_gestor.texto_novas(slug) or "Nenhuma tarefa nova.")
        return SAIDA_OK
    lista = tarefas_gestor.listar(slug, incluir_finais=a.todas)
    if not lista:
        print("Nenhuma tarefa aberta.")
    for t in lista:
        extra = f"/{t['esforco']}/{t['risco']}" if t.get("esforco") else ""
        print(f"{t['id']}  [{t['estado']}] [{t['prioridade']}{extra}] {t['titulo']}\n    {(t.get('descricao') or '')[:200]}")
    return SAIDA_OK


def cmd_tarefa(a):
    slug = _slug_tarefas(a.projeto)
    if not a.estado:
        raise ValueError("informe --estado " + "|".join(tarefas_gestor.ESTADOS))
    t = tarefas_gestor.mudar_estado(slug, a.id, a.estado, a.por, a.agente or "", a.nota or "")
    print(f"Tarefa {t['id']} agora está \"{t['estado_rotulo']}\"" + (f" (agente: {t['agente_atual']})" if t.get("agente_atual") else "") + f": {t['titulo']}")
    return SAIDA_OK


def _dinheiro(texto):
    try:
        return float(str(texto).replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"valor inválido: {texto!r} (use um número em US$, ex.: 25 ou 12,5)") from None


def cmd_orcamento(a):
    escopo = achar_projeto(a.projeto)["slug"] if a.projeto else "geral"
    campos = {k: v for k, v in (("dia", a.dia), ("semana", a.semana), ("mes", a.mes), ("aviso_pct", a.aviso)) if v is not None}
    if campos:
        orcamento.definir(escopo, **campos)
        print("Orçamento de " + ("todos os projetos" if escopo == "geral" else a.projeto) + " salvo.\n")
    print(orcamento.texto_estado(orcamento.estado(), None if escopo == "geral" else escopo))
    return SAIDA_OK


def cmd_tarefa_feita(a):
    propostas.concluir_tarefa(_slug_tarefas(a.projeto), a.id, a.nota or "")
    print("Tarefa marcada como feita.")
    return SAIDA_OK


def cmd_analisar(a):
    slug = _slug_tarefas(a.projeto)
    d = analise.executar(slug, config.ler_config())
    r = d["resumo"]
    print(f"Análise em {r['duracao']} s: {r['propostas']} proposta(s), {r['novas']} nova(s).")
    for p in d["propostas"]:
        if p["estado"] == "nova":
            print(f"  {p['id']} [{p['esforco']}/{p['risco']}] {p['titulo']}")
    return SAIDA_OK


def cmd_memoria(a):
    p = achar_projeto(a.projeto)
    if a.avisos:
        cfg = config.ler_config()
        dias = int((cfg.get("memoria_avisos") or {}).get("dias_velha") or memoria_avisos.DIAS_VELHA)
        d = memoria_avisos.avisos(p["slug"], p["caminho"], dias=dias, usar_cache=False)
        if not d["avisos"]:
            print("Nenhum aviso de memória.")
        for x in d["avisos"]:
            print(f"[{x['tipo']}] {x['titulo']}")
            print(f"    {x['motivo']}")
        print()
        print(f"{d['total']} aviso(s), todos a conferir (nada foi mudado).")
        return SAIDA_OK
    if not a.compactar:
        raise ValueError("use --compactar ou --avisos")
    try:
        r = memoria_compactar.propor(p["slug"])
    except memoria_edicao.Recusado as e:
        raise ValueError(str(e)) from None
    print(f"MEMORY.md: ≈ {r['tokens_antes']} → ≈ {r['tokens_depois']} tokens por conversa (economia ≈ {r['economia']}, {r['pct']}%)")
    print("Mudanças: " + (", ".join(f"{k}: {v}" for k, v in r["contagem"].items()) or "nenhuma"))
    for x in r["apontamentos"]["sem_arquivo"]:
        print(f"  a conferir: linha {x['linha']} aponta para {x['alvo']}, que não existe")
    for nome in r["apontamentos"]["sem_linha"]:
        print(f"  a conferir: {nome} não tem linha no índice")
    print("Verificador:")
    for c in r["verificacao"]["checagens"]:
        print(f"  [{'ok' if c['ok'] else 'FALHOU'}] {c['nome']}: {c['detalhe']}")
    if r["diff"]:
        print()
        print(r["diff"])
    print()
    if not a.aplicar:
        print("Só a proposta. Para gravar: --aplicar --confirmar")
        return SAIDA_OK
    if not a.confirmar:
        print("Prévia acima. Nada foi gravado: repita com --confirmar para gravar (com cópia de segurança antes).")
        return SAIDA_OK
    try:
        g = memoria_compactar.aplicar(p["slug"], r["versao"], confirmar=True)
    except memoria_edicao.Recusado as e:
        raise ValueError(str(e)) from None
    print(f"Gravado. Cópia de segurança em: {g['copia']}")
    return SAIDA_OK


def cmd_bastao(a):
    p = achar_projeto(a.projeto)
    ids = [x["id"] for x in indice.listar_arquivos(p["slug"]) if x["tipo"] == "sessao" and x["id"].startswith(a.sessao)]
    if len(ids) != 1:
        raise ValueError("sessão não encontrada" if not ids else "vários ids começam assim: " + ", ".join(ids[:5]))
    print(bastao.resumo(p["slug"], ids[0]))
    print(f"(gravado em {bastao.caminho_resumo(p['slug'], ids[0])})", file=sys.stderr)
    return SAIDA_OK


def cmd_hooks(a):
    from cerebro import ganchos_claude
    if a.estado or not (a.previa or a.instalar or a.remover):
        e = ganchos_claude.estado()
        print(f"Arquivo: {e['arquivo']}" + ("" if e["existe"] else " (não existe ainda)"))
        if not e["valido"]:
            print(f"ATENÇÃO: {e['erro']}")
            return SAIDA_ERRO
        print(f"Ganchos do Cérebro: {', '.join(e['eventos']) or 'desligados'}" + (f" (modo {e['modo']})" if e["modo"] else ""))
        print(f"Outros ganchos no arquivo (não são do Cérebro, ficam como estão): {e['outros_ganchos']}")
        print(f"statusLine: {e['statusline']}" + (" (encadeada com a sua antiga)" if e["statusline_encadeada"] else ""))
        if e["precisa_reinstalar"]:
            print(f"ATENÇÃO: os ganchos apontam para a porta {e['porta_instalada']}, mas a porta configurada é {e['porta_config']}. Reinstale.")
        return SAIDA_OK
    hooks = not a.sem_hooks
    if a.previa:
        p = ganchos_claude.previa(hooks, a.modo, a.statusline)
        if p["precisa_decidir"]:
            print("Você já tem uma statusLine. Escolha --statusline encadear (o Cérebro chama a sua) ou --statusline substituir.")
        print(p["diferenca"] or "Nada muda: já está instalado assim.")
        return SAIDA_OK
    if a.instalar:
        if not a.confirmar:
            raise ValueError("nada foi alterado: veja antes com --previa e repita com --confirmar")
        r = ganchos_claude.instalar(True, hooks, a.modo, a.statusline)
    else:
        if not a.confirmar:
            raise ValueError("nada foi alterado: repita com --confirmar")
        r = ganchos_claude.remover(True, not a.so_statusline, not a.so_hooks)
    print(r["diferenca"] or "Nada mudou.")
    if r["copia"]:
        print(f"Cópia de segurança: {r['copia']}")
    return SAIDA_OK


def cmd_explicar(a):
    p = achar_projeto(a.projeto)
    if not (Path(p["caminho"]) / "graphify-out" / "graph.json").is_file():
        raise ValueError("este projeto ainda não tem o mapa do Graphify")
    est = explicar_ia.estimar(p["slug"], p["caminho"], a.limite, a.via)
    print(f"Pontos do mapa: {est['pontos']} · sem texto no código: {est['sem_texto']} · já explicados: {est['ja_explicados']} · "
          f"desatualizados: {est['desatualizados']} · pulados por segurança: {est['pulados_sensiveis']}")
    print(f"Esta rodada ({est['modelo']}, via {est['via']}): {est['nesta_rodada']} pontos em {est['lotes']} chamadas, "
          f"cerca de {est['tokens_total']} tokens ({est['tokens_entrada']} de entrada + {est['tokens_saida']} de saída). Faltam {est['faltam']} no total.")
    print(est["aviso"])
    if not a.rodar:
        print("Nada foi gasto. Para explicar de verdade: python cerebro_cli.py explicar <projeto> --rodar [--limite N]")
        return SAIDA_OK
    if not est["nesta_rodada"]:
        print("Nada a explicar agora.")
        return SAIDA_OK
    if a.via == "claude" and not est["claude_encontrado"]:
        raise ValueError("não achei o programa `claude` neste PC")
    if a.via == "api" and not est["tem_chave_api"]:
        raise ValueError("não há ANTHROPIC_API_KEY neste PC")
    parar = threading.Event()

    def mostrar(r):
        print(f"  {r['explicados']} explicados, {r['sem_resposta']} sem resposta · lote {r['lotes_feitos']}/{r['lotes']}"
              + (f" · {r['falhas']} falha(s)" if r["falhas"] else ""), flush=True)
    try:
        res = explicar_ia.rodar(p["slug"], p["caminho"], a.limite, explicar_ia.chamador(a.via), parar, mostrar)
    except KeyboardInterrupt:
        parar.set()
        print("Interrompido: o que já foi explicado ficou guardado; rode de novo para continuar.")
        return SAIDA_OK
    print(f"Pronto: {res['explicados']} pontos explicados, {res['sem_resposta']} sem resposta."
          + (f" Gasto medido: {res['tokens_entrada']} de entrada, {res['tokens_saida']} de saída." if res["tokens_entrada"] else ""))
    if res["erro"]:
        print(f"Aviso: {res['erro']}", file=sys.stderr)
    if res["explicados"]:
        ok, texto = mapa_auto.gerar_agora(p["slug"], p["caminho"])
        print("Página do mapa refeita." if ok else f"A página do mapa não foi refeita ({texto[-200:] if texto else 'sem detalhe'}); use o botão do mapa.")
    return SAIDA_OK if not res["erro"] or res["explicados"] else SAIDA_ERRO


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cérebro do Projeto — linha de comando do gestor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("projetos").set_defaults(f=cmd_projetos)
    for nome, f in (("estado", cmd_estado), ("a-conferir", cmd_a_conferir)):
        s = sub.add_parser(nome)
        s.add_argument("projeto")
        s.set_defaults(f=f)
    s = sub.add_parser("conferir")
    s.add_argument("projeto")
    s.add_argument("ref", nargs="?", help="id (ou começo do id) do subagente, ou trecho da descrição")
    s.add_argument("--resultado", choices=revisoes.RESULTADOS)
    s.add_argument("--nota", default="")
    s.add_argument("--por", default="gestor")
    s.add_argument("--dispensar-antigos", action="store_true", help="marca como dispensados os terminados mais velhos que a janela")
    s.set_defaults(f=cmd_conferir)
    s = sub.add_parser("decisao")
    s.add_argument("projeto")
    s.add_argument("texto")
    s.add_argument("--tipo", choices=decisoes.TIPOS, default="decisao")
    s.add_argument("--origem", default="gestor", help="dono ou gestor")
    s.set_defaults(f=cmd_decisao)
    s = sub.add_parser("decisoes")
    s.add_argument("projeto")
    s.add_argument("--limite", type=int, default=30)
    s.set_defaults(f=cmd_decisoes)
    s = sub.add_parser("tarefas")
    s.add_argument("projeto")
    s.add_argument("--todas", action="store_true", help="inclui as já terminadas (feitas e recusadas)")
    s.add_argument("--novas", action="store_true", help="só as novas, em texto completo para o gestor (pontos do mapa, arquivos, agente, modelo, revisor)")
    s.set_defaults(f=cmd_tarefas)
    s = sub.add_parser("tarefa", help="muda o estado de uma tarefa e registra no histórico")
    s.add_argument("projeto")
    s.add_argument("id")
    s.add_argument("--estado", choices=tarefas_gestor.ESTADOS)
    s.add_argument("--agente", default="", help="qual agente ou sessão está com a tarefa")
    s.add_argument("--nota", default="")
    s.add_argument("--por", default="gestor")
    s.set_defaults(f=cmd_tarefa)
    s = sub.add_parser("orcamento", help="mostra ou define o orçamento de gasto (estimativa em US$) de um projeto ou geral")
    s.add_argument("projeto", nargs="?", help="sem projeto = orçamento geral (todos os projetos)")
    s.add_argument("--dia", type=_dinheiro, help="limite por dia em US$ (0 tira o limite)")
    s.add_argument("--semana", type=_dinheiro, help="limite por semana em US$ (0 tira o limite)")
    s.add_argument("--mes", type=_dinheiro, help="limite por mês em US$ (0 tira o limite)")
    s.add_argument("--aviso", type=int, help="percentual do limite em que começa o aviso (padrão 80)")
    s.set_defaults(f=cmd_orcamento)
    s = sub.add_parser("tarefa-feita")
    s.add_argument("projeto")
    s.add_argument("id")
    s.add_argument("--nota", default="")
    s.set_defaults(f=cmd_tarefa_feita)
    s = sub.add_parser("analisar")
    s.add_argument("projeto")
    s.set_defaults(f=cmd_analisar)
    cli_backup.adicionar_subcomandos(sub)          # backup, rotina, agendar
    s = sub.add_parser("memoria", help="compactar o MEMORY.md ou ver avisos de memória")
    s.add_argument("projeto")
    s.add_argument("--compactar", action="store_true", help="mostra a proposta de compactação (sem IA)")
    s.add_argument("--aplicar", action="store_true", help="com --confirmar, grava a proposta")
    s.add_argument("--confirmar", action="store_true", help="confirma a gravação (cópia de segurança antes)")
    s.add_argument("--avisos", action="store_true", help="memória velha, contraditória ou citando o que não existe")
    s.set_defaults(f=cmd_memoria)
    s = sub.add_parser("bastao", help="resumo de passa-bastão de uma conversa")
    s.add_argument("projeto")
    s.add_argument("sessao", help="id da sessão (ou o começo dele)")
    s.set_defaults(f=cmd_bastao)
    s = sub.add_parser("hooks", help="ganchos do Claude Code (agentes ao vivo instantâneo) e statusLine (anéis de limite)")
    g = s.add_mutually_exclusive_group()
    for op in ("--estado", "--previa", "--instalar", "--remover"):
        g.add_argument(op, action="store_true")
    s.add_argument("--confirmar", action="store_true", help="obrigatório para gravar no settings.json")
    s.add_argument("--modo", choices=("comando", "http"), default="comando", help="comando (padrão, nunca atrasa o Claude Code) ou http")
    s.add_argument("--statusline", choices=("instalar", "encadear", "substituir"), help="também instala a statusLine do Cérebro")
    s.add_argument("--sem-hooks", action="store_true", help="só a statusLine")
    s.add_argument("--so-hooks", action="store_true", help="ao remover: deixa a statusLine")
    s.add_argument("--so-statusline", action="store_true", help="ao remover: deixa os ganchos")
    s.set_defaults(f=cmd_hooks)
    cli_encaixe.registrar(sub, achar_projeto)       # instalar-ferramenta, encaixe, agentes-copiar (escrevem só com --confirmar)
    cli_gestora.registrar(sub, achar_projeto)       # gestora (troca da sessão gestora) e manual (GESTOR.md / CLAUDE.local.md)
    s = sub.add_parser("explicar", help="IA (Haiku) escreve uma frase simples para os pontos do mapa sem texto")
    s.add_argument("projeto")
    modo = s.add_mutually_exclusive_group()
    modo.add_argument("--estimar", action="store_true", help="só mostra a estimativa (padrão; não gasta nada)")
    modo.add_argument("--rodar", action="store_true", help="explica de verdade (gasta tokens)")
    s.add_argument("--limite", type=int, default=explicar_ia.LIMITE_PADRAO, help=f"pontos por rodada (padrão {explicar_ia.LIMITE_PADRAO})")
    s.add_argument("--via", choices=("claude", "api"), default="claude", help="claude = seu plano (padrão); api = ANTHROPIC_API_KEY, cobrado por uso")
    s.set_defaults(f=cmd_explicar)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        return a.f(a)
    except (ValueError, *cli_backup.ERROS) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return SAIDA_ERRO


if __name__ == "__main__":
    sys.exit(main())
