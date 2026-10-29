"""Cenários da revisão independente da 1.3 (itens 1, 2, 3, 4, 6, 8, 9, 13 e 14) no backup, no Agendador e no desinstalador.

Cada teste reproduz o cenário que a revisão provou (falhava no código de antes) e confere a correção. Tudo em pastas
temporárias (CEREBRO_HOME / CEREBRO_CLAUDE / CEREBRO_BACKUP / CEREBRO_CLAUDE_SETTINGS em ~/.cerebro-testes), schtasks de
mentira e subprocess trocado por falso: nada toca .claude, .cerebro, o backup de verdade ou o Agendador real."""
import hashlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import agendador, backup, config, ganchos_claude
from testes import ci_instalador as ci
from testes.test_servidor import Base

sys.path.insert(0, str(amb.RAIZ))
import desinstalar  # noqa: E402

SLUG = "C--Users-ana-Projetos-Loja"
SLUGS = [f"C--Users-ana-Projetos-P{i}" for i in range(6)]


def hora(h, d=29, minuto=0):
    return time.mktime((2026, 10, d, h, minuto, 0, 0, 0, -1))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def conversas(slug, n, linhas=200, prefixo="s"):
    pasta = config.PROJETOS_CLAUDE / slug
    pasta.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (pasta / f"{prefixo}{i}.jsonl").write_text(amb.linha_usuario(f"conversa importante {slug} {i}") * linhas, encoding="utf-8")


def memoria(slug, n=3):
    pasta = config.PROJETOS_CLAUDE / slug / "memory"
    pasta.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (pasta / f"regra{i}.md").write_text(f"REGRA {i}: nunca apagar nada sem perguntar\n" * 30, encoding="utf-8")


class BaseRevisao(unittest.TestCase):
    def setUp(self):
        amb.garantir_isolamento()
        amb.apagar(config.PROJETOS_CLAUDE)
        amb.apagar(amb.BACKUP)
        config.garantir_casa()
        amb.apagar(config.CASA / "config.json")
        self.base = backup.pasta_backup()

    def tearDown(self):
        config.garantir_casa()
        amb.apagar(config.CASA / "config.json")

    def nomes(self):
        return [s["nome"] for s in backup.listar(self.base)[0]]


