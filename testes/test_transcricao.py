import json
import tempfile
import unittest
from pathlib import Path

from cerebro import transcricao
from testes._ambiente import linha_assistente, linha_usuario


def escrever(pasta, nome, *linhas, bytes_extra=b""):
    caminho = Path(pasta) / nome
    caminho.write_bytes("".join(linhas).encode("utf-8") + bytes_extra)
    return caminho


class TesteUsage(unittest.TestCase):
    def test_extrai_campos(self):
        u = transcricao.extrair_usage({"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                                       "cache_creation_input_tokens": 10,
                                       "cache_creation": {"ephemeral_5m_input_tokens": 4, "ephemeral_1h_input_tokens": 6}})
        self.assertEqual(u, (1, 2, 3, 4, 6))

    def test_sem_detalhe_de_cache_tudo_vai_para_5_minutos(self):
        u = transcricao.extrair_usage({"input_tokens": 0, "output_tokens": 1, "cache_creation_input_tokens": 50})
        self.assertEqual(u, (0, 1, 0, 50, 0))

    def test_detalhe_incoerente_nao_cria_tokens(self):
        u = transcricao.extrair_usage({"cache_creation_input_tokens": 10, "cache_creation": {"ephemeral_5m_input_tokens": 50, "ephemeral_1h_input_tokens": 50}})
        self.assertEqual(u[3] + u[4], 10)

    def test_lixo_e_zeros(self):
        self.assertIsNone(transcricao.extrair_usage(None))
        self.assertIsNone(transcricao.extrair_usage({"input_tokens": 0}))
        self.assertEqual(transcricao.extrair_usage({"input_tokens": "x", "output_tokens": 5}), (0, 5, 0, 0, 0))

    def test_epoch(self):
        self.assertAlmostEqual(transcricao.para_epoch("2026-10-28T12:00:00.000Z"), 1793188800.0, delta=1)
        self.assertIsNone(transcricao.para_epoch("ontem"))
        self.assertIsNone(transcricao.para_epoch(None))


