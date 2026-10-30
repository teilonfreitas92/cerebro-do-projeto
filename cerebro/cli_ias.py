"""Subcomandos das outras IAs (cerebro_cli.py chama adicionar_subcomandos). Quem usa é o gestor, pela linha de comando:

    python cerebro_cli.py ia situacao                                   # quais IAs têm chave e qual modelo
    python cerebro_cli.py ia rodar meu-projeto --ia deepseek --tarefa "..."  # a IA faz o serviço numa cópia do projeto
    python cerebro_cli.py ia rodar meu-projeto --ia gemini --arquivo-tarefa tarefa.md
    python cerebro_cli.py ia listar meu-projeto                              # serviços feitos (id, ramo, estado)
    python cerebro_cli.py ia juntar meu-projeto <id>                         # depois de conferir: junta no projeto
    python cerebro_cli.py ia descartar meu-projeto <id>                      # joga fora a cópia e o ramo
"""
import time
from pathlib import Path

from . import config, ias_externas, indice

SAIDA_OK, SAIDA_ERRO = 0, 2


def _projeto(ref):
    import cerebro_cli
    return cerebro_cli.achar_projeto(ref)


def sessao_do_gestor(slug, cfg):
    """A conversa gestora do projeto (as IAs aparecem como subagentes dela); sem gestora, a conversa mexida por último."""
    g = ((cfg.get("gestoras") or {}).get(slug) or {}).get("conversa")
    if g:
        return g
    sessoes = [a for a in indice.listar_arquivos(slug) if a["tipo"] == "sessao"]
    if not sessoes:
        raise ias_externas.ErroIA("o projeto não tem nenhuma conversa do Claude Code ainda")
    return max(sessoes, key=lambda a: a["mtime"])["id"]


def cmd_ia(a):
    cfg = config.ler_config()
    if a.acao == "situacao":
        s = ias_externas.situacao(cfg)
        for i in s["ias"]:
            print(f"{i['id']:9} {i['nome']:16} modelo {i['modelo']:20} " + (f"chave ok (…{i['final']})" if i["configurada"] else "SEM CHAVE"))
        print("Comandos permitidos: " + ", ".join(s["comandos"]))
        return SAIDA_OK
    if not a.projeto:
        raise ValueError("informe o projeto")
    p = _projeto(a.projeto)
    if a.acao == "listar":
        for r in ias_externas.listar(p["slug"]):
            print(f"{r['id']}  {r['nome']:16} {r['estado']:10} {r['ramo']}  {r['tarefa'][:60]}")
        return SAIDA_OK
    if a.acao in ("juntar", "descartar"):
        if not a.id:
            raise ValueError("informe o id do serviço (veja: ia listar)")
        r = (ias_externas.juntar if a.acao == "juntar" else ias_externas.descartar)(p["slug"], a.id)
        print(f"{r['estado'].capitalize()}: {r['ramo']}")
        return SAIDA_OK
    # rodar
    if not a.ia:
        raise ValueError("diga qual IA faz o serviço: --ia " + "|".join(ias_externas.PROVEDORES))
    tarefa = a.tarefa or ""
    if a.arquivo_tarefa:
        tarefa = Path(a.arquivo_tarefa).read_text(encoding="utf-8")
    sessao = a.sessao or sessao_do_gestor(p["slug"], cfg)
    print(f"{ias_externas.PROVEDORES[a.ia]['nome']} trabalhando numa cópia de {p['nome']} (acompanhe em Agentes ao vivo)…", flush=True)
    t0 = time.time()
    r = ias_externas.rodar(p["slug"], p["caminho"], a.ia, tarefa, sessao, cfg, avisar=lambda t: print(t, flush=True))
    print(f"\nEstado: {r['estado']} · {r['voltas']} voltas · {int(time.time() - t0)} s · "
          f"{r['tokens_entrada']} tokens de entrada, {r['tokens_saida']} de saída")
    print(f"Id: {r['id']}  (para conferir: ia-{r['ia']}-{r['id']})\nRamo: {r['ramo']}\nCópia: {r['pasta']}")
    print("Mudanças:\n" + (r.get("mudancas") or "(nenhuma)"))
    print("\nResumo da IA:\n" + (r["resumo"] or "(vazio)"))
    print(f"\nConfira antes de aceitar:  git -C \"{p['caminho']}\" diff {r['base'][:12]}..{r['ramo']}")
    print(f"Aceitar:   python cerebro_cli.py ia juntar {p['slug']} {r['id']}")
    print(f"Recusar:   python cerebro_cli.py ia descartar {p['slug']} {r['id']}")
    return SAIDA_OK if r["estado"] == "pronto" else SAIDA_ERRO


def adicionar_subcomandos(sub):
    s = sub.add_parser("ia", help="outras IAs (OpenAI, DeepSeek, Grok, Gemini) fazendo serviço de subagente para o gestor")
    s.add_argument("acao", choices=["situacao", "rodar", "listar", "juntar", "descartar"])
    s.add_argument("projeto", nargs="?")
    s.add_argument("id", nargs="?", help="id do serviço (juntar/descartar)")
    s.add_argument("--ia", choices=list(ias_externas.PROVEDORES), help="qual IA faz o serviço")
    s.add_argument("--tarefa", help="o que fazer (como o pedido a um subagente)")
    s.add_argument("--arquivo-tarefa", help="lê a tarefa de um arquivo (tarefas longas)")
    s.add_argument("--sessao", help="conversa a que o serviço pertence (padrão: a gestora do projeto)")
    s.set_defaults(f=cmd_ia)


ERROS = (ias_externas.ErroIA,)
