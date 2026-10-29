"""O que cada rotina agendada no Windows faz quando roda sozinha (cerebro_cli.py rotina <nome>), com log e último resultado.

  backup     faz o backup de hoje (pula se já existe: a tarefa também roda ao fazer logon);
  analise    "Analisar agora" (sem IA) de cada projeto visível e do próprio Cérebro;
  novidades  procura novidades (só GET em páginas públicas de releases);
  mapa       refaz a página do mapa dos projetos que JÁ têm graphify-out/graph.json. Não roda o Graphify (nem com IA nem
             sem): só o mapa/gerar.py, que lê o graph.json. Por garantia, GRAPHIFY_BACKEND=none fica definido no processo.

Log em ~/.cerebro/rotinas/<nome>.log (rotativo: passou de 256 KB, vira <nome>.log.1 e começa outro) e o último resultado
em ~/.cerebro/rotinas/<nome>.json (a página mostra "última execução e resultado").
"""
import json
import os
import time
import traceback
from pathlib import Path

from . import agendador, config

LIMITE_LOG = 256 * 1024


def _pasta():
    p = Path(config.CASA) / "rotinas"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log(nome, texto):
    arq = _pasta() / f"{nome}.log"
    try:
        if arq.is_file() and arq.stat().st_size > LIMITE_LOG:
            velho = arq.with_name(arq.name + ".1")
            config.remover(velho)                       # o .1 anterior sai pela trava de sempre
            os.replace(arq, velho)
        with open(arq, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + texto.rstrip() + "\n")
    except OSError:
        pass


def ultimo(nome):
    try:
        d = json.loads((_pasta() / f"{nome}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _gravar_ultimo(nome, dados):
    arq = _pasta() / f"{nome}.json"
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, arq)


def _visiveis():
    from . import projetos
    return [p for p in projetos.descobrir(forcar=True) if not p["oculto"]]


def _r_backup():
    from . import backup
    r = backup.fazer_backup(so_se_faltar_hoje=True)
    if r.get("pulado"):
        return True, r["motivo"]
    txt = f"{r['nome']}: {r['arquivos']} arquivos, {r['bytes_zip'] // 1024} KB no zip em {r['duracao']} s"
    if r["falhas"]:
        txt += f"; {len(r['falhas'])} arquivo(s) não lido(s): " + ", ".join(f["arq"] for f in r["falhas"][:5])
    if r["encolheu"]:
        txt += "; ATENÇÃO: bem menor que o anterior (o anterior ficou protegido)"
    if r["removidos"]:
        txt += "; rotação removeu " + ", ".join(r["removidos"])
    return True, txt


def _r_analise():
    from . import analise, propostas
    cfg = config.ler_config()
    feitos, erros = [], []
    for slug in [p["slug"] for p in _visiveis()] + [propostas.ESCOPO_CEREBRO]:
        try:
            d = analise.executar(slug, cfg)
            feitos.append(f"{slug} ({d['resumo']['novas']} nova(s))")
        except Exception as e:
            erros.append(f"{slug}: {type(e).__name__}: {str(e)[:120]}")
    return not erros, "analisados: " + ", ".join(feitos) + ((" | erros: " + "; ".join(erros)) if erros else "")


def _r_novidades():
    from . import novidades
    d = novidades.procurar(config.ler_config())
    if d.get("sem_rede"):
        return False, "sem internet ou API indisponível: " + "; ".join(d.get("erros") or [])[:300]
    return True, f"consulta feita: {len(d.get('novas') or [])} proposta(s) nova(s)" + (("; avisos: " + "; ".join(d["erros"])[:300]) if d.get("erros") else "")


def _r_mapa():
    os.environ["GRAPHIFY_BACKEND"] = "none"          # garantia: nada daqui chama IA do Graphify
    from . import mapa_auto
    feitos = mapa_auto.varrer(forcar=True)
    erros = [f"{p['slug']}: {mapa_auto.estado(p['slug']).get('ultimo_erro', '')[-120:]}" for p in _visiveis()
             if mapa_auto.estado(p["slug"]).get("ultimo_erro")]
    return not erros, ("refeitos: " + ", ".join(feitos) if feitos else "todos os mapas em dia") + ((" | erros: " + "; ".join(erros)) if erros else "")


FAZER = {"backup": _r_backup, "analise": _r_analise, "novidades": _r_novidades, "mapa": _r_mapa}


def executar(nome, fazer=None):
    """Roda a rotina, registra no log e em <nome>.json. Devolve {ok, texto, em, duracao}. Nunca levanta (a tarefa agendada
    não tem janela para mostrar erro: tudo vai para o log)."""
    if nome not in agendador.ROTINAS:
        raise ValueError(f"rotina desconhecida: {nome!r} (use {', '.join(agendador.ROTINAS)})")
    fazer = fazer or FAZER[nome]
    inicio = time.time()
    _log(nome, "início")
    try:
        ok, texto = fazer()
    except Exception as e:
        ok, texto = False, f"{type(e).__name__}: {e}"
        _log(nome, traceback.format_exc()[-1500:])
    dados = {"em": inicio, "ok": bool(ok), "texto": str(texto)[:1000], "duracao": round(time.time() - inicio, 1)}
    _log(nome, ("ok: " if ok else "ERRO: ") + dados["texto"])
    try:
        _gravar_ultimo(nome, dados)
    except OSError:
        pass
    return dados


def situacao():
    """Para a página: cada rotina com parâmetros, estado no Agendador e última execução."""
    cfg = config.ler_config()
    saida = []
    for nome in agendador.ROTINAS:
        try:
            est = agendador.estado(nome)
        except agendador.AgendadorErro as e:
            est = {"disponivel": agendador.disponivel(), "ligada": False, "erro": str(e)}
        saida.append({"rotina": nome, "descricao": agendador.DESCRICOES[nome], "parametros": agendador.parametros(nome, cfg),
                      "agendador": est, "ultima_execucao": ultimo(nome)})
    return {"disponivel": agendador.disponivel(), "rotinas": saida, "python": str(agendador.python_das_rotinas())}
