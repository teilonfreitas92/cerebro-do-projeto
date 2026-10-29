"""Backup diário e rotativo, restauração sem apagar nada, rotinas no Windows (Agendador falso), CLI, rotas e desinstalador.

Tudo em pastas temporárias (CEREBRO_HOME / CEREBRO_CLAUDE / CEREBRO_BACKUP em ~/.cerebro-testes) e com o schtasks de mentira
(testes._ambiente.AgendadorFalso). Nenhum teste toca .claude, .cerebro, a pasta de backup de verdade ou o Agendador real."""
import contextlib
import io
import json
import os
import sys
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import agendador, backup, config, ganchos_claude, painel, rotinas_windows
from testes.test_servidor import Base

sys.path.insert(0, str(amb.RAIZ))
import cerebro_cli  # noqa: E402
import desinstalar  # noqa: E402

SLUG_A = "C--Users-ana-Projetos-Loja"
SLUG_B = "C--Users-ana-Projetos-Blog"


def dia(d, hora=12):
    return time.mktime((2026, 10, d, hora, 0, 0, 0, 0, -1))


def montar_dados():
    """Conversas e memória de mentira em CEREBRO_CLAUDE/projects e alguns dados (e caches) em CEREBRO_HOME."""
    amb.apagar(config.PROJETOS_CLAUDE)
    amb.apagar(amb.BACKUP)
    for slug in (SLUG_A, SLUG_B):
        pasta = config.PROJETOS_CLAUDE / slug
        (pasta / "memory").mkdir(parents=True)
        for i in range(3):
            (pasta / f"sessao{i}.jsonl").write_text(amb.linha_usuario(f"oi {slug} {i}") * 20, encoding="utf-8")
        (pasta / "memory" / "MEMORY.md").write_text(f"- regra de {slug}\n", encoding="utf-8")
        (pasta / "memory" / "fato.md").write_text("REGRA: testar sempre\n", encoding="utf-8")
    config.garantir_casa()
    (config.CASA / "projetos" / SLUG_A).mkdir(parents=True, exist_ok=True)
    (config.CASA / "projetos" / SLUG_A / "decisoes.jsonl").write_text('{"texto":"decidido"}\n', encoding="utf-8")
    (config.CASA / "projetos" / SLUG_A / "indice.json").write_text("{}", encoding="utf-8")          # cache: não entra
    (config.CASA / "token").write_text("x" * 40, encoding="ascii")                                     # não entra


def nomes_no_zip(caminho):
    with zipfile.ZipFile(caminho) as zf:
        return set(zf.namelist())


class BaseBackup(unittest.TestCase):
    def setUp(self):
        amb.garantir_isolamento()
        montar_dados()
        self.base = backup.pasta_backup()

    def snapshots(self):
        return [s["nome"] for s in backup.listar(self.base)[0]]


