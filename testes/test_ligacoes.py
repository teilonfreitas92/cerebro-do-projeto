"""Ligações da 1.3: tarefas → sessão gestora, PreCompact → passa-bastão, orçamento/backup → aviso do Windows."""
import unittest
from unittest import mock

from testes import _ambiente as amb  # noqa: F401  (isola o ambiente antes do cerebro)
from cerebro import config, ganchos_eventos, ligacoes


class TesteContextoDaGestora(unittest.TestCase):
    def setUp(self):
        ligacoes._ultimo_contexto.clear()

    def _ev(self, sid="s-gestora", slug="proj"):
        return {"evento": "UserPromptSubmit", "slug": slug, "session_id": sid, "em": 1}

    def test_so_a_gestora_recebe_e_sem_repetir(self):
        with mock.patch.object(ligacoes, "_gestora", return_value="s-gestora"), \
             mock.patch("cerebro.tarefas_gestor.texto_para_contexto", return_value="1 tarefa nova"):
            self.assertEqual(ligacoes._ao_mandar_mensagem(self._ev()), "1 tarefa nova")
            self.assertIsNone(ligacoes._ao_mandar_mensagem(self._ev()))             # mesma lista: não repete
            self.assertIsNone(ligacoes._ao_mandar_mensagem(self._ev(sid="outra")))  # outra sessão: nada

    def test_sem_tarefas_nao_escreve(self):
        with mock.patch.object(ligacoes, "_gestora", return_value="s-gestora"), \
             mock.patch("cerebro.tarefas_gestor.texto_para_contexto", return_value=""):
            self.assertIsNone(ligacoes._ao_mandar_mensagem(self._ev()))

    def test_lista_mudou_entrega_de_novo(self):
        with mock.patch.object(ligacoes, "_gestora", return_value="s-gestora"), \
             mock.patch("cerebro.tarefas_gestor.texto_para_contexto", side_effect=["A", "A e B"]):
            self.assertEqual(ligacoes._ao_mandar_mensagem(self._ev()), "A")
            self.assertEqual(ligacoes._ao_mandar_mensagem(self._ev()), "A e B")

    def test_ouvintes_registrados_e_resposta_vai_como_contexto(self):
        ligacoes.ligar()
        ligacoes.ligar()                       # não duplica
        self.assertEqual(ganchos_eventos._ouvintes["UserPromptSubmit"].count(ligacoes._ao_mandar_mensagem), 1)
        ev = self._ev()
        resp = ganchos_eventos.resposta_para(ev, ["1 tarefa nova"])
        self.assertEqual(resp["hookSpecificOutput"]["additionalContext"], "1 tarefa nova")


class TestePassaBastao(unittest.TestCase):
    def test_precompact_grava_o_bastao(self):
        with mock.patch("cerebro.bastao.resumo") as resumo:
            ligacoes._ao_compactar({"evento": "PreCompact", "slug": "proj", "session_id": "s1"})
        resumo.assert_called_once_with("proj", "s1")

    def test_precompact_sem_sessao_nao_faz_nada(self):
        with mock.patch("cerebro.bastao.resumo") as resumo:
            ligacoes._ao_compactar({"evento": "PreCompact", "slug": "proj"})
        resumo.assert_not_called()


class TesteAlertasViramAvisos(unittest.TestCase):
    def setUp(self):
        config.garantir_casa()
        amb.apagar(ligacoes._arquivo_enviados())

    def _rodar(self, agora, orc=None, bkp=None):
        with mock.patch("cerebro.orcamento.alertas", return_value=orc or []), \
             mock.patch("cerebro.backup.alertas", return_value=bkp or []), \
             mock.patch("cerebro.avisos.avisar") as avisar:
            feitos = ligacoes.avisar_alertas(agora=agora)
        return feitos, avisar

    def test_uma_vez_por_dia(self):
        orc = [{"chave": "orc:proj:dia:atencao", "titulo": "Orçamento em 80%", "texto": "x"}]
        feitos, avisar = self._rodar(1_000_000, orc)
        self.assertEqual(feitos, ["orc:proj:dia:atencao"])
        avisar.assert_called_once()
        feitos, avisar = self._rodar(1_000_000 + 3600, orc)
        self.assertEqual(feitos, [])
        avisar.assert_not_called()
        feitos, _ = self._rodar(1_000_000 + 86400, orc)
        self.assertEqual(feitos, ["orc:proj:dia:atencao"])

    def test_backup_so_nivel_aviso(self):
        bkp = [{"nivel": "info", "titulo": "Nenhum backup ainda", "texto": "x"},
               {"nivel": "aviso", "titulo": "O último backup falhou", "texto": "y"}]
        feitos, avisar = self._rodar(2_000_000, bkp=bkp)
        self.assertEqual(feitos, ["backup:O último backup falhou"])
        self.assertEqual(avisar.call_count, 1)

    def test_falha_de_um_modulo_nao_derruba(self):
        with mock.patch("cerebro.orcamento.alertas", side_effect=RuntimeError("quebrou")), \
             mock.patch("cerebro.backup.alertas", return_value=[]), \
             mock.patch("cerebro.avisos.avisar"):
            self.assertEqual(ligacoes.avisar_alertas(agora=3_000_000), [])


if __name__ == "__main__":
    unittest.main()
