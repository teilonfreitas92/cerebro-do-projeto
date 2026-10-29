import unittest

from testes import _ambiente  # noqa: F401
from cerebro.segredos import OCULTO, encurtar, mascarar


class TesteSegredos(unittest.TestCase):
    def assertOculto(self, entrada, segredo):
        saida = mascarar(entrada)
        self.assertNotIn(segredo, saida, f"vazou em: {saida!r}")
        self.assertIn(OCULTO, saida)

    def test_chaves_com_prefixo(self):
        self.assertOculto("usei sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV1234 agora", "ABCDEFGHIJKLMNOPQRSTUV1234")
        self.assertOculto("token ghp_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertOculto("github_pat_11ABCDEFG0123456789_abcdefghijklmnop", "11ABCDEFG0123456789")
        self.assertOculto("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP")
        self.assertOculto("xoxb-123456789012-abcdefghij", "123456789012-abcdefghij")

    def test_bearer_e_cabecalhos(self):
        self.assertOculto("curl -H 'Authorization: Bearer abcdef1234567890xyzTOKEN' http://x", "abcdef1234567890xyzTOKEN")
        self.assertOculto("Cookie: sessao=SEGREDO123456\nHost: x", "SEGREDO123456")
        self.assertOculto("x Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abcdefghijk", "eyJhbGciOiJIUzI1NiJ9")

    def test_bloco_de_chave_privada(self):
        txt = "antes\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----\ndepois"
        saida = mascarar(txt)
        self.assertNotIn("MIIEowIBAAKCAQEA", saida)
        self.assertIn("antes", saida)
        self.assertIn("depois", saida)

    def test_bloco_sem_fim_tambem_some(self):
        self.assertNotIn("MIIEowIBAAKCAQEA", mascarar("-----BEGIN PRIVATE KEY-----\nMIIEowIBAAKCAQEA"))

    def test_senhas_em_json_e_atribuicoes(self):
        self.assertOculto('{"password": "hunter2xyz", "usuario": "ana"}', "hunter2xyz")
        self.assertOculto('{"senha":"minha senha forte"}', "minha senha forte")
        self.assertOculto("TELEGRAM_TOKEN=12345:ABCdefGhIJklmn", "12345:ABCdefGhIJklmn")
        self.assertOculto("DB_PASSWORD = 'segredo-do-banco'", "segredo-do-banco")
        self.assertOculto("api_key: abcd1234efgh", "abcd1234efgh")
        self.assertIn('"usuario": "ana"', mascarar('{"password": "hunter2xyz", "usuario": "ana"}'))

    def test_texto_normal_nao_muda(self):
        for t in ["commit 1ba4d74 corrige o painel", "a tokenização é rápida", "caminho C:/Users/ana/Projetos/Loja",
                  "def sorteia(): return 42", "o sk-learn não é chave", ""]:
            self.assertEqual(mascarar(t), t)

    def test_entradas_estranhas(self):
        self.assertEqual(mascarar(None), "")
        self.assertEqual(mascarar(123), "123")

    def test_encurtar_mascara_antes_de_cortar(self):
        chave = "sk-ant-api03-" + "A" * 40
        saida = encurtar("x" * 10 + " " + chave, 20)
        self.assertNotIn("sk-ant", saida)
        self.assertLessEqual(len(saida), 21)

    def test_regressao_da_revisao_independente(self):
        """Cada caso passava em claro antes (achado ALTO da revisão independente)."""
        casos = [
            ("{'password': 'hunter2'}", "hunter2"), ("{'senha': 'abc'}", "abc"), ('{"senha": "ab"}', "ab"),
            ("--password hunter2 --user x", "hunter2"), ("--passwd 'dois espacos'", "dois espacos"), ("--pass segredo99", "segredo99"),
            ("sshpass -p hunter2 ssh a@b", "hunter2"), ("mysql -u root -pSEGREDO99 db", "SEGREDO99"), ("mysql -u root -p SEGREDO99", "SEGREDO99"),
            ("psql -h x -p SEGREDO99 db", "SEGREDO99"),
            ("postgres://ana:s3nh4Forte@db.local:5432/x", "s3nh4Forte"), ("https://user:pw123@host/p", "pw123"),
            ("bot 12345678:AAEhBP0av28qdWyBjSTyT3AqkuiQRaB-NHk", "AAEhBP0av28qdWyBjSTyT3AqkuiQRaB-NHk"),
            ("ya29.a0AfH6SMBx-abcdefghijklmnopqrstuvwxyz", "a0AfH6SMBx"), ("ASIAABCDEFGHIJKLMNOP", "ASIAABCDEFGHIJKLMNOP"),
            ("rk_live_ABCDEFGHIJKLMNOP", "ABCDEFGHIJKLMNOP"), ("rk_test_ABCDEFGHIJKLMNOP", "ABCDEFGHIJKLMNOP"),
            ("whsec_ABCDEFGHIJKLMNOPQRSTUV", "ABCDEFGHIJKLMNOPQRSTUV"),
            ("SG.abcdefghijklmnopqrstuv.wxyzABCDEFGHIJKLMNOPQR", "abcdefghijklmnopqrstuv"),
            ("MTAwMDAwMDAwMDAwMDAwMDA.GabcDE.abcdefghijklmnopqrstuvwxyz0123", "GabcDE"),
            ("my password is hunter2", "hunter2"), ("minha senha é segredo1", "segredo1"), ("senha: ab", "ab"), ("senha=1x", "1x"),
        ]
        for entrada, segredo in casos:
            saida = mascarar(entrada)
            self.assertNotIn(segredo, saida, f"vazou: {entrada!r} -> {saida!r}")
            self.assertIn(OCULTO, saida, entrada)

    def test_regressao_nao_mascara_o_que_nao_e_segredo(self):
        for t in ["ls -p /tmp", "git commit -p", "tar -p x", "mkdir -p a/b", "\"input_tokens\": 123", "max_tokens: 4096",
                  "senha forte é boa", "http://localhost:8188/api/x", "https://github.com/x/y", "o sk-learn não é chave"]:
            self.assertEqual(mascarar(t), t)
        self.assertEqual(mascarar("postgres://ana:s3nh4@db/x"), "postgres://" + OCULTO + "@db/x")


if __name__ == "__main__":
    unittest.main()