# ======================================================================================================================
# 1. Fazer o backup
# ======================================================================================================================
class TesteFazerBackup(BaseBackup):
    def test_pasta_e_a_dos_testes_e_fica_fora_de_claude_e_cerebro(self):
        self.assertEqual(self.base.resolve(), amb.BACKUP.resolve())
        for pasta in (config.CASA, config.CLAUDE):
            with self.assertRaises(ValueError):
                self.base.resolve().relative_to(Path(pasta).resolve())

    def test_recusa_pasta_dentro_de_cerebro_ou_claude(self):
        for ruim in (config.CASA / "bk", config.PROJETOS_CLAUDE / "bk", amb.BASE):       # dentro, ou contendo as duas
            with mock.patch.dict(os.environ, {"CEREBRO_BACKUP": str(ruim)}):
                with self.assertRaises(backup.BackupErro):
                    backup.pasta_backup()

    def test_snapshot_com_manifesto_sem_caches_e_que_confere(self):
        r = backup.fazer_backup(agora=dia(20))
        self.assertTrue(r["ok"])
        self.assertEqual(r["nome"], "2026-10-20.zip")
        nomes = nomes_no_zip(self.base / r["nome"])
        self.assertIn(backup.MANIFESTO, nomes)
        self.assertIn(f"claude/projects/{SLUG_A}/sessao0.jsonl", nomes)
        self.assertIn(f"claude/projects/{SLUG_B}/memory/fato.md", nomes)
        self.assertIn(f"cerebro/projetos/{SLUG_A}/decisoes.jsonl", nomes)
        self.assertNotIn(f"cerebro/projetos/{SLUG_A}/indice.json", nomes)
        self.assertNotIn("cerebro/token", nomes)
        man = backup.ler_manifesto(self.base / r["nome"])
        self.assertEqual(man["total_arquivos"], len(man["arquivos"]))
        self.assertTrue(all(len(e["sha256"]) == 64 and e["tam"] >= 0 for e in man["arquivos"]))
        c = backup.conferir(r["nome"])
        self.assertTrue(c["ok"], c)
        self.assertFalse(any(p.name.endswith(".parcial") for p in self.base.iterdir()))

    def test_manifesto_pega_conteudo_adulterado(self):
        r = backup.fazer_backup(agora=dia(20))
        orig = self.base / r["nome"]
        adulterado = self.base / "2026-10-19.zip"
        with zipfile.ZipFile(orig) as zin, zipfile.ZipFile(adulterado, "w") as zout:
            for item in zin.namelist():
                dados = zin.read(item)
                if item.endswith("sessao0.jsonl"):
                    dados = dados.replace(b"oi", b"OI")
                zout.writestr(item, dados)
        c = backup.conferir("2026-10-19.zip")
        self.assertFalse(c["ok"])
        self.assertTrue(any("sessao0.jsonl" in p for p in c["problemas"]))

    def test_snapshot_incompleto_nao_conta(self):
        backup.fazer_backup(agora=dia(20))
        (self.base / "2026-10-21.zip.parcial").write_bytes(b"PK metade")
        (self.base / "2026-10-22.zip").write_bytes(b"isto nao e zip")
        with zipfile.ZipFile(self.base / "2026-10-23.zip", "w") as zf:                 # zip sem manifesto
            zf.writestr("claude/projects/x/a.jsonl", "{}")
        completos, incompletos = backup.listar(self.base)
        self.assertEqual([s["nome"] for s in completos], ["2026-10-20.zip"])
        self.assertEqual({s["nome"] for s in incompletos}, {"2026-10-21.zip.parcial", "2026-10-22.zip", "2026-10-23.zip"})
        with self.assertRaises(backup.BackupErro):
            backup.achar_snapshot("2026-10-23")
        # o "anterior" para comparar e para a idade do backup é o completo, não o quebrado
        self.assertEqual(backup.resumo()["snapshots"][0]["nome"], "2026-10-20.zip")

    def test_arquivo_travado_e_registrado_e_o_resto_segue(self):
        original = backup._sha_e_copia

        def travado(origem, w, limite):
            if Path(origem).name == "sessao1.jsonl":
                raise PermissionError("arquivo em uso por outro processo")
            return original(origem, w, limite)

        with mock.patch.object(backup, "_sha_e_copia", travado):
            r = backup.fazer_backup(agora=dia(20))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["falhas"]), 2)                                # sessao1 dos dois projetos
        self.assertIn("PermissionError", r["falhas"][0]["erro"])
        man = backup.ler_manifesto(self.base / r["nome"])
        self.assertEqual(len(man["falhas"]), 2)
        self.assertTrue(backup.conferir(r["nome"])["ok"])

    def test_conversa_que_cresce_durante_a_copia_fica_com_o_tamanho_do_inicio(self):
        arq = config.PROJETOS_CLAUDE / SLUG_A / "sessao0.jsonl"
        tam = arq.stat().st_size
        original = backup._sha_e_copia

        def cresce(origem, w, limite):
            if Path(origem) == arq:
                with open(arq, "a", encoding="utf-8") as f:
                    f.write(amb.linha_usuario("escrito durante o backup"))
            return original(origem, w, limite)

        with mock.patch.object(backup, "_sha_e_copia", cresce):
            r = backup.fazer_backup(agora=dia(20))
        man = {e["arq"]: e for e in backup.ler_manifesto(self.base / r["nome"])["arquivos"]}
        self.assertEqual(man[f"claude/projects/{SLUG_A}/sessao0.jsonl"]["tam"], tam)
        self.assertTrue(backup.conferir(r["nome"])["ok"])

    def test_falha_nao_deixa_parcial_nao_roda_rotacao_e_avisa(self):
        for d in range(1, 10):
            backup.fazer_backup(agora=dia(d))
        antes = self.snapshots()
        with mock.patch.object(backup, "_escrever_zip", side_effect=OSError("disco cheio")):
            with self.assertRaises(backup.BackupErro):
                backup.fazer_backup(agora=dia(25))
        self.assertEqual(self.snapshots(), antes)
        self.assertFalse(any(p.name.endswith(".parcial") for p in self.base.iterdir()))
        self.assertFalse(backup.resumo()["ultimo"]["ok"])
        self.assertTrue(any(a["titulo"] == "O último backup falhou" for a in backup.alertas(agora=dia(25))))

    def test_um_backup_por_vez(self):
        (self.base).mkdir(parents=True, exist_ok=True)
        (self.base / backup.ARQ_TRAVA).write_text("123 0", encoding="ascii")
        with self.assertRaises(backup.BackupErro):
            backup.fazer_backup(agora=dia(20))
        os.utime(self.base / backup.ARQ_TRAVA, (time.time() - 4 * 3600,) * 2)         # trava velha: descartada
        self.assertTrue(backup.fazer_backup(agora=dia(20))["ok"])
        self.assertFalse((self.base / backup.ARQ_TRAVA).exists())

    def test_mesmo_dia_nunca_sobrescreve_o_de_hoje(self):
        backup.fazer_backup(agora=dia(20, 9))
        primeiro = (self.base / "2026-10-20.zip").read_bytes()
        (config.PROJETOS_CLAUDE / SLUG_A / "nova.jsonl").write_text("{}\n", encoding="utf-8")
        r = backup.fazer_backup(agora=dia(20, 18))
        self.assertEqual(r["nome"], "2026-10-20_180000.zip")
        self.assertEqual(self.snapshots(), ["2026-10-20_180000.zip", "2026-10-20.zip"])
        self.assertEqual((self.base / "2026-10-20.zip").read_bytes(), primeiro)               # o das 9 h ficou intacto
        self.assertIn(f"claude/projects/{SLUG_A}/nova.jsonl", nomes_no_zip(self.base / r["nome"]))
        self.assertEqual(backup.achar_snapshot("2026-10-20"), "2026-10-20_180000.zip")         # pela data: o mais novo do dia

    def test_rotina_ao_fazer_logon_pula_se_hoje_ja_tem(self):
        backup.fazer_backup(agora=dia(20, 9))
        r = backup.fazer_backup(agora=dia(20, 10), so_se_faltar_hoje=True)
        self.assertTrue(r.get("pulado"))

    def test_medir_so_le_tamanhos(self):
        m = backup.medir_origens()
        self.assertEqual(m["claude/projects"]["arquivos"], 10)
        self.assertGreater(m["claude/projects"]["bytes"], 0)
        self.assertFalse(self.base.exists() and any(self.base.iterdir()))