# ======================================================================================================================
# Item 1 (crítico): o 2º backup do dia nunca sobrescreve o snapshot protegido
# ======================================================================================================================
class TesteMesmoDia(BaseRevisao):
    def test_prova_da_revisao_terceiro_backup_nao_troca_o_protegido(self):
        """prova4.py: 09 h A (20 conversas); conversas apagadas; 11 h B encolheu (A protegido); 14 h C trocava A por os.replace."""
        conversas(SLUG, 20, linhas=500)
        a = backup.fazer_backup(agora=hora(9))
        self.assertEqual(a["nome"], "2026-10-29.zip")
        sha_a = sha(self.base / a["nome"])
        for i in range(20):
            amb.apagar(config.PROJETOS_CLAUDE / SLUG / f"s{i}.jsonl")         # "o teste apagou tudo"
        (config.PROJETOS_CLAUDE / SLUG / "nova.jsonl").write_text("x\n", encoding="utf-8")
        b = backup.fazer_backup(agora=hora(11))
        self.assertTrue(b["encolheu"])
        self.assertEqual(backup.resumo()["protegidos"], ["2026-10-29.zip"])
        c = backup.fazer_backup(agora=hora(14))
        self.assertNotEqual(c["nome"], "2026-10-29.zip")
        self.assertEqual(sha(self.base / "2026-10-29.zip"), sha_a)              # o bom continua byte a byte igual
        self.assertEqual(backup.ler_manifesto(self.base / "2026-10-29.zip")["total_arquivos"], a["arquivos"])
        conversas_em_a = [e for e in backup.ler_manifesto(self.base / "2026-10-29.zip")["arquivos"] if e["arq"].startswith("claude/projects/")]
        self.assertEqual(len(conversas_em_a), 20)
        self.assertIn("2026-10-29.zip", backup.resumo()["protegidos"])

    def test_dia_ruim_tres_backups_com_conversas_apagadas_entre_eles(self):
        conversas(SLUG, 12)
        memoria(SLUG)
        for s in SLUGS[:3]:
            conversas(s, 4)
            memoria(s, 2)
        a = backup.fazer_backup(agora=hora(9))                                  # 09 h: tudo inteiro
        bom = self.base / a["nome"]
        sha_bom, total_bom = sha(bom), a["arquivos"]
        # 10 h: alguém apaga as conversas do projeto principal
        for i in range(12):
            amb.apagar(config.PROJETOS_CLAUDE / SLUG / f"s{i}.jsonl")
        b = backup.fazer_backup(agora=hora(11))
        self.assertTrue(b["encolheu"])
        # 12 h: some a memória de outro projeto e nasce uma conversa nova
        amb.apagar(config.PROJETOS_CLAUDE / SLUGS[0] / "memory")
        conversas(SLUG, 1, prefixo="nova")
        c = backup.fazer_backup(agora=hora(14))
        # 15 h: mais coisa apagada
        amb.apagar(config.PROJETOS_CLAUDE / SLUGS[1])
        d = backup.fazer_backup(agora=hora(17))
        self.assertEqual(len({a["nome"], b["nome"], c["nome"], d["nome"]}), 4)  # cada backup com nome próprio
        self.assertTrue(c["encolheu"] and d["encolheu"])                        # régua = o último que NÃO encolheu (o das 9 h)
        self.assertEqual(sha(bom), sha_bom)
        self.assertEqual(backup.resumo()["protegidos"], [a["nome"]])
        # duas semanas de backups diários depois: o bom nunca sai da rotação nem é trocado
        for d_ in range(30, 32):
            backup.fazer_backup(agora=hora(12, d=d_))
        for d_ in range(1, 13):
            backup.fazer_backup(agora=time.mktime((2026, 11, d_, 12, 0, 0, 0, 0, -1)))
            self.assertIn(a["nome"], self.nomes())
            self.assertEqual(sha(bom), sha_bom)
        self.assertLessEqual(len(self.nomes()), 8)                              # 7 dias + o protegido
        self.assertEqual(backup.ler_manifesto(bom)["total_arquivos"], total_bom)
        # e dá para restaurar dele o que foi apagado
        pl = backup.plano(a["nome"])
        self.assertGreaterEqual(pl["totais"]["faltam"], 12)
        self.assertTrue(any("menor" in x["titulo"] for x in backup.alertas(agora=time.mktime((2026, 11, 12, 13, 0, 0, 0, 0, -1)))))

    def test_do_meio_do_dia_sai_sem_protegido_e_fica_com_protegido(self):
        conversas(SLUG, 4)
        nomes = [backup.fazer_backup(agora=hora(h))["nome"] for h in (9, 11, 14)]
        self.assertEqual(self.nomes(), [nomes[2], nomes[0]])                   # o primeiro e o último do dia ficam
        backup.fazer_backup(agora=hora(16))
        self.assertEqual(len(self.nomes()), 2)

    def test_nome_livre_nunca_e_existente_nem_protegido(self):
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "2026-10-29.zip").write_bytes(b"ocupado")
        (self.base / "2026-10-29_090000.zip").write_bytes(b"ocupado")
        livre = backup._nome_livre(self.base, "2026-10-29", hora(9), ["2026-10-29_090001.zip"])
        self.assertEqual(livre.name, "2026-10-29_090002.zip")
        parcial = self.base / "2026-10-29.zip.parcial"
        parcial.write_bytes(b"novo")
        with self.assertRaises(FileExistsError):
            backup._trocar_nome_sem_sobrescrever(self.base, parcial, self.base / "2026-10-29.zip")
        self.assertEqual((self.base / "2026-10-29.zip").read_bytes(), b"ocupado")


