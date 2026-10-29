"""Sessão gestora "mesma sessão + limpeza": vigia e recado uma vez, `gestora limpar` (capítulo conferido), SessionStart clear/compact
(corrente e config), capítulos, retenção estreita das transcrições antigas (muitas recusas), ganchos e instalador.
Tudo com settings.json, sessões e JSONL FALSOS em pasta temporária."""
import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import backup, bastao, capitulos, config, ganchos_claude, gestora_troca, ligacoes, retencao_gestora

sys.path.insert(0, str(amb.RAIZ))
import cerebro_cli  # noqa: E402
import cerebro_hook  # noqa: E402

DIA = 86400
NOVA = "11111111-2222-3333-4444-555555555555"
VELHA = amb.GESTORA_ID


class Base(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        amb.apagar(amb.BACKUP)
        retencao_gestora._conferidos.clear()

    def tearDown(self):
        self.desmontar_mundo()

    def ges(self):
        return config.ler_config()["gestoras"][self.slug]["conversa"]

    def escrever_conversa(self, sid, primeira, leitura=1000):
        arq = self.pasta_claude / f"{sid}.jsonl"
        arq.write_text(amb.linha_usuario(primeira) + amb.linha_assistente("n-" + sid[:4], leitura=leitura), encoding="utf-8")
        return arq

    def gestora_cheia(self, leitura=125_000):
        (self.pasta_claude / f"{VELHA}.jsonl").write_text(
            amb.linha_usuario("Gerencie o projeto") + amb.linha_assistente("g2", leitura=leitura,
                                                                           conteudo=[{"type": "text", "text": "Feito o login; falta o relatório."}]),
            encoding="utf-8")

    def corrente(self):
        return json.loads((config.pasta_projeto(self.slug) / "corrente.json").read_text(encoding="utf-8"))

    def elos(self):
        return {e["conversa"]: e for e in self.corrente()["elos"]}

    def evento_inicio(self, sid, fonte="clear"):
        return {"hook_event_name": "SessionStart", "source": fonte, "session_id": sid,
                "transcript_path": str(self.pasta_claude / f"{sid}.jsonl"), "cwd": str(self.real)}


# ======================================================================================================================
class TesteVigiaERecado(Base):
    def setUp(self):
        super().setUp()
        config.atualizar_config(lambda c: c.setdefault("gestora_rotacao", {}).update(ativo=True))   # limpeza é opcional: liga aqui

    def test_limpeza_desligada_por_padrao_nao_manda_recado(self):
        config.atualizar_config(lambda c: c["gestora_rotacao"].update(ativo=False))
        self.gestora_cheia()
        self.assertIsNone(gestora_troca.recado_limite(self.slug, VELHA))

    def ev(self, sid=VELHA):
        return {"evento": "UserPromptSubmit", "slug": self.slug, "session_id": sid}

    def test_contexto_lido_do_fim_do_jsonl(self):
        self.gestora_cheia(125_000)
        v = gestora_troca.vigia(self.slug)
        self.assertTrue(v["longa"])
        self.assertGreaterEqual(v["pct"], 60)

    def test_abaixo_do_limite_nao_diz_nada(self):
        self.assertFalse(gestora_troca.vigia(self.slug)["longa"])
        self.assertIsNone(gestora_troca.recado_limite(self.slug, VELHA))

    def test_recado_uma_vez_por_transcricao_e_so_na_gestora(self):
        self.gestora_cheia()
        r = ligacoes._aviso_manual(self.ev())
        self.assertIn("Contexto em 6", r)
        self.assertIn(f"cerebro_cli.py gestora limpar {self.slug}", r)
        self.assertIn('clear_session com session_id "self"', r)
        self.assertIn("Vou limpar a conversa agora", r)                                  # avisa o dono antes de limpar
        self.assertIn("Mande qualquer mensagem", r)                                      # diz como continuar
        self.assertNotIn("Contexto em", ligacoes._aviso_manual(self.ev()) or "")          # já entregue para esta transcrição
        self.assertIsNone(ligacoes._aviso_manual(self.ev("outra-sessao")))
        self.assertEqual(ganchos_eventos_resposta(self.ev(), r)["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_limite_configuravel_e_desligavel(self):
        self.gestora_cheia(50_000)                                        # 25%
        self.assertIsNone(gestora_troca.recado_limite(self.slug, VELHA))
        config.atualizar_config(lambda c: c["gestora_rotacao"].update(limite_pct=20))
        config.atualizar_config(lambda c: c["gestora_rotacao"].update(ativo=False))
        self.assertIsNone(gestora_troca.recado_limite(self.slug, VELHA))
        config.atualizar_config(lambda c: c["gestora_rotacao"].update(ativo=True))
        self.assertIsNotNone(gestora_troca.recado_limite(self.slug, VELHA))

    def test_aviso_de_conversa_longa_do_bastao_pula_a_gestora(self):
        self.gestora_cheia(150_000)
        cfg = config.ler_config()
        with mock.patch.object(bastao, "sessoes_longas", return_value=[{"sessao": VELHA, "titulo": "g", "contexto": 150_000, "pct": 75}]):
            self.assertEqual(bastao.itens_fila({"slug": self.slug, "nome": "Falso"}, cfg), [])


def ganchos_eventos_resposta(ev, texto):
    from cerebro import ganchos_eventos
    return ganchos_eventos.resposta_para({"evento": "UserPromptSubmit", **ev}, [texto])


# ======================================================================================================================
class TesteLimpar(Base):
    def test_limpar_grava_capitulo_conferido_e_deixa_pendente(self):
        self.gestora_cheia()
        r = gestora_troca.limpar(self.slug)
        texto = Path(r["capitulo"]).read_text(encoding="utf-8")
        self.assertEqual(gestora_troca.conferir_capitulo(texto), [])
        self.assertIn("falta o relatório", texto)
        self.assertEqual(self.corrente()["limpezas"][0]["conversa"], VELHA)

    def test_cli_ok_e_nao_limpe(self):
        self.gestora_cheia()
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(cerebro_cli.main(["gestora", "limpar", self.slug]), 0)
        self.assertTrue(s.getvalue().startswith("OK"))
        with mock.patch.object(capitulos, "montar", return_value="# só o título\n"):
            with redirect_stdout(io.StringIO()) as s:
                self.assertEqual(cerebro_cli.main(["gestora", "limpar", self.slug]), 2)
        self.assertIn("NÃO limpe", s.getvalue())
        config.atualizar_config(lambda c: c["gestoras"].pop(self.slug))
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(cerebro_cli.main(["gestora", "limpar", self.slug]), 2)
        self.assertIn("NÃO limpe", s.getvalue())


# ======================================================================================================================
class TesteSessionStart(Base):
    def test_clear_com_limpeza_pendente_troca_a_transcricao(self):
        self.gestora_cheia()
        r = gestora_troca.limpar(self.slug)
        self.escrever_conversa(NOVA, "oi")
        saida = json.loads(cerebro_hook.sincrono(json.dumps(self.evento_inicio(NOVA)).encode(), config.CASA))
        ctx = saida["hookSpecificOutput"]["additionalContext"]
        self.assertIn("GESTOR.md", ctx)
        self.assertIn("falta o relat", ctx)
        self.assertEqual(self.ges(), NOVA)
        self.assertEqual(config.ler_config()["gestoras"][self.slug]["nome"], "Gestora de teste")
        e = self.elos()
        self.assertEqual(e[NOVA]["estado"], "atual")
        self.assertEqual(e[VELHA]["estado"], "anterior")
        self.assertEqual(e[VELHA]["capitulo"], os.path.basename(r["capitulo"]))
        self.assertIsNotNone(e[VELHA]["fim"])
        self.assertEqual(self.corrente()["limpezas"], [])

    def test_clear_manual_com_gestora_ativa_e_capitulo_gravado_depois(self):
        self.gestora_cheia()
        self.escrever_conversa(NOVA, "oi")
        self.assertTrue(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA)) is not None)
        self.assertEqual(self.ges(), NOVA)
        self.assertTrue(self.elos()[VELHA]["capitulo_pendente"])
        ligacoes._ao_iniciar({"evento": "SessionStart", "slug": self.slug, "session_id": NOVA})
        e = self.elos()[VELHA]
        self.assertNotIn("capitulo_pendente", e)
        self.assertTrue(capitulos.caminho(self.slug, e["capitulo"]).is_file())

    def test_clear_de_outra_sessao_com_gestora_parada_nao_mexe(self):
        t = time.time() - 600
        os.utime(self.pasta_claude / f"{VELHA}.jsonl", (t, t))
        self.escrever_conversa(NOVA, "oi")
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA)), "")
        self.assertEqual(self.ges(), VELHA)

    def test_pendente_nao_vale_se_a_gestora_continuou_trabalhando(self):
        self.gestora_cheia()
        gestora_troca.limpar(self.slug, agora=time.time() - 3600)
        t = time.time() - 600                         # a transcrição antiga cresceu 50 min DEPOIS do capítulo: não houve limpeza
        os.utime(self.pasta_claude / f"{VELHA}.jsonl", (t, t))
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA)), "")

    def test_proxima_mensagem_horas_depois_ainda_completa_a_limpeza(self):
        # no app, a conversa nova só nasce quando o dono manda a próxima mensagem (pode ser horas depois)
        self.gestora_cheia()
        quando = time.time() - 5 * 3600
        gestora_troca.limpar(self.slug, agora=quando)
        os.utime(self.pasta_claude / f"{VELHA}.jsonl", (quando + 60, quando + 60))   # o turno terminou e a antiga parou
        self.escrever_conversa(NOVA, "oi")
        self.assertIn("GESTOR.md", gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA)))
        self.assertEqual(self.ges(), NOVA)
        self.assertEqual(self.elos()[VELHA]["estado"], "anterior")

    def test_app_abre_a_conversa_nova_como_startup(self):
        # caso real de 29/10: depois do clear_session, o app do Claude abre a conversa nova com source "startup"
        self.gestora_cheia()
        gestora_troca.limpar(self.slug)
        self.escrever_conversa(NOVA, "oi")
        saida = json.loads(cerebro_hook.sincrono(json.dumps(self.evento_inicio(NOVA, "startup")).encode(), config.CASA))
        self.assertIn("GESTOR.md", saida["hookSpecificOutput"]["additionalContext"])
        # pedido do dono: a gestora avisa, logo na primeira resposta, que a conversa foi limpa e que ele pode prosseguir
        self.assertIn("Pode prosseguir", saida["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.ges(), NOVA)
        self.assertEqual(self.elos()[VELHA]["estado"], "anterior")

    def test_startup_sem_limpeza_pendente_nao_mexe_mesmo_com_gestora_ativa(self):
        self.gestora_cheia()                          # gestora mexida agora, mas sem limpeza pedida: é uma sessão nova comum
        self.escrever_conversa(NOVA, "oi")
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA, "startup")), "")
        self.assertEqual(self.ges(), VELHA)

    def test_pendente_de_mais_de_um_dia_nao_vale(self):
        self.gestora_cheia()
        quando = time.time() - 25 * 3600
        gestora_troca.limpar(self.slug, agora=quando)
        os.utime(self.pasta_claude / f"{VELHA}.jsonl", (quando + 60, quando + 60))
        self.escrever_conversa(NOVA, "oi")
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA)), "")
        self.assertEqual(self.ges(), VELHA)
        self.assertEqual(self.ges(), VELHA)

    def test_compact_so_na_gestora_e_outros_eventos_nada(self):
        capitulos.gravar(self.slug, VELHA)
        self.assertIn("GESTOR.md", gestora_troca.ao_iniciar_sessao(self.evento_inicio(VELHA, "compact")))
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA, "compact")), "")
        self.assertEqual(gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA, "startup")), "")
        self.assertEqual(cerebro_hook.sincrono(json.dumps(self.evento_inicio(NOVA, "resume")).encode(), config.CASA), "")
        self.assertEqual(self.ges(), VELHA)

    def test_outro_projeto_nao_mexe(self):
        self.gestora_cheia()
        gestora_troca.limpar(self.slug)
        ev = self.evento_inicio(NOVA)
        ev["transcript_path"] = str(config.PROJETOS_CLAUDE / "C--outro" / f"{NOVA}.jsonl")
        self.assertEqual(gestora_troca.ao_iniciar_sessao(ev), "")
        self.assertEqual(self.ges(), VELHA)