# ======================================================================================================================
# 2. Rotação
# ======================================================================================================================
class TesteRotacao(BaseBackup):
    def test_guarda_7_dias_por_padrao(self):
        for d in range(1, 11):
            backup.fazer_backup(agora=dia(d))
        self.assertEqual(self.snapshots(), [f"2026-10-{d:02d}.zip" for d in range(10, 3, -1)])

    def test_pc_desligado_uma_semana_nao_perde_os_antigos(self):
        for d in (1, 2, 3, 4, 5, 6, 7):
            backup.fazer_backup(agora=dia(d))
        backup.fazer_backup(agora=dia(28))                 # 3 semanas depois: conta dias QUE TÊM backup
        self.assertEqual(len(self.snapshots()), 7)
        self.assertEqual(self.snapshots()[0], "2026-10-28.zip")

    def test_configuravel_e_nunca_apaga_o_mais_novo(self):
        config.atualizar_config(lambda c: c["backup"].__setitem__("manter_dias", 2))
        try:
            for d in range(1, 6):
                backup.fazer_backup(agora=dia(d))
            self.assertEqual(self.snapshots(), ["2026-10-05.zip", "2026-10-04.zip"])
            backup.rodar_rotacao(self.base, 0)               # mesmo pedindo 0, o mais novo fica
            self.assertEqual(self.snapshots(), ["2026-10-05.zip"])
        finally:
            config.atualizar_config(lambda c: c["backup"].__setitem__("manter_dias", 7))

    def test_nao_apaga_nada_fora_da_pasta_de_backup_nem_fora_do_padrao(self):
        backup.fazer_backup(agora=dia(20))
        fora = amb.BASE / "outro" / "2026-01-01.zip"
        fora.parent.mkdir(parents=True, exist_ok=True)
        fora.write_bytes(b"x")
        no_claude = config.PROJETOS_CLAUDE / "2026-01-01.zip"
        no_claude.write_bytes(b"x")
        estranho = self.base / "meu-arquivo.zip"
        estranho.write_bytes(b"x")
        for alvo in (fora, no_claude, estranho, self.base / ".." / "outro" / "2026-01-01.zip"):
            with self.assertRaises(config.RemocaoRecusada):
                backup.remover_snapshot(self.base, alvo)
        for alvo in (fora, no_claude, estranho):
            self.assertTrue(alvo.exists())
        backup.rodar_rotacao(self.base, 1)
        self.assertTrue(estranho.exists())                    # nome fora do padrão: a rotação nem olha

    def test_parcial_velho_sai_e_o_novo_fica(self):
        backup.fazer_backup(agora=dia(20))
        velho, novo = self.base / "2026-10-18.zip.parcial", self.base / "2026-10-19.zip.parcial"
        velho.write_bytes(b"x")
        novo.write_bytes(b"x")
        os.utime(velho, (time.time() - 7 * 3600,) * 2)
        backup.rodar_rotacao(self.base, 7)
        self.assertFalse(velho.exists())
        self.assertTrue(novo.exists())

    def test_backup_que_encolheu_protege_o_anterior_ate_liberar(self):
        for d in range(1, 8):
            backup.fazer_backup(agora=dia(d))
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_A)           # "alguém apagou" metade
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_B / "sessao0.jsonl")
        r = backup.fazer_backup(agora=dia(8))
        self.assertTrue(r["encolheu"])
        self.assertEqual(r["removidos"], [])                  # não roda rotação quando encolheu
        self.assertEqual(backup.resumo()["protegidos"], ["2026-10-07.zip"])
        self.assertTrue(any("menor" in a["titulo"] for a in backup.alertas(agora=dia(8))))
        for d in range(9, 20):                                 # dias seguintes: o protegido nunca sai
            backup.fazer_backup(agora=dia(d))
        self.assertIn("2026-10-07.zip", self.snapshots())
        self.assertEqual(len(self.snapshots()), 8)
        self.assertEqual(backup.liberar_protegidos(), ["2026-10-07.zip"])
        backup.fazer_backup(agora=dia(20))
        self.assertNotIn("2026-10-07.zip", self.snapshots())
        self.assertFalse(any("menor" in a["titulo"] for a in backup.alertas(agora=dia(20))))

    def test_encolheu_no_mesmo_dia_guarda_os_dois(self):
        backup.fazer_backup(agora=dia(20, 9))
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_A)
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_B)
        r = backup.fazer_backup(agora=dia(20, 18))
        self.assertEqual(r["nome"], "2026-10-20_180000.zip")
        self.assertIn("2026-10-20.zip", self.snapshots())