# ======================================================================================================================
# Item 8: "encolheu" por projeto e por memória, não só pelo total
# ======================================================================================================================
class TesteEncolheuPorProjeto(BaseRevisao):
    def setUp(self):
        super().setUp()
        for s in SLUGS:
            conversas(s, 4)
            memoria(s, 2)
        backup.fazer_backup(agora=hora(9, d=20))

    def test_um_projeto_inteiro_apagado_conta(self):
        amb.apagar(config.PROJETOS_CLAUDE / SLUGS[2])           # 1 de 6 projetos: o total cai só ~17%
        r = backup.fazer_backup(agora=hora(9, d=21))
        self.assertTrue(r["encolheu"])
        self.assertTrue(any(SLUGS[2] in m and "sumiu" in m for m in r["motivos"]), r["motivos"])
        self.assertEqual(backup.resumo()["protegidos"], ["2026-10-20.zip"])

    def test_a_memoria_de_um_projeto_apagada_conta(self):
        amb.apagar(config.PROJETOS_CLAUDE / SLUGS[4] / "memory")
        r = backup.fazer_backup(agora=hora(9, d=21))
        self.assertTrue(r["encolheu"])
        self.assertTrue(any("memória" in m and SLUGS[4] in m for m in r["motivos"]), r["motivos"])

    def test_projeto_que_caiu_a_menos_da_metade_conta_e_crescer_nao(self):
        conversas(SLUGS[0], 2, prefixo="extra")
        r = backup.fazer_backup(agora=hora(9, d=21))
        self.assertFalse(r["encolheu"], r["motivos"])
        for i in range(4):
            amb.apagar(config.PROJETOS_CLAUDE / SLUGS[1] / f"s{i}.jsonl")
        r = backup.fazer_backup(agora=hora(9, d=22))
        self.assertTrue(r["encolheu"])
        self.assertTrue(any(SLUGS[1] in m for m in r["motivos"]))


# ======================================================================================================================
# Itens 2 e 14: a pasta de backup e o "apagar tudo" do desinstalador
# ======================================================================================================================
class TestePastaDeBackup(BaseRevisao):
    def sem_variavel(self):
        """Sem CEREBRO_BACKUP: vale o config.json (de mentira) — a pasta continua dentro da pasta de testes."""
        env = dict(os.environ)
        env.pop("CEREBRO_BACKUP", None)
        return mock.patch.dict(os.environ, env, clear=True)

    def usar_pasta(self, pasta):
        (config.CASA / "config.json").write_text(json.dumps({"backup": {"pasta": str(pasta)}}), encoding="utf-8")

    def test_prova_da_revisao_documentos_nao_e_apagado(self):
        docs = amb.BASE / "revisao-docs" / "Documentos"
        (docs / "Projeto_Importante" / "src").mkdir(parents=True, exist_ok=True)
        (docs / "Projeto_Importante" / "src" / "main.py").write_text("x", encoding="utf-8")
        (docs / "tese.docx").write_text("tese", encoding="utf-8")
        self.usar_pasta(docs)
        with self.sem_variavel():
            with self.assertRaises(backup.BackupErro):
                backup.pasta_backup()
            with self.assertRaises(backup.BackupErro):
                backup.apagar_tudo()
            with self.assertRaises(backup.BackupErro):
                backup.fazer_backup(agora=hora(9))
        self.assertTrue((docs / "tese.docx").is_file())
        self.assertTrue((docs / "Projeto_Importante" / "src" / "main.py").is_file())

    def test_pasta_escolhida_vazia_ganha_a_marca_e_vale(self):
        nova = amb.BASE / "revisao-docs" / "MeusBackups"
        amb.apagar(nova)
        self.usar_pasta(nova)
        conversas(SLUG, 2)
        with self.sem_variavel():
            r = backup.fazer_backup(agora=hora(9))
            self.assertTrue((nova / backup.MARCA).is_file())
            (nova / "anotacao.txt").write_text("minha", encoding="utf-8")       # pasta com outras coisas, mas marcada: vale
            self.assertEqual(backup.pasta_backup(), Path(os.path.abspath(nova)))
            backup.apagar_tudo()
        self.assertFalse((nova / r["nome"]).exists())
        self.assertTrue((nova / "anotacao.txt").is_file())
        self.assertTrue((nova / backup.MARCA).is_file())                         # a pasta não ficou vazia: a marca fica

    def test_caminho_relativo_e_recusado(self):
        self.usar_pasta("backups_do_cerebro")
        with self.sem_variavel():
            with self.assertRaises(backup.BackupErro):
                backup.pasta_backup()
        with mock.patch.dict(os.environ, {"CEREBRO_BACKUP": "relativa/bk"}):
            with self.assertRaises(backup.BackupErro):
                backup.pasta_backup()

    def test_apagar_tudo_so_leva_o_que_e_do_backup(self):
        conversas(SLUG, 2)
        r = backup.fazer_backup(agora=hora(9))
        (self.base / "2026-10-28.zip.parcial").write_bytes(b"metade")
        (self.base / "planilha.xlsx").write_bytes(b"do dono")
        (self.base / "2026-01-01.zip").write_bytes(b"zip do dono, sem manifesto")
        (self.base / "fotos").mkdir()
        (self.base / "fotos" / "a.jpg").write_bytes(b"foto")
        (self.base / "copias" / "restauracao-x").mkdir(parents=True)
        (self.base / "copias" / "restauracao-x" / "sessao.jsonl").write_text("{}", encoding="utf-8")
        n = backup.apagar_tudo()
        self.assertEqual(n, 3)                                                   # snapshot, parcial, estado.json
        self.assertFalse((self.base / r["nome"]).exists())
        for fica in ("planilha.xlsx", "2026-01-01.zip", "fotos/a.jpg", "copias/restauracao-x/sessao.jsonl"):
            self.assertTrue((self.base / fica).exists(), fica)
        self.assertEqual(backup.sobras(self.base), ["2026-01-01.zip", "copias", "fotos", "planilha.xlsx"])
        backup.apagar_tudo(copias=True)                                          # copias/ só com a pergunta própria
        self.assertFalse((self.base / "copias").exists())
        self.assertTrue((self.base / "fotos" / "a.jpg").exists())

    def test_apagar_tudo_recusa_pasta_sem_marca_nem_nome(self):
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "2026-10-20.zip.parcial").write_bytes(b"x")
        with self.assertRaises(backup.BackupErro):
            backup.apagar_tudo()
        self.assertTrue((self.base / "2026-10-20.zip.parcial").exists())