# ======================================================================================================================
class TesteCapitulos(Base):
    def test_precompact_grava_capitulo_so_da_gestora(self):
        outra = "99999999-8888-7777-6666-555555555555"
        self.escrever_conversa(outra, "sessão comum")
        ligacoes._ao_compactar({"evento": "PreCompact", "slug": self.slug, "session_id": outra})
        self.assertEqual(capitulos.listar(self.slug), [])
        ligacoes._ao_compactar({"evento": "PreCompact", "slug": self.slug, "session_id": VELHA})
        caps = capitulos.listar(self.slug)
        self.assertEqual(len(caps), 1)
        self.assertRegex(caps[0]["nome"], r"^\d{4}-\d{2}-\d{2}_\d{6}_aaaaaaaa\.md$")

    def test_contexto_curto(self):
        caminho = capitulos.pasta(self.slug) / "2026-10-29_120000_aaaaaaaa.md"
        caminho.write_text("# Capítulo\n\n" + "x" * 20000 + "\n" + capitulos.FIM_RESUMO + "\nresto", encoding="utf-8")
        t = capitulos.texto_contexto(config.CASA, self.slug)
        self.assertIn("GESTOR.md", t)
        self.assertLessEqual(len(t), capitulos.LIMITE_CONTEXTO_CHARS)
        self.assertNotIn("resto", t)

    def test_retencao_padrao_nunca_apaga(self):
        caminho = capitulos.pasta(self.slug) / "2001-01-01_000000_aaaaaaaa.md"
        caminho.write_text("# velho\n" + capitulos.FIM_RESUMO, encoding="utf-8")
        capitulos.gravar(self.slug, VELHA)
        self.assertTrue(caminho.is_file())
        config.atualizar_config(lambda c: c["capitulos"].update(manter_dias=30))
        self.assertEqual(capitulos.girar(self.slug), ["2001-01-01_000000_aaaaaaaa.md"])