# ======================================================================================================================
# 3. Alertas ("Precisa de você")
# ======================================================================================================================
class TesteAlertas(BaseBackup):
    def test_nunca_feito_atrasado_e_em_dia(self):
        self.assertEqual([a["titulo"] for a in backup.alertas()], ["Nenhum backup das conversas ainda"])
        backup.fazer_backup(agora=time.time() - 3 * 86400)
        self.assertTrue(backup.alertas()[0]["titulo"].startswith("Backup atrasado"))
        backup.fazer_backup()
        self.assertEqual(backup.alertas(), [])

    def test_vai_para_a_fila_do_painel_com_link_para_configuracoes(self):
        itens = painel.fila(config.ler_config())
        achado = [i for i in itens if "backup" in i["titulo"].lower()]
        self.assertTrue(achado)
        self.assertEqual(achado[0]["link"], "#/config")


# ======================================================================================================================
# 4. Restauração (nunca apaga nada)
# ======================================================================================================================
class TesteRestaurar(BaseBackup):
    def setUp(self):
        super().setUp()
        self.nome = backup.fazer_backup(agora=dia(20))["nome"]
        p = config.PROJETOS_CLAUDE / SLUG_A
        amb.apagar(p / "sessao0.jsonl")                                       # falta hoje
        amb.apagar(p / "memory" / "fato.md")                                  # memória que falta
        (p / "sessao1.jsonl").write_text("mudado por outra pessoa\n", encoding="utf-8")       # diferente
        with open(p / "sessao2.jsonl", "a", encoding="utf-8") as f:           # só cresceu depois do backup
            f.write(amb.linha_usuario("nova mensagem"))
        (p / "so_hoje.jsonl").write_text("conversa nova, não está no backup\n", encoding="utf-8")

    def test_plano_mostra_o_que_mudaria_por_projeto_sem_escrever_nada(self):
        antes = sorted(str(x) for x in config.PROJETOS_CLAUDE.rglob("*"))
        pl = backup.plano(self.nome)
        self.assertEqual(sorted(x for x in (str(y) for y in config.PROJETOS_CLAUDE.rglob("*"))), antes)
        g = {x["grupo"]: x for x in pl["grupos"]}
        self.assertEqual(sorted(i["arq"].split("/")[-1] for i in g[SLUG_A]["faltam"]), ["fato.md", "sessao0.jsonl"])
        self.assertEqual([i["arq"].split("/")[-1] for i in g[SLUG_A]["diferentes"]], ["sessao1.jsonl"])
        self.assertEqual([i["arq"].split("/")[-1] for i in g[SLUG_A]["cresceram"]], ["sessao2.jsonl"])
        self.assertEqual(g[SLUG_B]["faltam"] + g[SLUG_B]["diferentes"], [])

    def test_sem_confirmacao_nao_restaura(self):
        with self.assertRaises(backup.BackupErro):
            backup.restaurar(self.nome)
        with self.assertRaises(backup.BackupErro):
            backup.restaurar(self.nome, confirmar="sim")
        self.assertFalse((config.PROJETOS_CLAUDE / SLUG_A / "sessao0.jsonl").exists())

    def test_restaura_o_que_falta_e_nao_apaga_nem_troca_nada(self):
        p = config.PROJETOS_CLAUDE / SLUG_A
        r = backup.restaurar(self.nome, confirmar=True)
        self.assertEqual(len(r["copiados"]), 2)
        self.assertEqual(r["trocados"], [])
        self.assertTrue((p / "sessao0.jsonl").is_file())
        self.assertTrue((p / "memory" / "fato.md").is_file())
        self.assertEqual((p / "sessao1.jsonl").read_text(encoding="utf-8"), "mudado por outra pessoa\n")       # não marcado: fica
        self.assertIn("nova mensagem", (p / "sessao2.jsonl").read_text(encoding="utf-8"))                       # cresceu: fica
        self.assertTrue((p / "so_hoje.jsonl").is_file())                                                       # não está no backup: fica
        self.assertFalse(any(x.name.endswith(".restaurando") for x in p.rglob("*")))
        self.assertEqual(backup.plano(self.nome)["totais"]["faltam"], 0)

    def test_troca_so_o_marcado_e_guarda_a_versao_de_hoje_antes(self):
        p = config.PROJETOS_CLAUDE / SLUG_A
        arc = f"claude/projects/{SLUG_A}/sessao1.jsonl"
        r = backup.restaurar(self.nome, confirmar=True, trocar=[arc, f"claude/projects/{SLUG_A}/sessao2.jsonl"])
        self.assertEqual(r["trocados"], [arc])                               # o que só cresceu nunca é trocado
        self.assertIn("oi", (p / "sessao1.jsonl").read_text(encoding="utf-8"))
        guarda = Path(r["copias"]).joinpath(*arc.split("/"))
        self.assertTrue(Path(r["copias"]).resolve().is_relative_to((config.CASA / "copias").resolve()))
        self.assertEqual(guarda.read_text(encoding="utf-8"), "mudado por outra pessoa\n")

    def test_so_um_projeto_ou_so_a_memoria(self):
        r = backup.restaurar(self.nome, confirmar=True, so_memoria=True)
        self.assertEqual([x.split("/")[-1] for x in r["copiados"]], ["fato.md"])
        self.assertFalse((config.PROJETOS_CLAUDE / SLUG_A / "sessao0.jsonl").exists())
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_B / "sessao0.jsonl")
        r = backup.restaurar(self.nome, confirmar=True, projeto="Blog")         # trecho do slug
        self.assertEqual([x.split("/")[-1] for x in r["copiados"]], ["sessao0.jsonl"])
        self.assertTrue(all(SLUG_B in x for x in r["copiados"]))
        with self.assertRaises(backup.BackupErro):
            backup.plano(self.nome, projeto="NaoExiste")

    def test_sem_a_casa_do_cerebro_a_copia_vai_para_a_pasta_de_backup(self):
        amb.apagar(config.CASA)
        try:
            arc = f"claude/projects/{SLUG_A}/sessao1.jsonl"
            r = backup.restaurar(self.nome, confirmar=True, trocar=[arc])
            self.assertTrue(Path(r["copias"]).resolve().is_relative_to((self.base / "copias").resolve()))
            self.assertIn("restauracao-", r["copias"])
            self.assertTrue((config.CASA / "projetos" / SLUG_A / "decisoes.jsonl").is_file())      # dados do Cérebro voltaram
            self.assertNotIn("copias", [s["nome"] for s in backup.listar(self.base)[0]])
        finally:
            config.garantir_casa()

    def test_snapshot_adulterado_nao_restaura_nada(self):
        caminho = self.base / self.nome
        with zipfile.ZipFile(caminho) as zin:
            itens = {n: zin.read(n) for n in zin.namelist()}
        itens[f"claude/projects/{SLUG_A}/sessao0.jsonl"] = b"trocado"
        ruim = self.base / "2026-10-19.zip"
        with zipfile.ZipFile(ruim, "w") as zout:
            for n, d in itens.items():
                zout.writestr(n, d)
        with self.assertRaises(backup.BackupErro):
            backup.restaurar("2026-10-19.zip", confirmar=True)
        self.assertFalse((config.PROJETOS_CLAUDE / SLUG_A / "sessao0.jsonl").exists())

    def test_nome_malicioso_no_zip_nunca_sai_da_pasta(self):
        ruim = self.base / "2026-10-18.zip"
        conteudo = b"invasor"
        import hashlib
        sha = hashlib.sha256(conteudo).hexdigest()
        arcs = ["claude/projects/../../fora.txt", "claude/projects/C:/x.txt", "outra/coisa.txt", "/abs.txt"]
        with zipfile.ZipFile(ruim, "w") as zf:
            for a in arcs:
                zf.writestr(a, conteudo)
            zf.writestr(backup.MANIFESTO, json.dumps({"arquivos": [{"arq": a, "tam": len(conteudo), "sha256": sha} for a in arcs],
                                                      "total_arquivos": 4, "total_bytes": 28}))
        pl = backup.plano("2026-10-18.zip")
        self.assertEqual(pl["totais"]["faltam"], 0)
        r = backup.restaurar("2026-10-18.zip", confirmar=True)
        self.assertEqual(r["copiados"], [])
        self.assertFalse((amb.BASE / "fora.txt").exists())
        self.assertFalse((config.CLAUDE / "fora.txt").exists())