class TesteIndice(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="cerebro_jsonl_")

    def test_soma_e_deduplica_mensagens_repetidas(self):
        # a mesma mensagem (mesmo id) aparece em duas linhas, um bloco por linha, com o mesmo usage
        arq = escrever(self.pasta, "a.jsonl",
                       linha_usuario("Faça o painel do Cérebro"),
                       linha_assistente("m1", saida=20, conteudo=[{"type": "text", "text": "ok"}]),
                       linha_assistente("m1", saida=20, conteudo=[{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]),
                       linha_assistente("m2", modelo="claude-sonnet-5-5", entrada=5, saida=7, leitura=100, escrita=40, w1=30))
        ind, mudou = transcricao.atualizar_indice(arq)
        self.assertTrue(mudou)
        self.assertEqual(len(ind["msgs"]), 2)
        self.assertEqual(ind["msgs"]["m1"][2:], [10, 20, 1000, 0, 0])
        self.assertEqual(ind["msgs"]["m2"][2:], [5, 7, 100, 10, 30])
        self.assertEqual(ind["tools"], {"Bash": 1})
        self.assertEqual(ind["modelos"], {"claude-opus-5-5": 1, "claude-sonnet-5-5": 1})
        self.assertEqual(ind["primeira"], "Faça o painel do Cérebro")
        self.assertEqual(ind["branch"], "main")

    def test_linhas_desconhecidas_e_quebradas_sao_ignoradas(self):
        arq = escrever(self.pasta, "b.jsonl", "não é json nenhum\n", '{"type":"coisa-nova","x":1}\n', '{"type":"assistant"}\n',
                       '{"type":"assistant","message":"texto"}\n', "[1,2,3]\n", linha_assistente("ok1"))
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertEqual(list(ind["msgs"]), ["ok1"])

    def test_linha_incompleta_fica_para_depois(self):
        completa = linha_assistente("m1")
        parcial = linha_assistente("m2")[:80]
        arq = escrever(self.pasta, "c.jsonl", completa, bytes_extra=parcial.encode())
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertEqual(list(ind["msgs"]), ["m1"])
        self.assertEqual(ind["tam"], len(completa.encode()))
        # o resto da linha chega: agora entra
        with open(arq, "ab") as f:
            f.write(linha_assistente("m2").encode()[80:])
        ind, mudou = transcricao.atualizar_indice(arq, ind)
        self.assertTrue(mudou)
        self.assertEqual(sorted(ind["msgs"]), ["m1", "m2"])

    def test_leitura_incremental_so_le_o_novo(self):
        arq = escrever(self.pasta, "d.jsonl", linha_assistente("m1"))
        ind, _ = transcricao.atualizar_indice(arq)
        pos = ind["tam"]
        ind2, mudou = transcricao.atualizar_indice(arq, ind)
        self.assertFalse(mudou)
        with open(arq, "ab") as f:
            f.write(linha_assistente("m2").encode())
        ind3, mudou = transcricao.atualizar_indice(arq, ind2)
        self.assertTrue(mudou)
        self.assertGreater(ind3["tam"], pos)
        self.assertEqual(len(ind3["msgs"]), 2)

    def test_arquivo_reescrito_menor_recomeca(self):
        arq = escrever(self.pasta, "e.jsonl", linha_assistente("m1"), linha_assistente("m2"))
        ind, _ = transcricao.atualizar_indice(arq)
        escrever(self.pasta, "e.jsonl", linha_assistente("novo"))
        ind, _ = transcricao.atualizar_indice(arq, ind)
        self.assertEqual(list(ind["msgs"]), ["novo"])

    def test_titulos(self):
        arq = escrever(self.pasta, "f.jsonl", '{"type":"custom-title","customTitle":"Meu título","sessionId":"s"}\n',
                       '{"type":"agent-name","agentName":"Nome do agente","sessionId":"s"}\n', linha_usuario("primeira pergunta"))
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertEqual(transcricao.titulo_do_indice(ind), "Meu título")
        ind["titulo"] = ""
        self.assertEqual(transcricao.titulo_do_indice(ind), "Nome do agente")
        ind["nome_agente"] = ""
        self.assertEqual(transcricao.titulo_do_indice(ind), "primeira pergunta")

    def test_primeira_mensagem_ignora_lembretes_do_sistema(self):
        arq = escrever(self.pasta, "g.jsonl", linha_usuario("<system-reminder>regras internas</system-reminder>"),
                       linha_usuario("<system-reminder>mais regras</system-reminder>\nO pedido de verdade"))
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertEqual(ind["primeira"], "O pedido de verdade")

    def test_modelo_sintetico_nao_conta(self):
        arq = escrever(self.pasta, "h.jsonl", linha_assistente("s1", modelo="<synthetic>"), linha_assistente("r1"))
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertEqual(list(ind["msgs"]), ["r1"])

    def test_segredo_na_primeira_mensagem_e_mascarado(self):
        arq = escrever(self.pasta, "i.jsonl", linha_usuario("use a chave sk-ant-api03-" + "Z" * 30 + " para testar"))
        ind, _ = transcricao.atualizar_indice(arq)
        self.assertNotIn("ZZZZZZ", ind["primeira"])


class TestePassos(unittest.TestCase):
    def test_texto_ferramenta_e_resultado(self):
        ferr = {}
        a = json.loads(linha_assistente("m1", conteudo=[
            {"type": "text", "text": "Vou ler o arquivo"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "C:/p/app.py"}},
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "echo $TOKEN_SECRETO=abcd1234efgh"}}]))
        passos = transcricao.passos_da_linha(a, ferr)
        self.assertEqual([p["tipo"] for p in passos], ["texto", "ferramenta", "ferramenta"])
        self.assertEqual(passos[1]["nome"], "Read")
        self.assertEqual(passos[1]["alvo"], "C:/p/app.py")
        self.assertNotIn("abcd1234efgh", passos[2]["alvo"])
        # resultado de Read: só o tamanho, nunca o conteúdo
        r = {"type": "user", "timestamp": "2026-10-28T12:00:01Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "import os\nSENHA_DO_ARQUIVO = 123\n" * 10}]}}
        p = transcricao.passos_da_linha(r, ferr)[0]
        self.assertEqual(p["tipo"], "resultado")
        self.assertNotIn("import os", p["texto"])
        self.assertIn("caracteres", p["texto"])

    def test_resultado_de_outra_ferramenta_e_encurtado_e_mascarado(self):
        ferr = {"t9": "Bash"}
        r = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t9", "content": [{"type": "text", "text": "ok " * 200 + " ghp_" + "a" * 30}]}]}}
        p = transcricao.passos_da_linha(r, ferr)[0]
        self.assertLessEqual(len(p["texto"]), 241)

    def test_resultado_enorme_mostra_so_tamanho(self):
        ferr = {"t9": "Bash"}
        r = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t9", "content": "x" * 9000}]}}
        self.assertIn("9.000", transcricao.passos_da_linha(r, ferr)[0]["texto"])

    def test_tipos_desconhecidos_e_formatos_estranhos(self):
        for obj in [None, [], {"type": "outra"}, {"type": "user"}, {"type": "assistant", "message": {"content": 5}},
                    {"type": "assistant", "message": {"content": [None, 3, {"type": "tool_use"}]}}]:
            self.assertIsInstance(transcricao.passos_da_linha(obj, {}), list)

    def test_ler_passos_incremental(self):
        pasta = tempfile.mkdtemp(prefix="cerebro_passos_")
        arq = escrever(pasta, "p.jsonl", linha_assistente("m1", conteudo=[{"type": "text", "text": "primeiro"}]))
        ferr = {}
        passos, pos = transcricao.ler_passos(arq, 0, ferr)
        self.assertEqual(len(passos), 1)
        with open(arq, "ab") as f:
            f.write(linha_assistente("m2", conteudo=[{"type": "text", "text": "segundo"}]).encode())
            f.write(b'{"type":"assistant","message":{"content":[{"type":"te')   # linha pela metade
        passos, pos2 = transcricao.ler_passos(arq, pos, ferr)
        self.assertEqual([p["texto"] for p in passos], ["segundo"])
        passos, pos3 = transcricao.ler_passos(arq, pos2, ferr)
        self.assertEqual(passos, [])
        self.assertEqual(pos3, pos2)

    def test_cauda_comeca_no_inicio_de_uma_linha(self):
        pasta = tempfile.mkdtemp(prefix="cerebro_cauda_")
        arq = escrever(pasta, "q.jsonl", *[linha_assistente(f"m{i}", conteudo=[{"type": "text", "text": "x" * 200}]) for i in range(100)])
        pos = transcricao.posicao_inicial_da_cauda(arq, 3000)
        self.assertGreater(pos, 0)
        passos, _ = transcricao.ler_passos(arq, pos, {})
        self.assertTrue(passos)


if __name__ == "__main__":
    unittest.main()