# ======================================================================================================================
class TesteRetencao(Base):
    """Apagar estreito: só elo 'anterior' do mesmo projeto, 7+ dias, backup mais novo conferido com o mesmo sha256, autorizado."""

    def setUp(self):
        super().setUp()
        self.agora = time.time()
        antes = self.agora - 10 * DIA
        self.gestora_cheia()
        self.criar_subagente("s1", "busca", idade_s=11 * DIA)
        gestora_troca.limpar(self.slug, agora=antes)
        self.escrever_conversa(NOVA, "oi")
        gestora_troca.ao_iniciar_sessao(self.evento_inicio(NOVA), agora=antes + 60)
        t = antes - DIA
        os.utime(self.pasta_claude / f"{VELHA}.jsonl", (t, t))
        self.arq = self.pasta_claude / f"{VELHA}.jsonl"
        self.sub = self.pasta_claude / VELHA

    def backup_e_autorizar(self, quando=None):
        backup.fazer_backup(agora=quando or self.agora - DIA)
        retencao_gestora.autorizar(self.slug, confirmar=True)

    def recusa(self, conversa=VELHA, slug=None):
        with self.assertRaises(retencao_gestora.ApagarRecusado):
            retencao_gestora.apagar(slug or self.slug, conversa, agora=self.agora)
        self.assertTrue(self.arq.is_file())

    def test_caminho_feliz_apaga_so_a_transcricao_e_os_subagentes(self):
        self.backup_e_autorizar()
        self.assertEqual([c["conversa"] for c in retencao_gestora.candidatos(self.slug, agora=self.agora)], [VELHA])
        r = retencao_gestora.apagar(self.slug, VELHA, agora=self.agora)
        self.assertEqual(r["arquivos"], 3)                       # jsonl + agent-s1.jsonl + agent-s1.meta.json
        self.assertFalse(self.arq.exists())
        self.assertFalse(self.sub.exists())
        self.assertTrue((self.pasta_claude / f"{NOVA}.jsonl").is_file())
        self.assertTrue(capitulos.listar(self.slug))              # capítulos ficam
        self.assertEqual(self.elos()[VELHA]["estado"], "apagada")
        linha = json.loads((config.pasta_projeto(self.slug) / "apagamentos.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(linha["conversa"], VELHA)

    def test_sem_autorizacao_recusa(self):
        backup.fazer_backup(agora=self.agora - DIA)
        self.recusa()
        with self.assertRaises(retencao_gestora.ApagarRecusado):
            retencao_gestora.autorizar(self.slug)                # sem confirmar
        self.assertEqual(retencao_gestora.rodar(agora=self.agora, forcar=True), [])

    def test_menos_de_7_dias_recusa(self):
        self.backup_e_autorizar()
        self.agora -= 4 * DIA
        self.recusa()

    def test_a_atual_recusa(self):
        self.backup_e_autorizar()
        self.recusa(NOVA)

    def test_fora_da_corrente_recusa(self):
        solto = "22222222-3333-4444-5555-666666666666"
        self.escrever_conversa(solto, "solta")
        self.backup_e_autorizar()
        self.recusa(solto)
        self.assertTrue((self.pasta_claude / f"{solto}.jsonl").is_file())

    def test_outro_projeto_recusa(self):
        outro = config.PROJETOS_CLAUDE / "C--outro-projeto"
        outro.mkdir(parents=True)
        (outro / f"{VELHA}.jsonl").write_text("x\n", encoding="utf-8")
        self.backup_e_autorizar()
        retencao_gestora.autorizar("C--outro-projeto", confirmar=True)
        self.recusa(slug="C--outro-projeto")
        self.assertTrue((outro / f"{VELHA}.jsonl").is_file())

    def test_ponto_ponto_e_id_invalido_recusam(self):
        self.backup_e_autorizar()
        for ruim in ("../" + VELHA, VELHA + "/../x", "..", "not-a-uuid"):
            self.recusa(ruim)
        self.recusa(slug="..")

    def test_sha_diferente_recusa(self):
        self.backup_e_autorizar()
        with open(self.arq, "a", encoding="utf-8") as f:
            f.write(amb.linha_usuario("mudou depois do backup"))
        self.recusa()

    def test_subagente_novo_fora_do_backup_recusa(self):
        self.backup_e_autorizar()
        (self.sub / "subagents" / "agent-s9.jsonl").write_text("novo\n", encoding="utf-8")
        self.recusa()

    def test_backup_nao_conferido_recusa(self):
        self.backup_e_autorizar()
        with mock.patch.object(backup, "conferir", return_value={"ok": False, "problemas": ["x"], "conferidos": 0}):
            self.recusa()

    def test_sem_backup_ou_backup_mais_novo_sem_o_arquivo_recusa(self):
        retencao_gestora.autorizar(self.slug, confirmar=True)
        self.recusa()                                            # nenhum backup
        backup.fazer_backup(agora=self.agora - 2 * DIA)
        man_sem = {"versao": 1, "criado_em": self.agora - DIA, "arquivos": [], "total_arquivos": 0, "total_bytes": 0, "falhas": []}
        with mock.patch.object(backup, "ler_manifesto", return_value=man_sem):
            self.recusa()

    def test_link_ou_juncao_recusa(self):
        self.backup_e_autorizar()
        original = retencao_gestora._eh_link
        with mock.patch.object(retencao_gestora, "_eh_link", side_effect=lambda p: p.name == f"{VELHA}.jsonl" or original(p)):
            self.recusa()
        with mock.patch.object(retencao_gestora, "_eh_link", side_effect=lambda p: p.name == VELHA or original(p)):
            self.recusa()
        with mock.patch.object(retencao_gestora, "_eh_link", side_effect=lambda p: p.name == "projects" or original(p)):
            self.recusa()

    def test_rotina_e_cli_com_autorizacao(self):
        backup.fazer_backup(agora=self.agora - DIA)
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(cerebro_cli.main(["gestora", "limpeza", self.slug]), 0)
        self.assertIn("pode sair", s.getvalue())
        self.assertTrue(self.arq.is_file())                      # listar não apaga
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cerebro_cli.main(["gestora", "limpeza", self.slug, "--autorizar"]), 2)     # sem --confirmar
        self.assertTrue(self.arq.is_file())
        retencao_gestora.autorizar(self.slug, confirmar=True)
        with mock.patch("cerebro.projetos.descobrir", return_value=[{"slug": self.slug}]):
            feitos = retencao_gestora.rodar(agora=self.agora, forcar=True)
        self.assertEqual([f["conversa"] for f in feitos], [VELHA])
        self.assertEqual(retencao_gestora.rodar(agora=self.agora + 60), [])          # no máximo 1 vez por dia


# ======================================================================================================================
class TesteTrocaPelaCli(Base):
    """Alternativa fora do padrão: troca por sessão nova do app (preparar/trocar com a marca)."""

    def test_marca_achada_atualiza_config_e_corrente(self):
        r = gestora_troca.preparar(self.slug)
        self.assertTrue(r["texto"].startswith(f"[cerebro-bastao:{r['marca']}]"))
        self.escrever_conversa(NOVA, f"{r['marca_texto']}\n\nVocê é a NOVA sessão gestora...")
        t = gestora_troca.trocar(self.slug, r["marca"], sessao_app="local_nova1", sessao_app_antiga="local_velha1")
        self.assertTrue(t["feito"])
        self.assertEqual(self.ges(), NOVA)
        e = self.elos()
        self.assertEqual((e[NOVA]["estado"], e[VELHA]["estado"], e[VELHA]["sessao_app"]), ("atual", "anterior", "local_velha1"))

    def test_pendente_completado_e_marca_fora_da_primeira_mensagem(self):
        r = gestora_troca.preparar(self.slug)
        (self.pasta_claude / f"{NOVA}.jsonl").write_text(amb.linha_usuario("outra") + amb.linha_usuario(r["marca_texto"]), encoding="utf-8")
        self.assertTrue(gestora_troca.trocar(self.slug, r["marca"])["pendente"])
        self.assertEqual(self.ges(), VELHA)
        self.escrever_conversa(NOVA, r["texto"])
        gestora_troca.completar_pendentes(self.slug)
        self.assertEqual(self.ges(), NOVA)
        with self.assertRaises(ValueError):
            gestora_troca.trocar(self.slug, "0123456789")


# ======================================================================================================================
class TesteGanchosEInstalador(unittest.TestCase):
    def test_um_grupo_clear_compact_sincrono_e_sai_junto(self):
        d = ganchos_claude.mesclar_hooks({}, ganchos_claude.entrada_hook("comando"))
        d = ganchos_claude.mesclar_sincrono(ganchos_claude.mesclar_sincrono(d))
        grupos = [g for g in d["hooks"]["SessionStart"] if g.get("matcher") == "startup|clear|compact"]
        self.assertEqual(len(grupos), 1)
        h = grupos[0]["hooks"][0]
        self.assertEqual(h["timeout"], 5)
        self.assertNotIn("async", h)
        self.assertIn("--sincrono", h["command"])
        self.assertNotIn("SessionStart", ganchos_claude.tirar_hooks(d).get("hooks", {}))

    def test_instalar_so_liga_os_ganchos_com_o_sim_na_hora(self):
        import instalar
        settings = ganchos_claude.caminho_settings()
        amb.apagar(settings)
        ditos = []
        ins = instalar.Instalador(amb.RAIZ, entrada=lambda _p="": "n", saida=ditos.append)
        self.assertFalse(ins.oferecer_ganchos())
        self.assertFalse(settings.exists())
        self.assertIn("hooks", "\n".join(ditos))                  # mostrou a diferença antes de perguntar
        self.assertFalse(instalar.Instalador(amb.RAIZ, entrada=lambda _p="": "s", saida=ditos.append, sim=True).oferecer_ganchos())
        self.assertFalse(settings.exists())                        # --sim não responde pela pessoa
        self.assertTrue(instalar.Instalador(amb.RAIZ, entrada=lambda _p="": "s", saida=ditos.append).oferecer_ganchos())
        self.assertIn("--sincrono", settings.read_text(encoding="utf-8"))
        ganchos_claude.remover(confirmar=True)


# ======================================================================================================================
from testes.test_servidor import Base as BaseServidor  # noqa: E402


class TesteRotas(BaseServidor):
    async def test_rotas_exigem_cookie_corrente_autorizar_e_manual(self):
        r = await self.http.get(f"{self.base}/api/p/{self.slug}/gestora/corrente")
        self.assertEqual(r.status, 401)
        await self.entrar()
        amb.apagar(config.pasta_projeto(self.slug) / "corrente.json")
        config.atualizar_config(lambda c: c["gestoras"].__setitem__(self.slug, {"conversa": "sessA", "nome": "Gestora"}))
        config.atualizar_config(lambda c: c["gestora_rotacao"].__setitem__("apagar_autorizado", {}))
        d = await (await self.http.get(f"{self.base}/api/p/{self.slug}/gestora/corrente")).json()
        self.assertEqual(d["vigia"]["conversa"], "sessA")
        self.assertEqual(d["elos"][-1]["estado"], "atual")
        self.assertFalse(d["autorizado"])
        r = await self.post(f"/api/p/{self.slug}/gestora/autorizar", {"ligar": True}, origem=False)
        self.assertEqual(r.status, 403)
        r = await self.post(f"/api/p/{self.slug}/gestora/autorizar", {"ligar": True})
        self.assertEqual(r.status, 409)                      # sem confirmar
        r = await self.post(f"/api/p/{self.slug}/gestora/autorizar", {"ligar": True, "confirmar": True})
        self.assertTrue((await r.json())["autorizado"])
        r = await self.post(f"/api/p/{self.slug}/gestora/autorizar", {"ligar": False})
        self.assertFalse((await r.json())["autorizado"])
        r = await self.http.get(f"{self.base}/api/p/{self.slug}/gestora/capitulo?nome=../config.json")
        self.assertEqual(r.status, 400)
        r = await self.post(f"/api/p/{self.slug}/gestora/preparar", {})
        self.assertEqual(r.status, 404)                      # a troca por sessão nova não está na página
        m = await (await self.http.get(f"{self.base}/api/gestor/manual")).json()
        self.assertTrue(m["existe"])                         # gerado ao subir o servidor
        amb.apagar(self.real / "CLAUDE.local.md")
        pv = await (await self.http.get(f"{self.base}/api/p/{self.slug}/manual")).json()
        self.assertEqual(pv["acao"], "instalar")
        r = await self.post(f"/api/p/{self.slug}/manual", {"acao": "instalar", "assinatura": pv["assinatura"]})
        self.assertEqual(r.status, 409)
        r = await self.post(f"/api/p/{self.slug}/manual", {"acao": "instalar", "assinatura": pv["assinatura"], "confirmar": True})
        self.assertEqual(r.status, 200)
        self.assertTrue((self.real / "CLAUDE.local.md").is_file())
        self.assertEqual((await self.http.get(f"{self.base}/static/gestora.js")).status, 200)


if __name__ == "__main__":
    unittest.main()
