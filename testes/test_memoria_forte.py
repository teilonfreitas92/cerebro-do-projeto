"""Memória mais forte: edição segura (trava de caminho, prévia, cópia, conflito de versão), criar/arquivar, compactação do
MEMORY.md com verificador, decisões sem perder linha, avisos de memória velha/contraditória e o passa-bastão.
Tudo com amostras sintéticas na pasta temporária dos testes."""
import io
import json
import os
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from testes._ambiente import MundoFalso, linha_assistente, linha_usuario
from cerebro import (bastao, config, decisoes, indice, memoria, memoria_avisos, memoria_compactar, memoria_edicao, painel,
                     propostas)
import cerebro_cli

ME = memoria_edicao


def _arq(nome, tipo, desc, corpo):
    return f"---\nname: {nome}\ndescription: {desc}\nmetadata:\n  type: {tipo}\n---\n\n{corpo}\n"


class BaseMemoria(MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.mem = self.pasta_claude / "memory"
        self.mem.mkdir()
        amb.apagar(config.CASA / "copias")
        memoria_avisos._cache.clear()

    def tearDown(self):
        self.desmontar_mundo()

    def escrever(self, nome, texto):
        (self.mem / nome).write_text(texto, encoding="utf-8", newline="\n")
        return self.mem / nome

    def copias(self):
        raiz = config.CASA / "copias" / "memoria" / self.slug
        return sorted(raiz.iterdir()) if raiz.is_dir() else []


# ---------------------------------------------------------------------------------------------------------------
class TesteTravaDeCaminho(BaseMemoria):
    def test_recusa_tudo_fora_da_pasta_memory(self):
        for ruim in ("../x.md", "..\\x.md", "sub/x.md", "sub\\x.md", "x.txt", ".escondido.md", "C:/x.md", "/etc/x.md",
                     "..md", "", "a" * 200 + ".md", "x.md/../../y.md"):
            with self.assertRaises(ME.Recusado, msg=ruim):
                ME.caminho_seguro(self.slug, ruim)
        self.assertEqual(ME.caminho_seguro(self.slug, "ok_1.md"), self.mem / "ok_1.md")

    def test_slug_invalido_recusado(self):
        with self.assertRaises(ME.Recusado):
            ME.caminho_seguro("../fora", "x.md")

    def test_editar_e_arquivar_com_nome_malicioso_nao_tocam_nada(self):
        fora = self.pasta_claude / "fora.md"
        fora.write_text("intocado\n", encoding="utf-8")
        with self.assertRaises(ME.Recusado):
            ME.editar(self.slug, "../fora.md", "x", corpo="mudado", confirmar=True)
        with self.assertRaises(ME.Recusado):
            ME.arquivar(self.slug, "../fora.md", "x", confirmar=True)
        self.assertEqual(fora.read_text(encoding="utf-8"), "intocado\n")


class TesteEdicao(BaseMemoria):
    def setUp(self):
        super().setUp()
        self.f = self.escrever("feedback_botoes.md", _arq("Botões", "feedback", "Botões com 28 px", "Use 28 px.\n\n**Why:** padrão\n**How to apply:** sempre"))

    def test_previa_nao_grava_e_mostra_diferenca(self):
        a = ME.abrir(self.slug, "feedback_botoes.md")
        antes = self.f.read_bytes()
        r = ME.editar(self.slug, "feedback_botoes.md", a["versao"], corpo="Use 32 px.\n", confirmar=False)
        self.assertTrue(r["previa"])
        self.assertIn("-Use 28 px.", r["diff"])
        self.assertIn("+Use 32 px.", r["diff"])
        self.assertEqual(self.f.read_bytes(), antes)
        self.assertEqual(self.copias(), [])

    def test_copia_de_seguranca_antes_de_gravar(self):
        a = ME.abrir(self.slug, "feedback_botoes.md")
        antes = self.f.read_text(encoding="utf-8")
        r = ME.editar(self.slug, "feedback_botoes.md", a["versao"], descricao="Botões com 32 px", corpo="Use 32 px.\n", confirmar=True)
        self.assertTrue(r["gravado"])
        copias = self.copias()
        self.assertEqual(len(copias), 1)
        self.assertEqual((copias[0] / "feedback_botoes.md").read_text(encoding="utf-8"), antes)
        novo = self.f.read_text(encoding="utf-8")
        self.assertIn("description: Botões com 32 px", novo)
        self.assertIn("name: Botões", novo)
        self.assertIn("  type: feedback", novo)
        self.assertTrue(novo.rstrip().endswith("Use 32 px."))
        self.assertEqual(list(self.mem.glob("*.tmp")) + list(self.mem.glob(".*.tmp")), [])      # sem temporário largado

    def test_conflito_se_o_arquivo_mudou_depois_de_aberto(self):
        a = ME.abrir(self.slug, "feedback_botoes.md")
        time.sleep(0.01)
        self.f.write_text(_arq("Botões", "feedback", "mudou por fora", "o Claude Code escreveu"), encoding="utf-8")
        with self.assertRaises(ME.Conflito):
            ME.editar(self.slug, "feedback_botoes.md", a["versao"], corpo="minha versão", confirmar=True)
        self.assertIn("o Claude Code escreveu", self.f.read_text(encoding="utf-8"))
        with self.assertRaises(ME.Recusado):
            ME.editar(self.slug, "feedback_botoes.md", None, corpo="sem versão", confirmar=True)

    def test_preserva_crlf(self):
        self.f.write_bytes(_arq("B", "user", "d e s", "linha 1\nlinha 2").replace("\n", "\r\n").encode())
        a = ME.abrir(self.slug, "feedback_botoes.md")
        ME.editar(self.slug, "feedback_botoes.md", a["versao"], corpo="linha 1\nlinha 3\n", confirmar=True)
        b = self.f.read_bytes()
        self.assertIn(b"linha 3\r\n", b)
        self.assertNotIn(b"\n\n", b.replace(b"\r\n", b"X"))

    def test_segredo_nao_e_trocado_pela_mascara(self):
        f = self.escrever("project_api.md", _arq("API", "project", "chave da api", "senha=abc12345xyz e mais nada"))
        a = ME.abrir(self.slug, "project_api.md")
        self.assertTrue(a["tem_segredo"])
        self.assertNotIn("abc12345xyz", a["texto"])
        with self.assertRaises(ME.Recusado):           # mexer no corpo com segredo: recusa
            ME.editar(self.slug, "project_api.md", a["versao"], corpo=a["corpo"] + " extra", confirmar=True)
        # devolver o corpo mascarado SEM mexer e trocar só a descrição: o segredo original continua no arquivo
        ME.editar(self.slug, "project_api.md", a["versao"], descricao="descrição nova", corpo=a["corpo"], confirmar=True)
        self.assertIn("senha=abc12345xyz", f.read_text(encoding="utf-8"))
        self.assertIn("description: descrição nova", f.read_text(encoding="utf-8"))

    def test_descricao_com_dois_pontos_ganha_aspas(self):
        a = ME.abrir(self.slug, "feedback_botoes.md")
        ME.editar(self.slug, "feedback_botoes.md", a["versao"], descricao='REGRA: tamanho "28"', confirmar=True)
        campos, _ = memoria._cabecalho(self.f.read_text(encoding="utf-8"))
        self.assertEqual(campos["description"], 'REGRA: tamanho "28"')


class TesteCriarArquivar(BaseMemoria):
    def setUp(self):
        super().setUp()
        self.indice = self.escrever("MEMORY.md", "# Memória\n- [Outra](outra.md) — fica\n")
        self.escrever("outra.md", _arq("Outra", "user", "fica", "texto"))

    def test_criar_gera_arquivo_e_linha_no_indice(self):
        with self.assertRaises(ME.Recusado):        # feedback sem Why/How
            ME.criar(self.slug, "Testes antes", "Rodar testes antes do commit", "feedback", "Rode os testes.")
        p = ME.criar(self.slug, "Testes antes", "Rodar testes antes do commit", "feedback", "Rode os testes.", porque="quebrou 2x",
                     como_aplicar="antes de todo commit")
        self.assertTrue(p["previa"])
        self.assertFalse((self.mem / p["nome"]).exists())
        r = ME.criar(self.slug, "Testes antes", "Rodar testes antes do commit", "feedback", "Rode os testes.", porque="quebrou 2x",
                     como_aplicar="antes de todo commit", versao_indice=p["versao_indice"], confirmar=True)
        f = self.mem / r["nome"]
        self.assertEqual(r["nome"], "feedback_testes_antes.md")
        texto = f.read_text(encoding="utf-8")
        self.assertIn("**Why:** quebrou 2x", texto)
        self.assertIn("**How to apply:** antes de todo commit", texto)
        campos, _ = memoria._cabecalho(texto)
        self.assertEqual(campos["type"], "feedback")
        ind = self.indice.read_text(encoding="utf-8")
        self.assertIn("- [Testes antes](feedback_testes_antes.md) — Rodar testes antes do commit", ind)
        self.assertIn("- [Outra](outra.md) — fica", ind)
        self.assertEqual(len(self.copias()), 1)
        with self.assertRaises(ME.Recusado):        # mesmo nome de novo
            ME.criar(self.slug, "Testes antes", "x y z", "feedback", "abc", porque="p q r", como_aplicar="c a p")

    def test_criar_recusa_segredo_e_indice_que_mudou(self):
        with self.assertRaises(ME.Recusado):
            ME.criar(self.slug, "Chave", "a chave", "reference", "token=ghp_abcdefghijklmnopqrstuvwxyz123456")
        p = ME.criar(self.slug, "Nova", "descrição", "user", "texto")
        self.indice.write_text("# Memória\n- [Outra](outra.md) — fica\n- [X](x.md) — escrita do Claude\n", encoding="utf-8")
        with self.assertRaises(ME.Conflito):
            ME.criar(self.slug, "Nova", "descrição", "user", "texto", versao_indice=p["versao_indice"], confirmar=True)
        self.assertFalse((self.mem / "user_nova.md").exists())

    def test_arquivar_move_nunca_apaga_e_tira_a_linha(self):
        f = self.mem / "outra.md"
        bytes_antes = f.read_bytes()
        a = ME.abrir(self.slug, "outra.md")
        p = ME.arquivar(self.slug, "outra.md", a["versao"])
        self.assertTrue(p["previa"])
        self.assertTrue(f.exists())
        r = ME.arquivar(self.slug, "outra.md", a["versao"], p["versao_indice"], confirmar=True)
        self.assertFalse(f.exists())
        movido = self.mem / "_arquivo" / "outra.md"
        self.assertEqual(movido.read_bytes(), bytes_antes)          # mesmo conteúdo, só mudou de pasta
        self.assertNotIn("outra.md", self.indice.read_text(encoding="utf-8"))
        self.assertIn("# Memória", self.indice.read_text(encoding="utf-8"))
        copia = self.copias()[0]
        self.assertTrue((copia / "outra.md").is_file() and (copia / "MEMORY.md").is_file())
        self.assertTrue(r["arquivado_em"].endswith("outra.md"))
        self.assertEqual([x["arquivo"] for x in ME.arquivadas(self.slug)], ["outra.md"])
        # a lista da aba não mostra mais a arquivada (só a pasta principal)
        ids = [i["id"] for i in memoria.listar(self.slug, str(self.real))["itens"]]
        self.assertNotIn("mem/outra.md", ids)

    def test_arquivar_nunca_sobrescreve_o_que_ja_esta_no_arquivo(self):
        guardada = self.mem / "_arquivo"
        guardada.mkdir()
        (guardada / "outra.md").write_text("primeira arquivada\n", encoding="utf-8")
        (guardada / "outra-20260101-120000.md").write_text("segunda arquivada, mesmo segundo\n", encoding="utf-8")
        bytes_antes = (self.mem / "outra.md").read_bytes()
        a = ME.abrir(self.slug, "outra.md")
        with mock.patch.object(ME.time, "strftime", return_value="20260101-120000"):
            p = ME.arquivar(self.slug, "outra.md", a["versao"])
            r = ME.arquivar(self.slug, "outra.md", a["versao"], p["versao_indice"], confirmar=True)
        self.assertEqual((guardada / "outra.md").read_text(encoding="utf-8"), "primeira arquivada\n")
        self.assertEqual((guardada / "outra-20260101-120000.md").read_text(encoding="utf-8"), "segunda arquivada, mesmo segundo\n")
        destino = Path(r["arquivado_em"])
        self.assertNotIn(destino.name, ("outra.md", "outra-20260101-120000.md"))
        self.assertEqual(destino.read_bytes(), bytes_antes)
        self.assertIn(destino.name, p["diff"])                                    # a prévia mostra o nome que vai ser usado
        self.assertEqual(len(list(guardada.glob("*.md"))), 3)

    def test_arquivar_recusa_indice(self):
        a = ME.abrir(self.slug, "MEMORY.md")
        with self.assertRaises(ME.Recusado):
            ME.arquivar(self.slug, "MEMORY.md", a["versao"], confirmar=True)


# ---------------------------------------------------------------------------------------------------------------
INDICE_GRANDE = """# Índice da memória

## Antigo título de seção
- [Usuário dev](user_dev.md) — O dono não é programador; explique tudo em português simples, sem jargão, com exemplos curtos e diretos sempre que der.
- [REGRA backup](feedback_backup.md) — REGRA: NUNCA apagar a pasta .claude; backup obrigatório antes de qualquer remoção.
- [Botões](feedback_botoes.md) — Botões com 28 px de altura em todas as telas do painel, para ficar fácil de clicar no celular e no PC.
- [Botões](feedback_botoes.md) — duplicada com outro gancho longo que repete o mesmo assunto dos botões do painel inteiro.
- [Projeto mapa](project_mapa.md) — O mapa do código é gerado pelo Graphify; a página é refeita quando o graph.json muda e o vigia confere.
- [Docs API](reference_api.md) — It is forbidden to call the API without a key; you must use the sandbox.
- [Sumiu](sumiu.md) — este arquivo não existe mais na pasta, mas a linha continua aqui por engano há meses.
- [Curta](user_curta.md) — curta
"""


class TesteCompactacao(BaseMemoria):
    def setUp(self):
        super().setUp()
        self.escrever("MEMORY.md", INDICE_GRANDE)
        for nome, tipo in (("user_dev.md", "user"), ("feedback_backup.md", "feedback"), ("feedback_botoes.md", "feedback"),
                           ("project_mapa.md", "project"), ("reference_api.md", "reference"), ("user_curta.md", "user"),
                           ("orfa.md", "project")):
            self.escrever(nome, _arq(nome[:-3], tipo, "d e s", "corpo"))

    def test_proposta_mantem_regras_e_todos_os_arquivos(self):
        p = memoria_compactar.propor(self.slug)
        depois = p["depois"].split("\n")
        for linha in INDICE_GRANDE.split("\n"):
            if memoria_compactar.tem_regra(linha):
                self.assertIn(linha, depois, "linha com regra mudou: " + linha)
        for alvo in ("user_dev.md", "feedback_backup.md", "feedback_botoes.md", "project_mapa.md", "reference_api.md", "sumiu.md", "user_curta.md"):
            self.assertEqual(sum(1 for x in depois if f"]({alvo})" in x), 1, alvo)
        self.assertTrue(p["verificacao"]["ok"], p["verificacao"])
        self.assertLess(p["tokens_depois"], p["tokens_antes"])
        self.assertEqual(p["economia"], memoria.estimar_tokens(len(INDICE_GRANDE)) - memoria.estimar_tokens(len(p["depois"])))
        self.assertEqual(p["contagem"].get("duplicada"), 1)
        self.assertEqual(p["contagem"].get("encurtado", 0), 1)          # só o gancho longo sem palavra de regra (Botões)
        self.assertEqual([x["alvo"] for x in p["apontamentos"]["sem_arquivo"]], ["sumiu.md"])
        self.assertEqual(p["apontamentos"]["sem_linha"], ["orfa.md"])
        self.assertIn("## Antigo título de seção", p["depois"])           # títulos ficam (nada de reagrupar por tipo)
        self.assertNotIn("## Sobre você", p["depois"])
        ordem = ("user_dev.md", "feedback_backup.md", "feedback_botoes.md", "project_mapa.md", "reference_api.md",
                 "sumiu.md", "user_curta.md")
        posicoes = [p["depois"].index(f"]({a})") for a in ordem]
        self.assertEqual(posicoes, sorted(posicoes))                      # a ordem original não muda
        self.assertEqual((self.mem / "MEMORY.md").read_text(encoding="utf-8"), INDICE_GRANDE)                 # proposta não grava

    def test_palavras_de_regra_em_varias_formas(self):
        for t in ("REGRA x", "nunca faça", "Sempre teste", "é proibido", "obrigatória", "Não pode", "you MUST", "do not touch",
                  "never", "jamais", "obrigatorio", "não  deve"):
            self.assertTrue(memoria_compactar.tem_regra(t), t)
        for t in ("regrado", "sempreviva", "nunca1", "mustard", "texto comum sobre botões"):
            self.assertFalse(memoria_compactar.tem_regra(t), t)

    def test_verificador_pega_regra_perdida_e_arquivo_sem_linha(self):
        p = memoria_compactar.propor(self.slug)
        ruim = p["depois"].replace("REGRA: NUNCA apagar", "apagar")
        v = memoria_compactar.verificar(INDICE_GRANDE, ruim)
        self.assertFalse(v["ok"])
        nomes = {c["nome"]: c["ok"] for c in v["checagens"]}
        self.assertFalse(nomes["Linhas com palavra de regra ficaram inteiras"])
        self.assertFalse(nomes["Nenhuma palavra de regra sumiu"])
        sem_linha = "\n".join(x for x in p["depois"].split("\n") if "user_curta.md" not in x)
        v2 = memoria_compactar.verificar(INDICE_GRANDE, sem_linha)
        self.assertFalse({c["nome"]: c["ok"] for c in v2["checagens"]}["Todo arquivo de memória continua com a sua linha"])

    def test_aplicar_com_copia_e_conflito(self):
        p = memoria_compactar.propor(self.slug)
        r = memoria_compactar.aplicar(self.slug, p["versao"], confirmar=False)
        self.assertTrue(r["previa"])
        self.assertEqual((self.mem / "MEMORY.md").read_text(encoding="utf-8"), INDICE_GRANDE)
        r = memoria_compactar.aplicar(self.slug, p["versao"], confirmar=True)
        self.assertTrue(r["gravado"])
        self.assertEqual((self.mem / "MEMORY.md").read_text(encoding="utf-8"), p["depois"])
        self.assertEqual((self.copias()[0] / "MEMORY.md").read_text(encoding="utf-8"), INDICE_GRANDE)
        with self.assertRaises(ME.Conflito):                          # versão velha: recusa
            memoria_compactar.aplicar(self.slug, p["versao"], confirmar=True)
        # aplicar de novo sobre o já compactado: nada (ou quase nada) a fazer, e nunca quebra as garantias
        p2 = memoria_compactar.propor(self.slug)
        self.assertTrue(p2["verificacao"]["ok"])

    def test_ia_desligada(self):
        self.assertFalse(memoria_compactar.COMPACTAR_COM_IA_LIGADO)
        self.assertIsNone(memoria_compactar.compactar_com_ia(INDICE_GRANDE, self.mem))


# Caso da revisão (prova3): regra sem palavra da lista antiga, subitem recuado e título de seção.
REGRA_SEM_PALAVRA = ("- [Apagar](feedback_apagar.md) — Não apague ~/.claude nem rode rmtree fora da pasta de testes; antes de remover "
                     "qualquer coisa pergunte ao dono e mostre o caminho")
SUBITEM = "  - Obs: vale também para os scripts de limpeza do CI e do desinstalador"
INDICE_REVISAO = ("# Memória\n\n## Backend\n" + REGRA_SEM_PALAVRA + "\n" + SUBITEM + "\n- [X](project_x.md) — projeto x\n\n"
                  "## Frontend\n- [Cores](project_cores.md) — A paleta do painel usa azul escuro no fundo, cinza claro nos cartões e "
                  "verde para os avisos de tudo certo na tela.\n")


class TesteCompactacaoConservadora(BaseMemoria):
    def setUp(self):
        super().setUp()
        for nome, tipo in (("feedback_apagar.md", "feedback"), ("project_x.md", "project"), ("project_cores.md", "project")):
            self.escrever(nome, _arq(nome[:-3], tipo, "d e s", "corpo"))

    def test_regra_subitem_e_titulo_ficam_no_lugar(self):
        novo, mud, _ = memoria_compactar.propor_texto(INDICE_REVISAO, self.mem)
        linhas = novo.split("\n")
        self.assertIn(REGRA_SEM_PALAVRA, linhas)                                       # "Não", "antes de", "pergunte": inteira
        self.assertEqual(linhas[linhas.index(REGRA_SEM_PALAVRA) + 1], SUBITEM)       # subitem logo abaixo da entrada
        self.assertIn("## Backend", linhas)
        self.assertIn("## Frontend", linhas)
        self.assertLess(linhas.index("## Backend"), linhas.index(REGRA_SEM_PALAVRA))
        self.assertLess(linhas.index("## Frontend"), next(i for i, x in enumerate(linhas) if "](project_cores.md)" in x))
        self.assertGreater(linhas.index("## Frontend"), next(i for i, x in enumerate(linhas) if "](project_x.md)" in x))
        self.assertEqual([x["tipo"] for x in mud], ["encurtado"])                       # só o gancho longo sem regra
        self.assertTrue(memoria_compactar.verificar(INDICE_REVISAO, novo)["ok"])

    def test_palavras_de_negacao_restricao_e_condicao_protegem(self):
        for p in ("não", "nao", "nunca", "never", "don't", "avoid", "evite", "só", "somente", "apenas", "sem", "pergunte",
                  "antes de", "depois de", "exceto", "salvo", "proibido", "obrigatório", "sempre", "regra", "decisão"):
            for forma in (p, p.upper(), p.capitalize()):
                self.assertTrue(memoria_compactar.tem_regra(f"faça isso {forma} aquilo"), forma)

    def _checagem(self, depois, nome, antes=INDICE_REVISAO):
        v = memoria_compactar.verificar(antes, depois)
        self.assertFalse(v["ok"], depois)
        self.assertFalse({c["nome"]: c["ok"] for c in v["checagens"]}[nome], depois)

    def test_verificador_pega_subitem_separado(self):
        ruim = INDICE_REVISAO.replace(SUBITEM + "\n", "").replace("# Memória\n", "# Memória\n" + SUBITEM + "\n")
        self._checagem(ruim, "Subitens continuam inteiros, logo abaixo da sua entrada")

    def test_verificador_pega_titulo_sumido(self):
        self._checagem(INDICE_REVISAO.replace("## Backend\n", ""), "Os títulos ficaram todos, na mesma ordem")

    def test_verificador_pega_entrada_que_trocou_de_secao(self):
        linha_x = "- [X](project_x.md) — projeto x\n"
        ruim = INDICE_REVISAO.replace(linha_x, "").replace("## Frontend\n", "## Frontend\n" + linha_x)
        self._checagem(ruim, "A ordem das entradas não mudou (nenhuma trocou de seção)")

    def test_verificador_pega_gancho_reescrito(self):
        ruim = INDICE_REVISAO.replace("projeto x", "outra coisa")
        self._checagem(ruim, "Linhas encurtadas só perderam o fim do gancho")

    def test_duplicada_com_subitem_nao_sai(self):
        antes = ("- [X](project_x.md) — projeto x\n- [X](project_x.md) — outra linha do x\n  - detalhe que depende desta linha\n")
        novo, mud, _ = memoria_compactar.propor_texto(antes, self.mem)
        self.assertIn("- [X](project_x.md) — outra linha do x\n  - detalhe que depende desta linha\n", novo)
        self.assertTrue(memoria_compactar.verificar(antes, novo)["ok"])


# ---------------------------------------------------------------------------------------------------------------
class TesteDecisoes(BaseMemoria):
    def _linhas(self):
        return (config.pasta_projeto(self.slug) / "decisoes.jsonl").read_bytes().split(b"\n")

    def test_arquivar_e_editar_nunca_apagam_linha(self):
        a = decisoes.registrar(self.slug, "Botões com 28 px", "decisao", "dono")
        b = decisoes.registrar(self.slug, "Nunca mexer na pasta financeiro", "regra", "gestor")
        antes = self._linhas()
        prev = decisoes.arquivar(self.slug, a["id"])
        self.assertTrue(prev["previa"])
        self.assertEqual(self._linhas(), antes)
        decisoes.arquivar(self.slug, a["id"], "não vale mais", confirmar=True)
        r = decisoes.substituir(self.slug, b["id"], "Nunca mexer nas pastas financeiro e fiscal", confirmar=True)
        depois = self._linhas()
        self.assertEqual(depois[:len(antes) - 1], antes[:-1])            # as linhas antigas continuam iguais, byte a byte
        self.assertGreater(len(depois), len(antes))
        lista = {d["id"]: d for d in decisoes.listar(self.slug)}
        self.assertEqual(lista[a["id"]]["estado"], "arquivada")
        self.assertEqual(lista[b["id"]]["estado"], "substituida")
        self.assertEqual(lista[b["id"]]["substituida_por"], r["nova"]["id"])
        self.assertEqual(lista[r["nova"]["id"]]["substitui"], b["id"])
        self.assertEqual([d["id"] for d in decisoes.listar(self.slug, so_ativas=True)], [r["nova"]["id"]])
        self.assertTrue((config.CASA / "copias" / "decisoes" / self.slug).is_dir())
        with self.assertRaises(ValueError):
            decisoes.arquivar(self.slug, a["id"], confirmar=True)        # já arquivada
        with self.assertRaises(ValueError):
            decisoes.arquivar(self.slug, "nao-existe", confirmar=True)


# ---------------------------------------------------------------------------------------------------------------
class TesteAvisos(BaseMemoria):
    def setUp(self):
        super().setUp()
        (self.real / "cerebro").mkdir()
        (self.real / "cerebro" / "app.py").write_text("def funcao_existente():\n    return 1\n", encoding="utf-8")
        self.escrever("project_codigo.md", _arq("Código", "project", "onde fica", "O servidor está em `cerebro/app.py` e usa `funcao_existente()`.\n"
                                                "O antigo `cerebro/velho.py` com `funcao_sumida()` foi trocado. Ver [[inexistente]] e [[Código]]."))

    def _avisos(self, **kw):
        return memoria_avisos.avisos(self.slug, str(self.real), usar_cache=False, **kw)["avisos"]

    def test_cita_arquivo_funcao_e_link_que_nao_existem(self):
        av = self._avisos()
        caminhos = " ".join(a["motivo"] for a in av if a["tipo"] == "caminho")
        self.assertIn("cerebro/velho.py", caminhos)
        self.assertNotIn("cerebro/app.py", caminhos)
        self.assertIn("funcao_sumida()", caminhos)
        self.assertNotIn("funcao_existente", caminhos)
        links = [a for a in av if a["tipo"] == "link"]
        self.assertEqual(len(links), 1)
        self.assertIn("[[inexistente]]", links[0]["motivo"])
        # modo rápido (fila): sem varrer o projeto, só os links
        self.assertFalse([a for a in self._avisos(rapido=True) if a["tipo"] == "caminho"])

    def test_memoria_velha_que_fala_de_estado(self):
        velha = self.escrever("project_migracao.md", _arq("Migração", "project", "estado", "A migração está em andamento, falta o banco."))
        t = time.time() - 60 * 86400
        os.utime(velha, (t, t))
        self.escrever("project_nova.md", _arq("Nova", "project", "estado", "Tarefa em andamento hoje."))
        self.escrever("project_mod.md", "---\nname: Mod\ndescription: x\nmodified: 2020-01-02\nmetadata:\n  type: project\n---\nStatus atual: pendente.\n")
        velhas = {a["arquivos"][0] for a in self._avisos() if a["tipo"] == "velha"}
        self.assertEqual(velhas, {"mem/project_migracao.md", "mem/project_mod.md"})

    def test_pares_contraditorios(self):
        self.escrever("feedback_tema_a.md", _arq("Tema A", "feedback", "tema", "O modo escuro do painel fica ligado por padrão na tela inicial."))
        self.escrever("feedback_tema_b.md", _arq("Tema B", "feedback", "tema", "O modo escuro do painel fica desligado por padrão na tela inicial."))
        self.escrever("feedback_bot_a.md", _arq("Bot A", "feedback", "botões", "Botões do painel com altura 28 px."))
        self.escrever("feedback_bot_b.md", _arq("Bot B", "feedback", "botões", "Botões do painel com altura 32 px."))
        self.escrever("user_gato.md", _arq("Gato", "user", "gato", "O gato do vizinho se chama Bolinha e está desligado do mundo."))
        decisoes.registrar(self.slug, "Usar 4 espaços de recuo nos arquivos Python do projeto", "decisao", "dono")
        self.escrever("feedback_recuo.md", _arq("Recuo", "feedback", "recuo", "Não usar 4 espaços de recuo nos arquivos Python do projeto; prefira tabulação."))
        contra = [a for a in self._avisos() if a["tipo"] == "contradicao"]
        pares = [set(a["arquivos"]) for a in contra]
        self.assertIn({"mem/feedback_tema_a.md", "mem/feedback_tema_b.md"}, pares)
        self.assertIn({"mem/feedback_bot_a.md", "mem/feedback_bot_b.md"}, pares)
        self.assertTrue(any("mem/feedback_recuo.md" in p and any(x.startswith("dec/") for x in p) for p in pares))
        self.assertFalse(any("mem/user_gato.md" in p for p in pares))
        motivo = next(a["motivo"] for a in contra if set(a["arquivos"]) == {"mem/feedback_bot_a.md", "mem/feedback_bot_b.md"})
        self.assertIn("28", motivo)
        self.assertIn("32", motivo)

    def test_fila_mostra_e_nada_e_mudado(self):
        antes = {f.name: f.read_bytes() for f in self.mem.iterdir()}
        p = {"slug": self.slug, "nome": "Falso", "caminho": str(self.real)}
        itens = memoria_avisos.itens_fila(p, {})
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["aba"], "memoria")
        self.assertEqual({f.name: f.read_bytes() for f in self.mem.iterdir()}, antes)
        titulos = [i["titulo"] for i in painel.fila(config.ler_config())]
        self.assertIn("Falso: memória a conferir", titulos)