# ======================================================================================================================
# 5. Agendador de Tarefas (schtasks falso)
# ======================================================================================================================
@unittest.skipUnless(os.name == "nt", "o agendamento é do Windows")
class TesteAgendador(unittest.TestCase):
    def setUp(self):
        amb.garantir_isolamento()
        self.falso = amb.AgendadorFalso()
        self.troca = mock.patch.object(agendador, "EXECUTAR", self.falso)
        self.troca.start()

    def tearDown(self):
        self.troca.stop()

    def test_teste_nunca_usa_o_agendador_real(self):
        self.assertIsInstance(agendador.EXECUTAR, amb.AgendadorFalso)
        with self.assertRaises(agendador.AgendadorErro):
            agendador._executar_de_verdade(["schtasks", "/Query"])

    def test_ligar_cria_tarefa_no_prefixo_sem_senha_sem_admin_e_sem_janela(self):
        e = agendador.ligar("backup", {"hora": "12:30"})
        self.assertTrue(e["ligada"])
        criar = next(c for c in self.falso.chamadas if c[1] == "/Create")
        self.assertTrue(Path(criar[0]).is_absolute() and criar[0].lower().endswith("\\system32\\schtasks.exe"), criar[0])
        self.assertEqual(criar[1:3], ["/Create", "/TN"])
        self.assertEqual(criar[3], "CerebroDoProjeto\\backup")
        for proibido in ("/RU", "/RP", "/RL", "/IT"):
            self.assertNotIn(proibido, criar)
        xml = self.falso.tarefas["CerebroDoProjeto\\backup"]
        for trecho in ("<StartWhenAvailable>true</StartWhenAvailable>", "<LogonTrigger>", "<LogonType>InteractiveToken</LogonType>",
                       "<RunLevel>LeastPrivilege</RunLevel>", "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
                       "T12:30:00</StartBoundary>", 'cerebro_cli.py" rotina backup</Arguments>'):
            self.assertIn(trecho, xml)
        self.assertNotIn("<Password>", xml)
        self.assertEqual(xml.split("<Command>")[1].split("</Command>")[0], str(agendador.python_das_rotinas()))
        self.assertEqual(config.ler_config()["rotinas_windows"]["backup"], {"hora": "12:30"})

    def test_intervalos_de_cada_rotina(self):
        agendador.ligar("analise", {"hora": "13:00", "dias": 3})
        agendador.ligar("mapa", {"hora": "08:00", "horas": 4})
        self.assertIn("<DaysInterval>3</DaysInterval>", self.falso.tarefas["CerebroDoProjeto\\analise"])
        self.assertNotIn("<LogonTrigger>", self.falso.tarefas["CerebroDoProjeto\\analise"])
        self.assertIn("<Interval>PT4H</Interval>", self.falso.tarefas["CerebroDoProjeto\\mapa"])
        for ruim in ({"hora": "25:00"}, {"hora": "12:30", "dias": 0}, {"hora": "12:30", "dias": True}):
            with self.assertRaises(ValueError):
                agendador.ligar("analise", ruim)

    def test_nada_fora_do_prefixo(self):
        with self.assertRaises(agendador.AgendadorErro):
            agendador.nome_tarefa("Microsoft")
        n = len(self.falso.chamadas)
        for nome in ("Microsoft\\Windows\\Defrag", "CerebroDoProjeto\\..\\Outra", "CerebroDoProjeto\\qualquer", "\\Outra"):
            with self.assertRaises(agendador.AgendadorErro):
                agendador._schtasks("/Delete", "/TN", nome, "/F")
        self.assertEqual(len(self.falso.chamadas), n)            # nenhum comando chegou ao schtasks

    def test_estado_desligar_e_remover_todas_so_do_prefixo(self):
        self.assertFalse(agendador.estado("novidades")["ligada"])
        agendador.ligar("backup")
        agendador.ligar("novidades")
        e = agendador.estado("backup")
        self.assertEqual((e["proxima"], e["situacao"]), ("30/10/2026 12:30:00", "Pronto"))
        self.assertEqual(sorted(agendador.listar_do_prefixo()), ["CerebroDoProjeto\\backup", "CerebroDoProjeto\\novidades"])
        self.assertTrue(agendador.desligar("backup"))
        self.assertFalse(agendador.desligar("backup"))
        self.assertEqual(agendador.remover_todas(), ["CerebroDoProjeto\\novidades"])
        apagadas = [c for c in self.falso.chamadas if c[1] == "/Delete"]
        self.assertTrue(all(c[3].startswith("CerebroDoProjeto\\") for c in apagadas))

    def test_recusa_do_agendador_vira_erro_explicado(self):
        self.falso.falhar = True
        with self.assertRaises(agendador.AgendadorErro):
            agendador.ligar("backup")


