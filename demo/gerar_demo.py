#!/usr/bin/env python
"""Gera dados 100% FICTÍCIOS para ver o Cérebro do Projeto funcionando sem nenhum dado seu.

    python demo/gerar_demo.py --destino demo/saida

Cria, SÓ dentro da pasta de destino:
  casa/                       a "~/.cerebro" da demonstração (CEREBRO_HOME)
  claude/projects/            as "conversas do Claude Code" inventadas (CEREBRO_CLAUDE)
  projetos/<nome>/            3 projetos inventados (código pequeno, git com alguns commits, graphify-out de exemplo)
Cada projeto ganha: sessão gestora, subagentes de vários modelos, custos, memória, decisões, propostas, ferramentas executadas e mapa.
Nada aqui vem de um projeto ou de uma conversa de verdade. A pasta de destino leva a marca .cerebro-demo; só uma pasta com essa marca
(ou vazia) é limpa e refeita.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MARCA = ".cerebro-demo"

# --------------------------------------------------------------------------------------------------------------------
# Os projetos inventados: módulos -> funções -> quem cada uma chama
# --------------------------------------------------------------------------------------------------------------------
PROJETOS = {
    "loja-de-plantas": {"pacote": "loja", "lang": "py", "modulos": {
        "catalogo": {"listar_plantas": [], "buscar_planta": ["listar_plantas"], "filtrar_por_luz": ["listar_plantas"], "ordenar_por_preco": ["listar_plantas"],
                     "carregar_estoque": [], "plantas_em_promocao": ["listar_plantas", "ordenar_por_preco"]},
        "carrinho": {"criar_carrinho": [], "adicionar_item": ["criar_carrinho", "buscar_planta"], "remover_item": ["criar_carrinho"],
                     "total_do_carrinho": ["adicionar_item"], "aplicar_cupom": ["total_do_carrinho"]},
        "pagamentos": {"calcular_frete": [], "validar_cartao": [], "iniciar_pagamento": ["validar_cartao", "total_do_carrinho", "calcular_frete"],
                       "confirmar_pedido": ["iniciar_pagamento"]},
        "pedidos": {"criar_pedido": ["confirmar_pedido"], "listar_pedidos": [], "cancelar_pedido": ["listar_pedidos"], "reembolsar": ["cancelar_pedido"]},
        "estoque": {"carregar_estoque_diario": [], "baixar_do_estoque": ["carregar_estoque_diario"], "repor_estoque": ["carregar_estoque_diario"],
                    "alertar_estoque_baixo": ["baixar_do_estoque"], "inventario_geral": ["carregar_estoque_diario", "alertar_estoque_baixo"]},
        "clientes": {"criar_cliente": [], "entrar_cliente": ["criar_cliente"], "endereco_do_cliente": ["entrar_cliente"], "historico_do_cliente": ["listar_pedidos", "entrar_cliente"]},
        "avaliacoes": {"enviar_avaliacao": ["entrar_cliente"], "media_de_avaliacoes": ["enviar_avaliacao"], "destacar_avaliacoes": ["media_de_avaliacoes", "buscar_planta"]},
        "notificacoes": {"enviar_email": [], "avisar_pedido_enviado": ["enviar_email", "criar_pedido"], "avisar_estoque": ["enviar_email", "alertar_estoque_baixo"]},
        "servidor": {"rota_catalogo": ["buscar_planta", "filtrar_por_luz", "destacar_avaliacoes"], "rota_carrinho": ["adicionar_item", "aplicar_cupom", "baixar_do_estoque"],
                     "rota_pagamento": ["iniciar_pagamento", "avisar_pedido_enviado"], "rota_conta": ["endereco_do_cliente", "historico_do_cliente"],
                     "iniciar": ["rota_catalogo", "rota_carrinho", "rota_pagamento", "rota_conta"]}},
        "extra": {"docs/arquitetura.md": "# Arquitetura\nCatálogo, carrinho, pagamentos e pedidos.\n", "docs/api.md": "# API\nRotas do catálogo e do carrinho.\n",
                  "README.md": "# Loja de plantas\nProjeto inventado para a demonstração do Cérebro.\n", "requirements.txt": "flask==3.0.0\n",
                  "ruff.toml": 'target-version = "py311"\n\n[lint]\nselect = ["E9", "F"]\n'}},
    "app-de-receitas": {"pacote": "src", "lang": "js", "modulos": {
        "receitas": {"carregarReceitas": [], "buscarPorIngrediente": ["carregarReceitas"], "filtrarPorTempo": ["carregarReceitas"], "favoritar": ["buscarPorIngrediente"]},
        "lista": {"criarLista": [], "adicionarIngrediente": ["criarLista"], "marcarComprado": ["criarLista"], "totalDaLista": ["adicionarIngrediente"]},
        "interface": {"desenharCartao": ["favoritar"], "desenharLista": ["totalDaLista"], "abrirTela": ["desenharCartao", "desenharLista"]},
        "sincronia": {"enviarFavoritos": ["favoritar"], "baixarReceitas": ["carregarReceitas"], "resolverConflito": ["enviarFavoritos", "baixarReceitas"]},
        "agenda": {"planejarSemana": ["buscarPorIngrediente", "filtrarPorTempo"], "sugerirJantar": ["planejarSemana"], "exportarCardapio": ["planejarSemana", "totalDaLista"]}},
        "extra": {"package.json": json.dumps({"name": "app-de-receitas", "version": "1.0.0", "private": True,
                                              "scripts": {"test": "node --test", "lint": "eslint ."}}, indent=2) + "\n",
                  "eslint.config.js": "export default [];\n", "README.md": "# App de receitas\nProjeto inventado para a demonstração do Cérebro.\n",
                  "docs/ideias.md": "# Ideias\nModo offline e lista de compras compartilhada.\n"}},
    "painel-de-metas": {"pacote": "metas", "lang": "py", "modulos": {
        "metas": {"criar_meta": [], "atualizar_progresso": ["criar_meta"], "concluir_meta": ["atualizar_progresso"], "metas_atrasadas": ["criar_meta"]},
        "relatorios": {"resumo_semanal": ["metas_atrasadas"], "grafico_de_progresso": ["atualizar_progresso"], "exportar": ["resumo_semanal", "grafico_de_progresso"]},
        "avisos": {"montar_aviso": ["metas_atrasadas"], "enviar_aviso": ["montar_aviso"], "agendar_avisos": ["enviar_aviso", "resumo_semanal"],
                   "silenciar_avisos": ["agendar_avisos"]},
        "equipes": {"criar_equipe": ["criar_usuario"], "convidar": ["criar_equipe", "enviar_aviso"], "metas_da_equipe": ["criar_equipe", "criar_meta"]},
        "usuarios": {"criar_usuario": [], "entrar": ["criar_usuario"], "sair": []}},
        "extra": {"README.md": "# Painel de metas\nProjeto inventado para a demonstração do Cérebro.\n", "pyproject.toml": '[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["E9", "F"]\n',
                  "docs/produto.md": "# Produto\nMetas pessoais com avisos semanais.\n"}},
}

# conversa fictícia de cada projeto: (descrição do subagente, tipo, modelo, há quantas horas terminou)
SUBAGENTES = {
    "loja-de-plantas": [("Buscar onde o carrinho calcula o total", "Explore", "claude-haiku-5-5", 70), ("Escrever os testes do carrinho", "general-purpose", "claude-sonnet-5-5", 52),
                        ("Revisão de segurança do fluxo de pagamento", "general-purpose", "claude-opus-5-5", 40), ("Documentação das rotas do servidor", "general-purpose", "claude-haiku-5-5", 29),
                        ("Corrigir bug no cupom de desconto", "general-purpose", "claude-sonnet-5-5", 20), ("Levantamento dos arquivos mais longos", "Explore", "claude-haiku-5-5", 9),
                        ("Implementar o cálculo de frete por região", "general-purpose", "claude-sonnet-5-5", 3)],
    "app-de-receitas": [("Listar as telas e o que cada uma faz", "Explore", "claude-haiku-5-5", 60), ("Implementar a busca por ingrediente", "general-purpose", "claude-sonnet-5-5", 33),
                        ("Resumo das ideias do arquivo docs/ideias.md", "general-purpose", "claude-haiku-5-5", 14), ("Arquitetura da sincronia offline", "general-purpose", "claude-opus-5-5", 6)],
    "painel-de-metas": [("Procurar onde os avisos são agendados", "Explore", "claude-haiku-5-5", 45), ("Escrever os testes das metas atrasadas", "general-purpose", "claude-sonnet-5-5", 25),
                        ("Corrigir o gráfico de progresso", "general-purpose", "claude-sonnet-5-5", 11)],
}
MEMORIAS = {
    "loja-de-plantas": [("tema-escuro", "feedback", "REGRA do dono: a loja usa tema escuro por padrão e nunca perde o carrinho ao recarregar."),
                        ("pagamentos-api", "project", "DECISÃO 12/10: pagamentos só pela API do provedor; nunca guardar número de cartão."),
                        ("frete-regioes", "project", "O frete é por região (Sul, Sudeste, resto); a tabela fica em loja/pagamentos.py."),
                        ("estoque-diario", "reference", "O estoque é carregado uma vez por dia às 6h.")],
    "app-de-receitas": [("offline-primeiro", "project", "DECISÃO 05/10: o app funciona offline e sincroniza quando voltar a rede."),
                        ("sem-login", "feedback", "REGRA: sem tela de login na primeira versão.")],
    "painel-de-metas": [("avisos-semanais", "project", "DECISÃO 20/10: um aviso por semana, nunca mais que isso."),
                        ("testes-antes", "feedback", "REGRA: rodar os testes antes de pedir revisão.")],
}
DEPARTAMENTOS = {
    "loja-de-plantas": [("Vitrine", "#29e0a0", ["loja/catalogo", "loja/avaliacoes", "loja/servidor"]), ("Compra", "#ffb340", ["loja/carrinho", "loja/pagamentos", "loja/pedidos"]),
                        ("Operação", "#8c8cff", ["loja/estoque", "loja/clientes", "loja/notificacoes"]), ("Testes", "#8f9bb0", ["testes/"])],
    "app-de-receitas": [("Receitas", "#29e0a0", ["src/receitas", "src/agenda"]), ("Lista", "#ffb340", ["src/lista"]), ("Tela", "#ff5fd2", ["src/interface"]),
                        ("Sincronia", "#3cc8f5", ["src/sincronia"])],
    "painel-de-metas": [("Metas", "#29e0a0", ["metas/metas", "metas/relatorios"]), ("Pessoas", "#8c8cff", ["metas/usuarios", "metas/equipes"]), ("Avisos", "#ffb340", ["metas/avisos"]),
                        ("Testes", "#8f9bb0", ["testes/"])],
}
DECISOES = {
    "loja-de-plantas": [("Delegar buscas e textos ao Haiku, código comum ao Sonnet e segurança ao Opus.", "regra", "dono"), ("Todo subagente passa pela conferência do gestor.", "regra", "dono"),
                        ("Cupons não acumulam.", "decisao", "dono"), ("Painel de custos por dia na aba Custos.", "ideia", "gestor")],
    "app-de-receitas": [("A primeira versão é só offline.", "decisao", "dono"), ("Testar a busca com 1000 receitas.", "ideia", "gestor")],
    "painel-de-metas": [("Avisos só por e-mail na primeira versão.", "decisao", "dono")],
}


# --------------------------------------------------------------------------------------------------------------------
# Geração do código dos projetos
# --------------------------------------------------------------------------------------------------------------------
def _codigo_py(pacote, modulo, funcoes, todos):
    onde = {f: m for m, fs in todos.items() for f in fs}
    linhas = [f'"""Módulo {modulo} do projeto de demonstração (inventado)."""']
    imports = sorted({(onde[c], c) for f, cs in funcoes.items() for c in cs if c in onde and onde[c] != modulo})
    for m, c in imports:
        linhas.append(f"from {pacote}.{m} import {c}")
    for i, (f, chamadas) in enumerate(funcoes.items()):
        linhas += ["", "", f"def {f}(x=0):", f'    """{f.replace("_", " ").capitalize()} (demonstração)."""']
        corpo = " + ".join(f"{c}(x)" for c in chamadas) or "0"
        linhas.append(f"    return {corpo} + {i + 1}")
    return "\n".join(linhas) + "\n"


def _codigo_js(modulo, funcoes, todos):
    onde = {f: m for m, fs in todos.items() for f in fs}
    linhas = [f"// Módulo {modulo} do projeto de demonstração (inventado)."]
    for m, c in sorted({(onde[c], c) for f, cs in funcoes.items() for c in cs if c in onde and onde[c] != modulo}):
        linhas.append(f"import {{ {c} }} from './{m}.js';")
    for i, (f, chamadas) in enumerate(funcoes.items()):
        corpo = " + ".join(f"{c}(x)" for c in chamadas) or "0"
        linhas += ["", f"/** {f} (demonstração). */", f"export function {f}(x = 0) {{", f"  return {corpo} + {i + 1};", "}"]
    return "\n".join(linhas) + "\n"


def _grafo(raiz, spec, commit):
    """graph.json no formato do Graphify, montado a partir do código inventado (sem precisar do Graphify instalado)."""
    nos, ligas, ids = [], [], {}
    arquivos = sorted(spec["modulos"])
    ext = "py" if spec["lang"] == "py" else "js"
    for com, modulo in enumerate(arquivos):
        for f in spec["modulos"][modulo]:
            nid = f"{modulo}_{f}"
            ids[f] = nid
    for com, modulo in enumerate(arquivos):
        fonte = f"{spec['pacote']}/{modulo}.{ext}"
        for i, (f, chamadas) in enumerate(spec["modulos"][modulo].items()):
            nos.append({"id": ids[f], "label": f + "()", "_callable": True, "_origin": "ast", "community": com, "community_name": modulo, "file_type": "code",
                        "norm_label": f + "()", "source_file": fonte, "source_location": f"L{3 + i * 5}"})
            for c in chamadas:
                if c in ids:
                    ligas.append({"source": ids[f], "target": ids[c], "relation": "calls", "_origin": "ast", "confidence": "EXTRACTED", "confidence_score": 1.0,
                                  "context": "call", "source_file": fonte, "source_location": f"L{4 + i * 5}", "weight": 1.0})
    return {"directed": True, "multigraph": False, "graph": {"schema_version": 1, "graphify_version": "demo"}, "nodes": nos, "links": ligas, "hyperedges": [],
            "built_at_commit": commit}


def _git(pasta, *args):
    return subprocess.run(["git", "-C", str(pasta), "-c", "user.name=Demonstração", "-c", "user.email=demo@example.com", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, timeout=60)


def _criar_projeto(pasta, nome, spec):
    pasta.mkdir(parents=True, exist_ok=True)
    pacote = pasta / spec["pacote"]
    pacote.mkdir(exist_ok=True)
    ext = "py" if spec["lang"] == "py" else "js"
    if spec["lang"] == "py":
        (pacote / "__init__.py").write_text('"""Pacote de demonstração."""\n', encoding="utf-8")
    for modulo, funcoes in spec["modulos"].items():
        txt = _codigo_py(spec["pacote"], modulo, funcoes, spec["modulos"]) if spec["lang"] == "py" else _codigo_js(modulo, funcoes, spec["modulos"])
        (pacote / f"{modulo}.{ext}").write_text(txt, encoding="utf-8")
    for rel, conteudo in spec["extra"].items():
        arq = pasta / rel
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(conteudo, encoding="utf-8")
    if spec["lang"] == "py":
        primeiro = next(iter(spec["modulos"]))
        f1 = next(iter(spec["modulos"][primeiro]))
        (pasta / "testes").mkdir(exist_ok=True)
        (pasta / "testes" / "__init__.py").write_text("", encoding="utf-8")
        (pasta / "testes" / f"test_{primeiro}.py").write_text(
            f"import unittest\n\nfrom {spec['pacote']}.{primeiro} import {f1}\n\n\nclass Teste(unittest.TestCase):\n    def test_{f1}(self):\n        self.assertEqual({f1}(0), 1)\n\n\n"
            "if __name__ == \"__main__\":\n    unittest.main()\n", encoding="utf-8")
    # um arquivo grande para a análise ter o que propor
    grande = pasta / spec["pacote"] / ("dados_gerados." + ext)
    grande.write_text("".join((f"X{i} = {i}\n" if ext == "py" else f"export const X{i} = {i};\n") for i in range(1650)), encoding="utf-8")
    if _git(pasta, "init", "-q").returncode != 0:
        return ""
    _git(pasta, "checkout", "-q", "-b", "main")
    _git(pasta, "add", "-A")
    _git(pasta, "commit", "-q", "-m", f"Começa o projeto {nome}")
    (pasta / "CHANGELOG.md").write_text("# Mudanças\n- primeira versão\n", encoding="utf-8")
    _git(pasta, "add", "-A")
    _git(pasta, "commit", "-q", "-m", "Adiciona o CHANGELOG")
    (pasta / spec["pacote"] / ("dados_gerados." + ext)).write_text("".join((f"X{i} = {i}\n" if ext == "py" else f"export const X{i} = {i};\n") for i in range(2100)), encoding="utf-8")
    _git(pasta, "add", "-A")
    _git(pasta, "commit", "-q", "-m", "Cresce a tabela de dados")
    commit = _git(pasta, "rev-parse", "HEAD").stdout.strip()
    saida = pasta / "graphify-out"
    saida.mkdir(exist_ok=True)
    (saida / "graph.json").write_text(json.dumps(_grafo(pasta, spec, commit), ensure_ascii=False), encoding="utf-8")
    return commit


# --------------------------------------------------------------------------------------------------------------------
# Conversas inventadas (formato dos transcritos do Claude Code)
# --------------------------------------------------------------------------------------------------------------------
def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def _ass(mid, sessao, cwd, modelo, t, entrada, saida, leitura, texto):
    uso = {"input_tokens": entrada, "output_tokens": saida, "cache_read_input_tokens": leitura, "cache_creation_input_tokens": 0,
           "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    return json.dumps({"type": "assistant", "timestamp": _iso(t), "cwd": cwd, "sessionId": sessao, "uuid": "u-" + mid,
                       "message": {"id": mid, "model": modelo, "role": "assistant", "content": [{"type": "text", "text": texto}], "usage": uso}}, ensure_ascii=False) + "\n"


def _usu(texto, sessao, cwd, t):
    return json.dumps({"type": "user", "timestamp": _iso(t), "cwd": cwd, "sessionId": sessao, "uuid": "x-" + str(int(t)),
                       "message": {"role": "user", "content": texto}}, ensure_ascii=False) + "\n"


def _uuid(semente):
    import hashlib
    h = hashlib.md5(semente.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _conversas(pasta_claude, caminho, nome, agora):
    gestora = _uuid("gestora-" + nome)
    cwd = str(caminho)
    arq = pasta_claude / f"{gestora}.jsonl"
    linhas = [json.dumps({"type": "user", "cwd": cwd})]
    t0 = agora - 4 * 86400
    linhas.append(_usu(f"Vamos cuidar do projeto {nome}: você é a gestora e delega o trabalho pesado.", gestora, cwd, t0))
    for d in range(5):
        t = t0 + d * 86400 + 3600
        linhas.append(_ass(f"g{d}", gestora, cwd, "claude-opus-5-5", t, 3000 + d * 400, 900 + d * 150, 60000 + d * 9000, "Plano do dia: delegar as buscas e conferir cada entrega."))
    arq.write_text("".join(linhas), encoding="utf-8")
    pasta_sub = pasta_claude / gestora / "subagents"
    pasta_sub.mkdir(parents=True, exist_ok=True)
    for i, (desc, tipo, modelo, horas) in enumerate(SUBAGENTES[nome]):
        sid = f"{i + 1:02d}{_uuid(desc)[:8]}"
        fim = agora - horas * 3600
        f = pasta_sub / f"agent-{sid}.jsonl"
        f.write_text(_usu(desc, gestora, cwd, fim - 600) + _ass(f"s{i}", gestora, cwd, modelo, fim - 300, 2200 + i * 300, 800 + i * 120, 30000 + i * 5000, f"Relatório: {desc}")
                     + _ass(f"s{i}b", gestora, cwd, modelo, fim, 1500, 600, 42000, "Terminei: arquivos tocados e como verifiquei."), encoding="utf-8")
        (pasta_sub / f"agent-{sid}.meta.json").write_text(json.dumps({"agentType": tipo, "description": desc, "spawnDepth": 1, "finished": True}, ensure_ascii=False), encoding="utf-8")
        os.utime(f, (fim, fim))
    return gestora


def _memoria(pasta_claude, nome):
    mem = pasta_claude / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    indice = []
    for ident, tipo, texto in MEMORIAS[nome]:
        (mem / f"{ident}.md").write_text(f"---\nname: {ident}\ndescription: {texto}\nmetadata:\n  type: {tipo}\n---\n\n{texto}\n", encoding="utf-8")
        indice.append(f"- [{ident}]({ident}.md) — {texto}")
    (mem / "MEMORY.md").write_text("\n".join(indice) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------------
# O que a versão 1.3 mostra: tarefas, orçamento, avisos de memória, capítulos da gestora, backup e explicações (tudo inventado)
# --------------------------------------------------------------------------------------------------------------------
TAREFAS = {
    "loja-de-plantas": [
        ("Revisar o cálculo de frete por região", "A tabela do Nordeste parece trocada com a do Norte.", "alta", "andamento",
         [{"tipo": "função", "nome": "calcular_frete", "arquivo": "loja/pagamentos.py"}]),
        ("Escrever testes para o cupom de desconto", "Cobrir cupom vencido e cupom em dobro.", "normal", "recebida", None),
        ("Melhorar a busca de plantas por luz", "Aceitar 'meia-sombra' como sinônimo de 'luz indireta'.", "normal", "conferir",
         [{"tipo": "função", "nome": "filtrar_por_luz", "arquivo": "loja/catalogo.py"}]),
        ("Trocar o texto do e-mail de pedido enviado", "Mais curto e com o código de rastreio no começo.", "baixa", "nova", None),
        ("Explicar no README como rodar a loja", "", "normal", "feita", None),
        ("Guardar o número do cartão para a próxima compra", "", "normal", "recusada", None),
    ],
    "app-de-receitas": [("Lista de compras funcionando sem internet", "Seguir a decisão de 05/10 (offline primeiro).", "alta", "nova", None)],
    "painel-de-metas": [("Não mandar avisos no fim de semana", "", "normal", "nova", None)],
}
LONGAS = [("historia-da-loja", "História da loja: começou como uma lista de plantas numa planilha, virou um site simples e ganhou "
                                "carrinho, pagamentos e estoque diário ao longo de três versões seguidas, com a mesma equipe pequena."),
          ("fornecedores", "Fornecedores atuais: viveiro do interior para as plantas grandes, um atacado da capital para vasos e "
                           "terra adubada, e uma cooperativa local para as mudas pequenas que saem mais na primavera.")]
NOTAS = {"recusada": "Contra a decisão de 12/10: nunca guardar número de cartão.", "feita": "Conferido e aprovado.",
         "conferir": "Pronto; falta o gestor conferir.", "andamento": "", "recebida": ""}
EXPLICACOES = {       # só alguns: o cartão "Explicar pontos do mapa com IA" mostra os já explicados e os que faltam
    "enviar_avaliacao": "Guarda a nota e o comentário que o cliente deu para uma planta.",
    "media_de_avaliacoes": "Calcula a nota média de cada planta a partir das avaliações.",
    "enviar_email": "Manda um e-mail para o cliente (pedido, entrega ou aviso).",
    "avisar_pedido_enviado": "Avisa o cliente por e-mail que o pedido saiu para entrega.",
    "rota_carrinho": "Recebe da página os pedidos de mexer no carrinho e devolve o carrinho atualizado.",
}


def _explicacoes_ia(slug, pasta, agora):
    """Algumas 'explicações automáticas (IA)' de exemplo no mapa da loja (escritas aqui, sem chamar IA nenhuma)."""
    from cerebro import explicar_ia
    cands, _ = explicar_ia.candidatos(slug, pasta)
    novos = {c["id"]: {"t": EXPLICACOES[c["nome"].rstrip("()")], "h": c["hash"], "em": agora - 3600}
             for c in cands if c.get("nome", "").rstrip("()") in EXPLICACOES and c.get("hash")}
    explicar_ia.guardar_no_cache(slug, novos)


def _transcrito_antigo(pasta_claude, cwd, nome, agora):
    """A transcrição 'anterior' da gestora (a de antes da última limpeza do contexto)."""
    sid = _uuid("gestora-antiga-" + nome)
    t0 = agora - 9 * 86400
    linhas = [json.dumps({"type": "user", "cwd": cwd}), _usu(f"Começo do projeto {nome}: monte o plano e delegue.", sid, cwd, t0)]
    for d in range(4):
        linhas.append(_ass(f"a{d}", sid, cwd, "claude-opus-5-5", t0 + d * 20000, 4000, 1200, 90000 + d * 15000,
                           "Feito: catálogo e carrinho. Falta: frete por região e testes do cupom."))
    arq = pasta_claude / f"{sid}.jsonl"
    arq.write_text("".join(linhas), encoding="utf-8")
    os.utime(arq, (t0 + 80000, t0 + 80000))
    return sid


def _extras_13(resultado, agora):
    from cerebro import armazem, backup, capitulos, config, gestora_troca, orcamento, tarefas_gestor
    for nome, lista in TAREFAS.items():
        slug = resultado[nome]["slug"]
        for i, (titulo, desc, prio, estado, pontos) in enumerate(lista):
            t = tarefas_gestor.criar(slug, titulo, desc, prio, pontos, agora=agora - (30 - i * 4) * 3600)
            caminho = {"recebida": ["recebida"], "andamento": ["recebida", "andamento"], "conferir": ["recebida", "andamento", "conferir"],
                       "feita": ["recebida", "andamento", "conferir", "feita"], "recusada": ["recusada"]}.get(estado, [])
            for j, e in enumerate(caminho):
                quem = "dono" if e in ("feita", "recusada") else "gestor"
                tarefas_gestor.mudar_estado(slug, t["id"], e, por=quem, nota=NOTAS.get(e, "") if j == len(caminho) - 1 else "",
                                            agora=agora - (20 - i * 3 - j) * 3600)
    # orçamento: geral e da loja (a loja fica perto do limite da semana, para o aviso aparecer)
    orcamento.definir("geral", dia=0.5, semana=1.2, mes=3, aviso_pct=80)
    loja = resultado["loja-de-plantas"]
    est = orcamento.estado(config.ler_config(), agora, so_slug=loja["slug"])
    gasto = max([float(b["periodos"]["semana"]["gasto"] or 0) for b in est["projetos"]] + [0.0])
    orcamento.definir(loja["slug"], semana=round(max(gasto / 0.86, 0.1), 2), mes=round(max(gasto * 3, 0.3), 2))
    # memória com dois avisos para conferir: uma nota velha que fala de "em andamento" e um caminho que não existe mais
    pc = config.CLAUDE / "projects" / loja["slug"] / "memory"
    velhas = [("migracao-estoque", "project", "A migração do estoque para o banco novo está em andamento; falta a tabela de fornecedores."),
              ("cupons-antigos", "reference", "As regras antigas de cupom ficam em loja/cupons_antigos.py (não mexer).")]
    with open(pc / "MEMORY.md", "a", encoding="utf-8") as f:
        for ident, tipo, texto in velhas:
            arq = pc / f"{ident}.md"
            arq.write_text(f"---\nname: {ident}\ndescription: {texto}\nmetadata:\n  type: {tipo}\n---\n\n{texto}\n", encoding="utf-8")
            os.utime(arq, (agora - 95 * 86400, agora - 95 * 86400))
            f.write(f"- [{ident}]({ident}.md) — {texto}\n")
        for ident, texto in LONGAS:            # ganchos longos: o "Propor compactação do índice" tem o que encurtar
            (pc / f"{ident}.md").write_text(f"---\nname: {ident}\ndescription: {texto[:80]}\nmetadata:\n  type: reference\n---\n\n{texto}\n",
                                            encoding="utf-8")
            f.write(f"- [{ident}]({ident}.md) — {texto}\n")
    # corrente da gestora: a transcrição antiga virou capítulo e a conversa continuou na mesma sessão (depois de limpar o contexto)
    pasta_claude = config.CLAUDE / "projects" / loja["slug"]
    antiga = _transcrito_antigo(pasta_claude, loja["pasta"], "loja-de-plantas", agora)
    config.atualizar_config(lambda c: c["gestoras"].__setitem__(loja["slug"], {"conversa": antiga, "nome": "Gestora principal"}))
    gestora_troca.corrente(loja["slug"], agora=agora - 9 * 86400)
    cap = capitulos.gravar(loja["slug"], antiga, agora=agora - 5 * 86400)
    config.atualizar_config(lambda c: c["gestoras"].__setitem__(loja["slug"], {"conversa": loja["gestora"], "nome": "Gestora principal"}))
    gestora_troca.corrente(loja["slug"], agora=agora - 5 * 86400 + 60)

    def ajustar(d):
        for e in d.get("elos", []):
            if e.get("conversa") == antiga:
                e.update(capitulo=cap.name if cap else "", como_saiu="contexto cheio: capítulo gravado e conversa limpa na mesma sessão",
                         quem="gestora")
            elif e.get("conversa") == loja["gestora"]:
                e.update(como="continuou na mesma sessão depois da limpeza", quem="gestora")
        return d
    armazem.atualizar_json(config.pasta_projeto(loja["slug"]) / "corrente.json", {}, ajustar)
    for horas in (60, 6):
        capitulos.gravar(loja["slug"], loja["gestora"], agora=agora - horas * 3600)
    # uma cópia de segurança da demonstração (na pasta backup/ dela)
    backup.fazer_backup()


# --------------------------------------------------------------------------------------------------------------------
def _limpar(destino):
    """Refaz a demonstração do zero: apaga o que tem DENTRO da pasta de destino, mas só se ela tiver a marca da demonstração, nunca se
    for a pasta do usuário (ou algo que a contenha) nem estiver dentro de ~/.claude."""
    import shutil
    d = Path(destino).resolve()
    home = Path.home().resolve()
    if d == home or d in home.parents or d == d.parent or (home / ".claude") in (d, *d.parents):
        raise SystemExit(f"Recusado: {d} não pode ser limpa.")
    if not (d / MARCA).is_file():
        return
    for filho in d.iterdir():
        if filho.name == MARCA:
            continue
        if filho.is_dir() and not filho.is_symlink():
            shutil.rmtree(filho, onerror=lambda f, c, _e: (os.chmod(c, 0o700), f(c)))
        else:
            filho.unlink()


def montar(destino):
    destino = Path(destino).resolve()
    if destino.exists() and any(destino.iterdir()):
        if not (destino / MARCA).is_file():
            raise SystemExit(f"A pasta {destino} não está vazia e não é uma pasta de demonstração (falta {MARCA}). Escolha outra.")
    destino.mkdir(parents=True, exist_ok=True)
    _limpar(destino)
    os.environ["CEREBRO_HOME"] = str(destino / "casa")
    os.environ["CEREBRO_CLAUDE"] = str(destino / "claude")
    os.environ["CEREBRO_BACKUP"] = str(destino / "backup")     # o backup da demonstração fica na própria pasta dela
    os.environ["CEREBRO_DEMO"] = "1"
    os.environ["CEREBRO_SEM_EFEITOS"] = "1"                    # nada de aviso na tela nem Agendador de verdade
    sys.path.insert(0, str(RAIZ))
    from cerebro import analise, config, decisoes, ferramentas, mapa_auto, propostas, revisoes, sugestoes
    (destino / MARCA).write_text("Pasta criada pelo demo/gerar_demo.py: dados inventados.\n", encoding="utf-8")
    agora = time.time()
    resultado = {}
    for nome, spec in PROJETOS.items():
        pasta = destino / "projetos" / nome
        commit = _criar_projeto(pasta, nome, spec)
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(pasta))
        pc = destino / "claude" / "projects" / slug
        pc.mkdir(parents=True, exist_ok=True)
        gestora = _conversas(pc, pasta, nome, agora)
        _memoria(pc, nome)
        resultado[nome] = {"slug": slug, "pasta": str(pasta), "gestora": gestora, "commit": commit}
    # tudo abaixo usa a configuração e os dados da própria demonstração (CEREBRO_HOME)
    from cerebro import projetos
    projetos.descobrir(forcar=True)
    cfg = config.ler_config()
    for nome, info in resultado.items():
        slug = info["slug"]
        config.atualizar_config(lambda c, s=slug, g=info["gestora"]: c["gestoras"].__setitem__(s, {"conversa": g, "nome": "Gestora principal"}))
        config.atualizar_config(lambda c, s=slug, n=nome: c["departamentos"].__setitem__(
            s, {"modo": "regras", "padrao": "Outros", "deptos": [{"nome": d, "cor": cor, "caminhos": cam} for d, cor, cam in DEPARTAMENTOS[n]]}))
        for texto, tipo, origem in DECISOES[nome]:
            decisoes.registrar(slug, texto, tipo, origem)
        for sug in sugestoes.detectar(info["pasta"]):
            if sug["id"] in ("unittest", "ruff") and nome != "app-de-receitas":
                sugestoes.aprovar(slug, info["pasta"], sug["id"])
        cfg = config.ler_config()
        for cmd in ferramentas.comandos_do_projeto(cfg, slug):
            if cmd["id"] == "ruff" and not ferramentas._modulo_python("ruff"):
                continue
            try:
                ferramentas.rodar(slug, info["pasta"], cfg, cmd["id"])
            except ValueError:
                continue
            for _ in range(240):
                time.sleep(0.25)
                if ferramentas.estado_execucoes(slug)["rodando"] is None:
                    break
        # fila "a conferir": confere alguns, deixa outros esperando
        cfg = config.ler_config()
        fila = revisoes.fila(slug, cfg)
        for i, it in enumerate(fila["pendentes"][:-2]):
            res = ("aprovado", "aprovado", "corrigido", "aprovado", "recusado")[i % 5]
            revisoes.conferir(slug, cfg, it["id"], res, ["Conferi o diff e rodei os testes.", "", "Faltava tratar o caso vazio; ajustei.", "", "Não servia; refiz."][i % 5], "dono")
        analise.executar(slug, cfg)
        aprovada = next((p for p in propostas.listar(slug) if p["estado"] == "nova"), None)
        if aprovada:
            propostas.decidir(slug, aprovada["id"], True, "Pode fazer.")
        if nome == "loja-de-plantas":
            _explicacoes_ia(slug, info["pasta"], agora)
        mapa_auto.gerar(info["pasta"])
    analise.executar(propostas.ESCOPO_CEREBRO, config.ler_config())
    _extras_13(resultado, agora)
    config.atualizar_config(lambda c: c.__setitem__("primeiro_uso_concluido", True))
    return {"destino": str(destino), "casa": str(destino / "casa"), "claude": str(destino / "claude"), "projetos": resultado}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gera os dados fictícios da demonstração")
    ap.add_argument("--destino", default=str(RAIZ / "demo" / "saida"), help="pasta onde criar a demonstração (padrão: demo/saida)")
    a = ap.parse_args(argv)
    r = montar(a.destino)
    print(json.dumps({k: v for k, v in r.items() if k != "projetos"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