# ======================================================================================================================
# Itens 3 e 6: Agendador real travado fora da instalação principal; schtasks pelo caminho completo
# ======================================================================================================================
class _Concluido:
    returncode, stdout, stderr = 0, "", ""


class TesteTravasDoAgendador(unittest.TestCase):
    def setUp(self):
        amb.garantir_isolamento()

    def ambiente(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("CEREBRO_TESTE_HOME", "CEREBRO_DEMO", "CEREBRO_SEM_AGENDADOR", "CEREBRO_HOME")}
        env.update(extra)
        return mock.patch.dict(os.environ, env, clear=True)

    def test_sem_agendador_e_outra_casa_recusam_antes_do_schtasks(self):
        chamado = mock.Mock(side_effect=AssertionError("o schtasks real não pode rodar aqui"))
        with mock.patch.object(agendador.subprocess, "run", chamado):
            with self.ambiente(CEREBRO_SEM_AGENDADOR="1"):
                with self.assertRaises(agendador.AgendadorErro):
                    agendador._executar_de_verdade([agendador.caminho_schtasks(), "/Delete", "/TN", "CerebroDoProjeto\\backup", "/F"])
            with self.ambiente(CEREBRO_HOME=str(config.CASA)):          # 2ª cópia / prova: CEREBRO_HOME fora de ~/.cerebro
                with self.assertRaises(agendador.AgendadorErro) as e:
                    agendador._executar_de_verdade([agendador.caminho_schtasks(), "/Query"])
                self.assertIn("CEREBRO_HOME", str(e.exception))
        chamado.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "o agendamento é do Windows")
    def test_instalacao_principal_chama_pelo_caminho_completo(self):
        chamado = mock.Mock(return_value=_Concluido())
        with mock.patch.object(agendador.subprocess, "run", chamado), self.ambiente():
            self.assertIsNone(agendador.motivo_sem_agendador())
            agendador._executar_de_verdade([agendador.caminho_schtasks(), "/Query"])
            with self.assertRaises(agendador.AgendadorErro):
                agendador._executar_de_verdade(["schtasks", "/Query"])         # nome solto: recusado
        self.assertEqual(chamado.call_count, 1)
        self.assertTrue(Path(chamado.call_args[0][0][0]).is_absolute())

    def test_caminho_do_schtasks_nunca_e_relativo(self):
        for valor in (".", "", "pasta\\relativa"):
            with mock.patch.dict(os.environ, {"SystemRoot": valor, "SYSTEMROOT": valor}):
                self.assertEqual(agendador.caminho_schtasks(), str(Path(r"C:\Windows") / "System32" / "schtasks.exe"))
        with mock.patch.dict(os.environ, {"SystemRoot": r"D:\Win", "SYSTEMROOT": r"D:\Win"}):
            self.assertTrue(agendador.caminho_schtasks().endswith("schtasks.exe"))

    def test_prova_do_instalador_define_sem_agendador(self):
        trabalho = amb.BASE / "ci_falso"
        env = ci.ambiente_filho(trabalho, trabalho / "home", trabalho / "casa")
        self.assertEqual(env["CEREBRO_SEM_AGENDADOR"], "1")
        self.assertNotIn("CEREBRO_TESTE_HOME", env)
        self.assertNotIn("CEREBRO_CLAUDE_SETTINGS", env)
        self.assertTrue(Path(env["CEREBRO_BACKUP"]).is_relative_to(trabalho))
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNotNone(agendador.motivo_sem_agendador())