# ======================================================================================================================
# 6. Rotinas (o que a tarefa roda) e log
# ======================================================================================================================
class TesteRotinas(BaseBackup):
    def test_rotina_backup_registra_log_e_ultimo_resultado(self):
        r = rotinas_windows.executar("backup")
        self.assertTrue(r["ok"], r)
        self.assertTrue((config.CASA / "rotinas" / "backup.log").is_file())
        self.assertEqual(rotinas_windows.ultimo("backup")["ok"], True)
        r2 = rotinas_windows.executar("backup")                 # segunda vez no dia (ao fazer logon): pula
        self.assertIn("já existe", r2["texto"])

    def test_erro_vai_para_o_log_e_nao_levanta(self):
        def quebra():
            raise RuntimeError("deu ruim")
        r = rotinas_windows.executar("analise", fazer=quebra)
        self.assertFalse(r["ok"])
        self.assertIn("deu ruim", (config.CASA / "rotinas" / "analise.log").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            rotinas_windows.executar("formatar_disco")

    def test_log_rotativo(self):
        log = config.CASA / "rotinas" / "novidades.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("x" * (rotinas_windows.LIMITE_LOG + 10), encoding="utf-8")
        rotinas_windows.executar("novidades", fazer=lambda: (True, "ok"))
        self.assertTrue(log.with_name("novidades.log.1").is_file())
        self.assertLess(log.stat().st_size, 1000)

    def test_mapa_nunca_chama_graphify_com_ia(self):
        from cerebro import mapa_auto
        chamadas = []
        with mock.patch.dict(os.environ, {}), mock.patch.object(mapa_auto, "varrer", lambda forcar=False: chamadas.append(forcar) or []), \
             mock.patch("subprocess.run", side_effect=AssertionError("nenhum programa externo na rotina do mapa")):
            r = rotinas_windows.executar("mapa")
            self.assertEqual(os.environ.get("GRAPHIFY_BACKEND"), "none")
        self.assertTrue(r["ok"], r)
        self.assertEqual(chamadas, [True])

    def test_analise_roda_para_cada_projeto_visivel_e_o_cerebro(self):
        from cerebro import analise, projetos
        feitos = []
        falsos = [{"slug": "a", "oculto": False}, {"slug": "b", "oculto": True}, {"slug": "c", "oculto": False}]
        with mock.patch.object(projetos, "descobrir", lambda forcar=False: falsos), \
             mock.patch.object(analise, "executar", lambda slug, cfg: feitos.append(slug) or {"resumo": {"novas": 0}}):
            r = rotinas_windows.executar("analise")
        self.assertTrue(r["ok"])
        self.assertEqual(feitos, ["a", "c", "_cerebro"])

    def test_situacao_para_a_pagina(self):
        with mock.patch.object(agendador, "EXECUTAR", amb.AgendadorFalso()):
            s = rotinas_windows.situacao()
        self.assertEqual([r["rotina"] for r in s["rotinas"]], list(agendador.ROTINAS))
        self.assertEqual(s["rotinas"][0]["parametros"]["hora"], "12:30")


# ======================================================================================================================
# 7. Linha de comando
# ======================================================================================================================
class TesteCLI(BaseBackup):
    def rodar(self, *args):
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = cerebro_cli.main(list(args))
        return codigo, saida.getvalue() + erro.getvalue()

    def test_backup_listar_restaurar_sem_e_com_confirmar(self):
        codigo, txt = self.rodar("backup")
        self.assertEqual(codigo, 0)
        self.assertIn("Nenhum backup feito ainda", txt)
        codigo, txt = self.rodar("backup", "--agora")
        self.assertEqual(codigo, 0)
        self.assertIn("Backup feito", txt)
        hoje = time.strftime("%Y-%m-%d")
        amb.apagar(config.PROJETOS_CLAUDE / SLUG_A / "memory" / "fato.md")
        codigo, txt = self.rodar("backup", "--restaurar", hoje, "--so-memoria")
        self.assertIn("Nada foi escrito", txt)
        self.assertFalse((config.PROJETOS_CLAUDE / SLUG_A / "memory" / "fato.md").exists())
        codigo, txt = self.rodar("backup", "--restaurar", hoje, "--so-memoria", "--confirmar")
        self.assertEqual(codigo, 0, txt)
        self.assertTrue((config.PROJETOS_CLAUDE / SLUG_A / "memory" / "fato.md").exists())
        codigo, txt = self.rodar("backup", "--conferir", hoje)
        self.assertEqual(codigo, 0)
        self.assertIn("confere", txt)
        codigo, txt = self.rodar("backup", "--restaurar", "1999-01-01")
        self.assertEqual(codigo, 2)

    @unittest.skipUnless(os.name == "nt", "o agendamento é do Windows")
    def test_agendar_e_rotina(self):
        falso = amb.AgendadorFalso()
        with mock.patch.object(agendador, "EXECUTAR", falso):
            codigo, txt = self.rodar("agendar", "backup", "--ligar", "--hora", "07:15")
            self.assertEqual(codigo, 0, txt)
            self.assertIn("T07:15:00", falso.tarefas["CerebroDoProjeto\\backup"])
            codigo, txt = self.rodar("agendar", "backup", "--estado")
            self.assertIn("LIGADA", txt)
            codigo, txt = self.rodar("agendar", "backup", "--ligar", "--hora", "99:99")
            self.assertEqual(codigo, 2)
            codigo, txt = self.rodar("agendar", "backup", "--desligar")
            self.assertIn("Tarefa removida", txt)
        codigo, txt = self.rodar("rotina", "backup")
        self.assertEqual(codigo, 0, txt)


# ======================================================================================================================
# 8. Desinstalador
# ======================================================================================================================
class TesteDesinstalarBackup(BaseBackup):
    def setUp(self):
        super().setUp()
        self.raiz = amb.BASE / "desinstalacao-bk"
        self.raiz.mkdir(parents=True, exist_ok=True)
        amb.apagar(ganchos_claude.caminho_settings())          # settings.json de mentira sem nada do Cérebro: sem pergunta a mais
        backup.fazer_backup(agora=dia(20))
        self.falso = amb.AgendadorFalso()
        self.troca = mock.patch.object(agendador, "EXECUTAR", self.falso)
        self.troca.start()
        if os.name == "nt":
            agendador.ligar("backup")
        self.saida = []

    def tearDown(self):
        self.troca.stop()
        config.garantir_casa()

    def rodar(self, *args, entrada=()):
        respostas = iter(entrada)
        return desinstalar.main(list(args) + ["--sem-encerrar"], entrada=lambda _p="": next(respostas, ""), saida=self.saida.append, raiz=self.raiz)

    def test_sim_e_apagar_dados_nao_apagam_o_backup(self):
        self.rodar("--sim", "--apagar-dados")
        self.assertEqual(len(self.snapshots()), 1)
        texto = "\n".join(self.saida)
        self.assertIn("Backups mantidos", texto)
        if os.name == "nt":
            self.assertEqual(self.falso.tarefas, {})                   # --sim tira as tarefas do Cérebro
            self.assertIn("CerebroDoProjeto\\backup", texto)

    def test_backup_so_sai_com_sim_explicito_na_pergunta_propria(self):
        self.rodar("--manter-dados", entrada=["n", "s"] if os.name == "nt" else ["s"])     # tarefas: não; backup: sim
        self.assertFalse(amb.BACKUP.exists())
        if os.name == "nt":
            self.assertIn("CerebroDoProjeto\\backup", self.falso.tarefas)   # respondeu "n" às tarefas: ficam


# ======================================================================================================================
# 9. Rotas
# ======================================================================================================================
class TesteRotasBackup(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        amb.apagar(amb.BACKUP)
        self.falso = amb.AgendadorFalso()
        self.troca = mock.patch.object(agendador, "EXECUTAR", self.falso)
        self.troca.start()

    async def asyncTearDown(self):
        self.troca.stop()
        await super().asyncTearDown()

    async def test_precisam_de_cookie_origin_e_json(self):
        for c in ("/api/backup", "/api/rotinas/windows"):
            self.assertEqual((await self.http.get(self.base + c)).status, 401)
        await self.entrar()
        self.assertEqual((await self.post("/api/backup/agora", {}, origem=False)).status, 403)
        self.assertEqual((await self.http.post(self.base + "/api/backup/agora", data="x", headers={"Origin": self.base})).status, 415)
        self.assertEqual((await self.http.get(self.base + "/static/backup.js")).status, 200)

    async def test_fazer_ver_plano_e_restaurar_com_confirmacao(self):
        await self.entrar()
        r = await self.post("/api/backup/agora", {})
        self.assertEqual(r.status, 200, await r.text())
        nome = (await r.json())["nome"]
        d = await (await self.http.get(self.base + "/api/backup")).json()
        self.assertEqual(d["snapshots"][0]["nome"], nome)
        arq = config.PROJETOS_CLAUDE / self.slug / "memory" / "regra.md"
        amb.apagar(arq)
        pl = await (await self.post("/api/backup/plano", {"snapshot": nome})).json()
        self.assertEqual(pl["totais"]["faltam"], 1)
        self.assertNotIn("abc12345xyz", json.dumps(pl))
        self.assertEqual((await self.post("/api/backup/restaurar", {"snapshot": nome})).status, 400)
        self.assertFalse(arq.exists())
        r = await self.post("/api/backup/restaurar", {"snapshot": nome, "confirmar": True})
        self.assertEqual((await r.json())["copiados"], 1)
        self.assertTrue(arq.exists())
        self.assertEqual((await self.post("/api/backup/plano", {"snapshot": "../../x.zip"})).status, 404)
        self.assertTrue((await (await self.post("/api/backup/conferir", {"snapshot": nome})).json())["ok"])

    @unittest.skipUnless(os.name == "nt", "o agendamento é do Windows")
    async def test_ligar_e_desligar_rotina_pela_pagina(self):
        await self.entrar()
        r = await self.post("/api/rotinas/windows", {"rotina": "backup", "acao": "ligar", "hora": "12:30"})
        self.assertEqual(r.status, 200, await r.text())
        self.assertIn("CerebroDoProjeto\\backup", self.falso.tarefas)
        self.assertEqual((await self.post("/api/rotinas/windows", {"rotina": "Microsoft", "acao": "desligar"})).status, 400)
        self.assertEqual((await self.post("/api/rotinas/windows", {"rotina": "backup", "acao": "ligar", "hora": "x"})).status, 409)
        r = await self.post("/api/rotinas/windows", {"rotina": "backup", "acao": "desligar"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.falso.tarefas, {})


if __name__ == "__main__":
    unittest.main()
