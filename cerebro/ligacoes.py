"""Ligações entre os módulos da 1.3 (cada um foi feito sozinho; aqui eles conversam):

* tarefas novas do dono → contexto da sessão GESTORA (gancho UserPromptSubmit; só a gestora do projeto, só quando muda);
* gancho PreCompact (o Claude Code vai compactar a conversa) → grava o passa-bastão daquela sessão (bastao.resumo) e, se é a
  sessão GESTORA, um capítulo datado (capitulos.gravar);
* manual do gestor: a sessão gestora recebe UMA vez por versão "Cérebro atualizado para X — leia ~/.cerebro/GESTOR.md";
* contexto da gestora acima do limite (gestora_troca.recado_limite): UMA vez por transcrição, o recado de rodar
  `gestora limpar` e chamar clear_session ao fim do turno (sem Stop hook: ele prenderia a conversa);
* SessionStart: capítulo de transcrição que saiu por /clear manual e trocas pendentes da CLI (gestora_troca);
* alertas de orçamento e de backup → aviso do Windows, no máximo uma vez por dia para o mesmo alerta.

Tudo tolera falha: um erro aqui nunca derruba o receptor dos ganchos nem o laço de rotinas do servidor."""
import threading
import time

from . import armazem, avisos, config, ganchos_eventos

UM_DIA = 86400
_trava = threading.Lock()
_ultimo_contexto = {}          # session_id -> texto já entregue (não repete a mesma lista a cada mensagem)


def _gestora(slug):
    return ((config.ler_config().get("gestoras") or {}).get(slug) or {}).get("conversa", "")


def _ao_mandar_mensagem(ev):
    """UserPromptSubmit: na sessão gestora, devolve as tarefas novas como contexto (o receptor manda como additionalContext)."""
    slug, sid = ev.get("slug"), ev.get("session_id")
    if not slug or not sid or sid != _gestora(slug):
        return None
    from . import tarefas_gestor
    texto = tarefas_gestor.texto_para_contexto(slug)
    with _trava:
        if not texto or _ultimo_contexto.get(sid) == texto:
            return None
        _ultimo_contexto[sid] = texto
    return texto


def _ao_compactar(ev):
    """PreCompact: guarda o passa-bastão antes de a conversa ser resumida pelo Claude Code (e o capítulo, se for a gestora)."""
    slug, sid = ev.get("slug"), ev.get("session_id")
    if not slug or not sid:
        return None
    from . import bastao
    bastao.resumo(slug, sid)
    if sid == _gestora(slug):
        from . import capitulos
        capitulos.gravar(slug, sid)
    return None


def _aviso_manual(ev):
    """UserPromptSubmit na sessão gestora: recado do manual atualizado (uma vez por versão) e do limite de contexto."""
    slug, sid = ev.get("slug"), ev.get("session_id")
    if not slug or not sid or sid != _gestora(slug):
        return None
    from . import gestora_troca, manual_gestor
    textos = [manual_gestor.recado_para_sessao(sid), gestora_troca.recado_limite(slug, sid)]
    return "\n\n".join(x for x in textos if x) or None


def _ao_iniciar(ev):
    """SessionStart: grava o capítulo de quem saiu por /clear manual e completa trocas pendentes (barato quando não há nada)."""
    slug = ev.get("slug")
    if not slug:
        return None
    from . import gestora_troca
    gestora_troca.capitulos_pendentes(slug)
    gestora_troca.completar_pendentes(slug)
    return None


def ligar():
    """Registra os ouvintes (pode chamar mais de uma vez: não duplica)."""
    ganchos_eventos.registrar_ouvinte("UserPromptSubmit", _ao_mandar_mensagem)
    ganchos_eventos.registrar_ouvinte("PreCompact", _ao_compactar)
    ganchos_eventos.registrar_ouvinte("UserPromptSubmit", _aviso_manual)
    ganchos_eventos.registrar_ouvinte("SessionStart", _ao_iniciar)


def rotina_retencao(agora=None):
    """Rotina do servidor: transcrições antigas da gestora nos projetos AUTORIZADOS (no máximo 1 vez por dia; ver retencao_gestora)."""
    from . import retencao_gestora
    return retencao_gestora.rodar(agora=agora)


def _arquivo_enviados():
    return config.CASA / "avisos_enviados.json"


def avisar_alertas(agora=None):
    """Orçamento e backup → aviso do Windows. O mesmo alerta (chave) só volta a avisar depois de um dia. Devolve os avisados."""
    agora = agora or time.time()
    itens = []
    try:
        from . import orcamento
        itens += [(a["chave"], a["titulo"], a["texto"]) for a in orcamento.alertas()]
    except Exception as e:
        print(f"Alertas de orçamento: {type(e).__name__}: {e}", flush=True)
    try:
        from . import backup
        itens += [("backup:" + a["titulo"], a["titulo"], a["texto"]) for a in backup.alertas(agora) if a.get("nivel") == "aviso"]
    except Exception as e:
        print(f"Alertas de backup: {type(e).__name__}: {e}", flush=True)
    if not itens:
        return []
    feitos = []

    def mudar(enviados):
        enviados = {k: v for k, v in (enviados or {}).items() if agora - v < 7 * UM_DIA}     # esquece o que tem mais de 7 dias
        for chave, titulo, texto in itens:
            if agora - enviados.get(chave, 0) >= UM_DIA:
                enviados[chave] = agora
                feitos.append((chave, titulo, texto))
        return enviados

    config.garantir_casa()
    armazem.atualizar_json(_arquivo_enviados(), {}, mudar)
    for chave, titulo, texto in feitos:
        avisos.avisar(titulo, texto, chave, tipo="geral", agora=agora)
    return [c for c, _, _ in feitos]