@unittest.skipUnless(os.name == "nt", "o agendamento é do Windows")
class TesteRemoverSoDestaInstalacao(unittest.TestCase):
    def setUp(self):
        amb.garantir_isolamento()
        self.falso = amb.AgendadorFalso()
        self.troca = mock.patch.object(agendador, "EXECUTAR", self.falso)
        self.troca.start()

    def tearDown(self):
        self.troca.stop()

    def test_desinstalar_uma_copia_nao_remove_a_tarefa_da_principal(self):
        agendador.ligar("backup")                                               # desta instalação
        outra = Path(r"D:\OutraCopia\Cerebro") / "cerebro_cli.py"
        self.falso.tarefas["CerebroDoProjeto\\novidades"] = agendador.montar_xml("novidades", {"hora": "13:10", "dias": 3}, cli=outra)
        self.assertTrue(agendador.aponta_para_esta("backup"))
        self.assertFalse(agendador.aponta_para_esta("novidades"))
        self.assertFalse(agendador.aponta_para_esta("mapa"))                    # nem existe
        self.assertEqual(agendador.remover_todas(), ["CerebroDoProjeto\\backup"])
        self.assertIn("CerebroDoProjeto\\novidades", self.falso.tarefas)
        self.assertEqual(agendador.outras_copias(), ["CerebroDoProjeto\\novidades"])
        for c in self.falso.chamadas:
            self.assertTrue(Path(c[0]).is_absolute() and c[0].lower().endswith("schtasks.exe"), c[0])