# ---------------------------------------------------------------------------------------------------------------
class TesteBastao(BaseMemoria):
    SID = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        super().setUp()
        app = str(self.real / "app.py")
        linhas = [json.dumps({"type": "user", "cwd": str(self.real)}) + "\n",
                  linha_usuario("Quero um painel novo com login; senha=abc12345xyz é a do teste"),
                  linha_assistente("a1", leitura=5000, conteudo=[{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": app}}]),
                  linha_usuario("Agora ajuste os botões"),
                  linha_assistente("a2", leitura=8000, conteudo=[{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": app}},
                                                                 {"type": "tool_use", "id": "t3", "name": "Write",
                                                                  "input": {"file_path": str(self.mem / "feedback_nova.md")}}]),
                  linha_usuario("Por fim, rode os testes"),
                  linha_assistente("a3", ts="2026-10-28T13:00:00.000Z", entrada=50, leitura=125_000, escrita=1000)]
        (self.pasta_claude / f"{self.SID}.jsonl").write_text("".join(linhas), encoding="utf-8")
        self.escrever("feedback_nova.md", f"---\nname: Nova\ndescription: botões maiores\noriginSessionId: {self.SID}\nmetadata:\n  type: feedback\n---\nx\n")
        decisoes.registrar(self.slug, "Botões com 28 px", "decisao", "dono")
        propostas.sincronizar(self.slug, [propostas.proposta("teste", "k1", "Tarefa de teste", "motivo")])
        pid = propostas.listar(self.slug)[0]["id"]
        propostas.decidir(self.slug, pid, True)
        indice.indexar_projeto(self.slug)

    def test_contexto_do_ultimo_turno(self):
        ind = indice.indice_se_existe(self.slug, f"{self.SID}.jsonl")
        self.assertEqual(bastao.contexto_do_indice(ind), 50 + 125_000 + 1000)
        e = bastao.estado_sessao(ind, {})
        self.assertTrue(e["longa"])
        self.assertEqual(e["limite_tokens"], 120_000)
        self.assertFalse(bastao.estado_sessao(ind, {"bastao": {"limite_pct": 90}})["longa"])
        # mesmo horário em todos os turnos (relógio grosso): vale o último gravado
        msgs = {"a": [100, "m", 1, 0, 10, 0, 0], "b": [100, "m", 1, 0, 500, 0, 0], "c": [99, "m", 1, 0, 9000, 0, 0]}
        self.assertEqual(bastao.contexto_do_indice({"msgs": msgs}), 501)

    def test_detecta_so_a_sessao_longa_e_avisa_na_fila(self):
        longas = bastao.sessoes_longas(self.slug, {})
        self.assertEqual([s["sessao"] for s in longas], [self.SID])          # a gestora (pequena) não entra
        titulos = [i["titulo"] for i in painel.fila(config.ler_config())]
        self.assertIn("Falso: conversa longa — passar o bastão", titulos)

    def test_resumo_publico_mascarado_e_gravado(self):
        texto = bastao.resumo(self.slug, self.SID)
        self.assertIn("Quero um painel novo com login", texto)                # objetivo inicial
        self.assertIn("Por fim, rode os testes", texto)                       # últimos pedidos
        self.assertIn("app.py (2 edições)", texto)                            # arquivos mais editados (relativo ao projeto)
        self.assertIn("Botões com 28 px", texto)                              # decisões
        self.assertIn("Tarefa de teste", texto)                               # tarefas abertas
        self.assertIn("feedback_nova.md", texto)                              # memórias criadas na sessão
        self.assertNotIn("abc12345xyz", texto)                                # mascarado
        arq = config.pasta_projeto(self.slug) / "bastao" / f"{self.SID}.md"
        self.assertEqual(arq.read_text(encoding="utf-8"), texto)
        with self.assertRaises(ValueError):
            bastao.resumo(self.slug, "../fora")

    def test_cli_bastao(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(cerebro_cli.main(["bastao", self.slug, self.SID[:8]]), 0)
        self.assertIn("Passa-bastão", out.getvalue())


class TesteCliMemoria(BaseMemoria):
    def test_compactar_so_grava_com_confirmar(self):
        self.escrever("MEMORY.md", INDICE_GRANDE)
        for nome in ("user_dev.md", "feedback_backup.md", "feedback_botoes.md", "project_mapa.md", "reference_api.md", "user_curta.md"):
            self.escrever(nome, _arq(nome[:-3], nome.split("_")[0], "d e s", "corpo"))
        for args in (["memoria", self.slug, "--compactar"], ["memoria", self.slug, "--compactar", "--aplicar"]):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cerebro_cli.main(args), 0)
            self.assertIn("Verificador", out.getvalue())
            self.assertEqual((self.mem / "MEMORY.md").read_text(encoding="utf-8"), INDICE_GRANDE)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cerebro_cli.main(["memoria", self.slug, "--compactar", "--aplicar", "--confirmar"]), 0)
        self.assertNotEqual((self.mem / "MEMORY.md").read_text(encoding="utf-8"), INDICE_GRANDE)
        self.assertEqual(len(self.copias()), 1)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cerebro_cli.main(["memoria", self.slug, "--avisos"]), 0)
        self.assertIn("aviso(s)", out.getvalue())


# ---------------------------------------------------------------------------------------------------------------
from testes.test_servidor import Base as BaseServidor  # noqa: E402


class TesteRotasMemoria(BaseServidor):
    async def test_editar_pela_rota_previa_confirmar_e_trava(self):
        await self.entrar()
        u = f"/api/p/{self.slug}"
        mem = config.PROJETOS_CLAUDE / self.slug / "memory"
        a = await (await self.http.get(f"{self.base}{u}/memoria/editar?nome=regra.md")).json()
        self.assertNotIn("abc12345xyz", json.dumps(a))                     # mascarado na tela
        r = await self.post(f"{u}/memoria/editar", {"nome": "regra.md", "versao": a["versao"], "descricao": "REGRA 30/10: sempre testar tudo"})
        d = await r.json()
        self.assertEqual(r.status, 200)
        self.assertTrue(d["previa"])
        self.assertIn("+description:", d["diff"])
        self.assertIn("29/10", (mem / "regra.md").read_text(encoding="utf-8"))
        r = await self.http.post(self.base + f"{u}/memoria/editar", data=json.dumps({"nome": "regra.md", "versao": a["versao"], "confirmar": True}),
                                 headers={"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)                                    # sem Origin: recusado
        r = await self.post(f"{u}/memoria/editar", {"nome": "regra.md", "versao": a["versao"], "descricao": "REGRA 30/10: sempre testar tudo", "confirmar": True})
        self.assertEqual(r.status, 200)
        texto = (mem / "regra.md").read_text(encoding="utf-8")
        self.assertIn("30/10", texto)
        self.assertIn("senha=abc12345xyz", texto)                          # o segredo do corpo ficou intacto
        r = await self.post(f"{u}/memoria/editar", {"nome": "regra.md", "versao": a["versao"], "descricao": "outra", "confirmar": True})
        self.assertEqual(r.status, 409)                                    # versão velha
        r = await self.post(f"{u}/memoria/editar", {"nome": "../x.md", "versao": "x", "corpo": "y", "confirmar": True})
        self.assertEqual(r.status, 400)
        r = await self.post(f"{u}/memoria/arquivar", {"nome": "..\\..\\x.md", "versao": "x", "confirmar": True})
        self.assertEqual(r.status, 400)

    async def test_compactar_avisos_decisoes_e_sessoes(self):
        await self.entrar()
        u = f"/api/p/{self.slug}"
        p = await (await self.http.get(f"{self.base}{u}/memoria/compactar")).json()
        self.assertIn("verificacao", p)
        self.assertIn("tokens_antes", p)
        av = await self.http.get(f"{self.base}{u}/memoria/avisos")
        self.assertEqual(av.status, 200)
        await self.post(f"{u}/decisoes", {"texto": "Botões com 28 px", "tipo": "decisao", "origem": "dono"})
        did = (await (await self.http.get(f"{self.base}{u}/decisoes")).json())["registradas"][0]["id"]
        r = await (await self.post(f"{u}/decisoes/{did}", {"acao": "editar", "texto": "Botões com 32 px"})).json()
        self.assertTrue(r["previa"])
        r = await (await self.post(f"{u}/decisoes/{did}", {"acao": "editar", "texto": "Botões com 32 px", "confirmar": True})).json()
        self.assertFalse(r["previa"])
        lista = (await (await self.http.get(f"{self.base}{u}/decisoes")).json())["registradas"]
        self.assertEqual(sorted(x["estado"] for x in lista), ["ativa", "substituida"])
        r = await self.post(f"{u}/decisoes/{did}", {"acao": "apagar", "confirmar": True})
        self.assertEqual(r.status, 400)
        s = await (await self.http.get(f"{self.base}{u}/sessoes")).json()
        self.assertTrue(all("bastao" in x for x in s["sessoes"]))
        b = await (await self.http.get(f"{self.base}{u}/bastao")).json()
        self.assertEqual(b["longas"], [])
        r = await self.post(f"{u}/bastao", {"sessao": "sessA"})
        self.assertEqual(r.status, 200)
        self.assertIn("Faça o teste", (await r.json())["texto"])
        r = await self.post(f"{u}/bastao", {"sessao": "../../x"})
        self.assertEqual(r.status, 400)
        r = await self.http.get(f"{self.base}/static/memoria.js")
        self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()


class TesteJanelaReal(unittest.TestCase):
    """Modelo com janela de 1 milhão: 527 mil tokens não é "263% da janela" (visto no painel em 29/10/2026)."""
    def test_janela_grande_quando_o_contexto_passa_da_configurada(self):
        from cerebro import bastao
        self.assertEqual(bastao.janela_efetiva(150_000, 200_000), 200_000)
        self.assertEqual(bastao.janela_efetiva(527_000, 200_000), 1_000_000)

    def test_estado_sessao_nunca_passa_de_100_por_cento_ate_1_milhao(self):
        from cerebro import bastao
        ind = {"msgs": {"a": [1, None, 500_000, 0, 27_000, 0, 0]}}
        e = bastao.estado_sessao(ind, {})
        self.assertEqual(e["janela"], 1_000_000)
        self.assertLess(e["pct"], 100)
        self.assertFalse(e["longa"])                   # 52,7% de 1 milhão: abaixo do limite de 60%