# ======================================================================================================================
# Itens 4 e 9: desinstalar tira os ganchos (statusLine antiga volta) e não perde as cópias de ~/.cerebro/copias
# ======================================================================================================================
class TesteDesinstalarRevisao(BaseRevisao):
    def setUp(self):
        super().setUp()
        self.raiz = amb.BASE / "desinstalacao-revisao"
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.settings = ganchos_claude.caminho_settings()
        amb.apagar(self.settings)
        amb.apagar(config.CASA / "ganchos.json")
        amb.apagar(config.CASA / "copias")
        self.falso = amb.AgendadorFalso()
        self.troca = mock.patch.object(agendador, "EXECUTAR", self.falso)
        self.troca.start()
        self.saida = []

    def tearDown(self):
        self.troca.stop()
        amb.apagar(self.settings)
        config.garantir_casa()
        amb.apagar(config.CASA / "ganchos.json")
        amb.apagar(config.CASA / "copias")
        super().tearDown()

    def rodar(self, *args, entrada=()):
        respostas = iter(entrada)
        return desinstalar.main(list(args) + ["--sem-encerrar"], entrada=lambda _p="": next(respostas, ""), saida=self.saida.append, raiz=self.raiz)

    def instalar_ganchos(self):
        anterior = {"type": "command", "command": "bash ~/minha-linha.sh"}
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"statusLine": anterior, "permissions": {"allow": ["Bash(ls)"]}}), encoding="utf-8")
        ganchos_claude.instalar(confirmar=True, hooks=True, modo="comando", statusline="encadear")
        self.assertTrue(desinstalar.entradas_no_settings())
        return anterior

    def test_apagar_dados_tira_os_ganchos_e_devolve_a_statusline_antiga(self):
        anterior = self.instalar_ganchos()
        self.rodar("--sim", "--apagar-dados")
        dados = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(dados["statusLine"], anterior)                        # a statusLine do dono voltou
        self.assertEqual(dados["permissions"], {"allow": ["Bash(ls)"]})
        self.assertNotIn("hooks", dados)
        self.assertEqual(desinstalar.entradas_no_settings(), [])
        self.assertFalse(config.CASA.exists())
        guardadas = list((self.base / "copias").glob("desinstalacao-*"))
        self.assertEqual(len(guardadas), 1)                                     # o settings.json de antes ficou guardado fora da casa
        self.assertTrue(list((guardadas[0] / "copias" / "settings").glob("*.json")))

    def test_recusa_apagar_a_casa_enquanto_o_settings_chama_o_cerebro(self):
        self.instalar_ganchos()
        self.rodar("--apagar-dados", entrada=["n"])                             # "não" para tirar os ganchos
        self.assertTrue((config.CASA / "ganchos.json").is_file())               # a statusLine antiga continua guardada
        self.assertTrue(desinstalar.entradas_no_settings())
        self.assertIn("NÃO apaguei os dados", "\n".join(self.saida))

    def test_settings_invalido_com_o_cerebro_tambem_segura_a_casa(self):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text('{"statusLine": {"command": "pythonw cerebro_statusline.py"}, quebrado', encoding="utf-8")
        self.rodar("--sim", "--apagar-dados")
        self.assertTrue(config.CASA.is_dir())
        self.assertIn('quebrado', self.settings.read_text(encoding="utf-8"))   # não mexeu no arquivo quebrado

    def test_copias_da_casa_vao_para_a_pasta_de_backup(self):
        (config.CASA / "copias" / "memoria" / "C--x").mkdir(parents=True)
        (config.CASA / "copias" / "memoria" / "C--x" / "MEMORY.md").write_text("memória antes da edição\n", encoding="utf-8")
        self.rodar("--sim", "--apagar-dados")
        self.assertFalse(config.CASA.exists())
        achadas = list((self.base / "copias").glob("desinstalacao-*/copias/memoria/C--x/MEMORY.md"))
        self.assertEqual(len(achadas), 1)
        self.assertEqual(achadas[0].read_text(encoding="utf-8"), "memória antes da edição\n")
        self.assertIn("Backups mantidos", "\n".join(self.saida))

    def test_copias_so_somem_com_sim_explicito(self):
        (config.CASA / "copias" / "x").mkdir(parents=True)
        (config.CASA / "copias" / "x" / "a.txt").write_text("a", encoding="utf-8")
        self.rodar("--sim", "--apagar-dados", entrada=["s"])                   # a pergunta das cópias ignora o --sim
        self.assertFalse(config.CASA.exists())
        self.assertFalse((self.base / "copias").exists())

    def test_sem_onde_guardar_as_copias_a_casa_fica(self):
        (config.CASA / "copias" / "x").mkdir(parents=True)
        (config.CASA / "copias" / "x" / "a.txt").write_text("a", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CEREBRO_BACKUP": str(config.CASA / "bk")}):      # pasta de backup inválida
            self.rodar("--sim", "--apagar-dados")
        self.assertTrue((config.CASA / "copias" / "x" / "a.txt").is_file())
        self.assertIn("NÃO apaguei a pasta de dados", "\n".join(self.saida))


# ======================================================================================================================
# Item 13: liberar os protegidos pela página exige "confirmar": true
# ======================================================================================================================
class TesteRotaLiberar(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        amb.apagar(amb.BACKUP)

    async def test_liberar_sem_confirmar_e_recusado(self):
        backup._gravar_estado(backup.pasta_backup(), {"protegidos": ["2026-10-20.zip"]})
        await self.entrar()
        r = await self.post("/api/backup/liberar", {})
        self.assertEqual(r.status, 400)
        self.assertEqual(backup.resumo()["protegidos"], ["2026-10-20.zip"])
        r = await self.post("/api/backup/liberar", {"confirmar": "sim"})
        self.assertEqual(r.status, 400)
        r = await self.post("/api/backup/liberar", {"confirmar": True})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["liberados"], ["2026-10-20.zip"])
        self.assertEqual(backup.resumo()["protegidos"], [])


if __name__ == "__main__":
    unittest.main()
