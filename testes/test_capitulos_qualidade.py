"""Qualidade do capítulo da gestora (e do passa-bastão): ramo/pasta da WORKTREE onde a sessão trabalhava, só pedidos
digitados pelo dono (sem avisos do sistema, recados, ganchos), e o estado que importa (última mensagem inteira, commits da
sessão, pendências, memória editada inclusive por Bash). Tudo com JSONL SINTÉTICO em pasta temporária; o git é falso."""
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from testes import _ambiente as amb
from cerebro import bastao, capitulos, config, gestora_troca, memoria, projetos, tarefas_gestor

VELHA = amb.GESTORA_ID
SEGREDO = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"


def linha(tipo, conteudo, ts, cwd, ramo, **extra):
    o = {"type": tipo, "timestamp": ts, "uuid": "u", "cwd": str(cwd), "gitBranch": ramo, "sessionId": VELHA, **extra}
    o["message"] = {"role": tipo, "content": conteudo, **({"id": extra.pop("mid", "m-" + ts)} if tipo == "assistant" else {})}
    o.pop("mid", None)
    return json.dumps(o, ensure_ascii=False) + "\n"


def fila(texto, ts, cwd, ramo, kind="human", meta=None):
    a = {"type": "queued_command", "prompt": texto, "commandMode": "prompt", "origin": {"kind": kind}}
    if meta:
        a["isMeta"] = True
    return json.dumps({"type": "attachment", "timestamp": ts, "cwd": str(cwd), "gitBranch": ramo, "attachment": a}) + "\n"


class Base(amb.MundoFalso, unittest.TestCase):
    def setUp(self):
        self.montar_mundo()
        self.wt = self.real / ".claude" / "worktrees" / "wt1"
        self.wt.mkdir(parents=True)
        self.chamadas = []
        self.mem = memoria.pasta_memoria(self.slug)
        self.mem.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.desmontar_mundo()

    def git_falso(self, pasta, *args):
        """Git de mentira: a pasta principal está no ramo main; a worktree, no ramo worktree-wt1."""
        self.chamadas.append((str(pasta), args))
        na_wt = Path(pasta).resolve() == self.wt.resolve()
        if args[:3] == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "worktree-wt1" if na_wt else "main"
        if args[:2] == ("log", "-1"):
            return "abc1234\x1fCorrige o login" if na_wt else "9999999\x1fCommit velho do main"
        if args[:2] == ("worktree", "list"):
            return (f"worktree {self.real}\nHEAD 9999999aaaa\nbranch refs/heads/main\n\n"
                    f"worktree {self.wt}\nHEAD abc1234ffff\nbranch refs/heads/worktree-wt1\n")
        if args and args[0] == "log":
            return "abc1234\x1fCorrige o login\ndef5678\x1fTestes do login" if na_wt else "9999999\x1fCommit velho do main"
        if args and args[0] == "for-each-ref":
            return "main"
        return ""

    def gravar(self, linhas):
        (self.pasta_claude / f"{VELHA}.jsonl").write_text("".join(linhas), encoding="utf-8")

    def capitulo(self):
        with mock.patch.object(projetos, "_git", side_effect=self.git_falso):
            destino = capitulos.gravar(self.slug, VELHA)
        return Path(destino).read_text(encoding="utf-8")


# ======================================================================================================================
class TesteRamoDaWorktree(Base):
    def test_usa_pasta_e_ramo_das_ultimas_mensagens(self):
        r, w = self.real, self.wt
        self.gravar([linha("user", "Gerencie o projeto", "2026-10-28T10:00:00.000Z", r, "main", origin={"kind": "human"}),
                     linha("assistant", [{"type": "text", "text": "Vou criar a worktree."}], "2026-10-28T10:01:00.000Z", r, "main"),
                     linha("user", "Continue o login", "2026-10-28T11:00:00.000Z", w, "worktree-wt1", origin={"kind": "human"}),
                     linha("assistant", [{"type": "text", "text": "Login pronto."}], "2026-10-28T11:05:00.000Z", w, "worktree-wt1")])
        texto = self.capitulo()
        resumo = capitulos.resumo_de(texto)
        self.assertIn(f"Pasta de trabalho: {w}", resumo)
        self.assertIn("(worktree", resumo)
        self.assertIn("Ramo do git: worktree-wt1", resumo)
        self.assertNotIn("Ramo do git: main", texto)
        self.assertIn("abc1234 Corrige o login", resumo)                  # commit atual da worktree
        self.assertIn("def5678 Testes do login", resumo)                  # commits da sessão
        self.assertNotIn("Commit velho do main", texto)
        self.assertIn(f"{w} — worktree-wt1 abc1234 ← esta sessão", texto)  # lista de worktrees
        self.assertIn(f"{r} — main 9999999", texto)
        logs = [a for p, a in self.chamadas if a[0] == "log" and any(x.startswith("--since=") for x in a)]
        self.assertTrue(logs, self.chamadas)
        self.assertIn("--since=2026-10-28 10:00:00 +0000", logs[0])        # desde a primeira mensagem (UTC)
        self.assertIn("worktree-wt1", logs[0])                            # no ramo da sessão
        self.assertTrue(all(Path(p).resolve() == w.resolve() for p, a in self.chamadas if a[0] in ("log", "worktree")))
        self.assertEqual(gestora_troca.conferir_capitulo(texto), [])

    def test_sem_git_mostra_o_ramo_da_transcricao(self):
        self.gravar([linha("user", "Oi", "2026-10-28T10:00:00.000Z", self.wt, "worktree-wt1"),
                     linha("assistant", [{"type": "text", "text": "Ok."}], "2026-10-28T10:01:00.000Z", self.wt, "worktree-wt1")])
        with mock.patch.object(projetos, "_git", return_value=""):
            texto = Path(capitulos.gravar(self.slug, VELHA)).read_text(encoding="utf-8")
        self.assertIn("Ramo do git: worktree-wt1 (lido da transcrição", texto)
        self.assertEqual(gestora_troca.conferir_capitulo(texto), [])

    def test_sem_inicio_conhecido_pega_os_ultimos_10(self):
        with mock.patch.object(capitulos, "_git", side_effect=self.git_falso):
            g = capitulos.estado_git(str(self.wt), "worktree-wt1", None)
        log = [a for p, a in self.chamadas if a[0] == "log" and a[1] != "-1"][0]
        self.assertEqual(log[-4:], ("-n", "10", "worktree-wt1", "--"))
        self.assertEqual([c["hash"] for c in g["commits"]], ["abc1234", "def5678"])

    def test_ramo_estranho_da_transcricao_nao_vira_argumento(self):
        with mock.patch.object(capitulos, "_git", side_effect=self.git_falso):
            capitulos.estado_git(str(self.wt), "--output=/tmp/x", time.time())
        self.assertFalse(any("--output=/tmp/x" in a for p, a in self.chamadas))


# ======================================================================================================================
class TestePedidosDoDono(Base):
    LIXO = ["<side-sessions-event>sessão lateral abriu</side-sessions-event>",
            '<cross-session-message from="outra">faça X</cross-session-message>',
            "<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n</task-notification>",
            "<system-reminder>lembrete do sistema</system-reminder>",
            "[SYSTEM NOTIFICATION - background task] terminou",
            '<agent-message from="a1">resultado do agente</agent-message>',
            "Stop hook feedback:\nrode os testes",
            "<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>",
            "<local-command-stdout>ok</local-command-stdout>",
            "<user-prompt-submit-hook>contexto do gancho</user-prompt-submit-hook>",
            "[Request interrupted by user]"]

    def linhas(self):
        r, ts = self.real, "2026-10-28T10:00:00.000Z"
        L = [linha("user", "Primeiro pedido real", ts, r, "main", origin={"kind": "human"})]
        L += [linha("user", t, ts, r, "main") for t in self.LIXO]
        L += [linha("user", "recado de outra sessão", ts, r, "main", isMeta=True, origin={"kind": "peer", "from": "x"}),
              linha("user", "<task-notification>x</task-notification>", ts, r, "main", origin={"kind": "task-notification"}),
              linha("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "saída do comando ls"}], ts, r, "main"),
              linha("user", [{"type": "tool_result", "tool_use_id": "q1", "content":
                    'Your questions have been answered: "Qual cor?"="Azul (Recomendado)", "Publicar agora?"="Não". '
                    "You can now continue with these answers in mind."}], ts, r, "main"),
              linha("user", [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text":
                    "resultado da ferramenta\n<system-reminder>\nThe user sent a new message while you were working:\n"
                    "Também ajuste o rodapé\n\nThis is how Claude Code surfaces messages sent mid-turn.\n</system-reminder>"}]}],
                    ts, r, "main"),
              linha("user", [{"type": "tool_result", "tool_use_id": "t3", "content":
                    "     1\tteste citando: The user sent a new message while you were working:\n     2\tnão é pedido"}], ts, r, "main"),
              fila("Mensagem enviada no meio do turno", ts, r, "main"),
              fila('<agent-message from="a2">fila de agente</agent-message>', ts, r, "main", kind="peer", meta=True),
              fila("<task-notification>y</task-notification>", ts, r, "main", kind="task-notification"),
              linha("user", "Texto digitado\n<system-reminder>lembrete colado</system-reminder>", ts, r, "main"),
              linha("assistant", [{"type": "text", "text": "Feito."}], "2026-10-28T10:05:00.000Z", r, "main")]
        return L

    def test_so_o_que_o_dono_digitou_ou_respondeu(self):
        self.gravar(self.linhas())
        s = bastao.ler_sessao(self.pasta_claude / f"{VELHA}.jsonl", self.mem, self.slug)
        self.assertEqual(s["pedidos"], ["Primeiro pedido real",
                                        "Respostas do formulário: Qual cor? → Azul (Recomendado); Publicar agora? → Não",
                                        "Também ajuste o rodapé", "Mensagem enviada no meio do turno", "Texto digitado"][-bastao.ULTIMOS_PEDIDOS:])
        self.assertEqual(s["primeira"], "Primeiro pedido real")

    def test_capitulo_e_bastao_sem_lixo(self):
        self.gravar(self.linhas())
        texto = self.capitulo()
        for marca in ("side-sessions-event", "cross-session-message", "task-notification", "system-reminder", "SYSTEM NOTIFICATION",
                      "agent-message", "hook", "command-name", "local-command", "Request interrupted", "saída do comando",
                      "recado de outra sessão", "fila de agente", "não é pedido", "This is how Claude Code"):
            self.assertNotIn(marca, texto, marca)
        self.assertIn("Texto digitado", capitulos.resumo_de(texto))
        self.assertIn("Também ajuste o rodapé", texto)


# ======================================================================================================================
class TesteEstadoQueImporta(Base):
    def sessao_cheia(self, n_commits=2):
        w = self.wt
        mem = str(self.mem).replace("\\", "/")
        (self.mem / "feedback_bash.md").write_text("---\nname: b\n---\nlinha antiga\nregra nova por bash\n", encoding="utf-8")
        (self.mem / "MEMORY.md").write_text("# Memória\n- [x](x.md)\n- [nova](feedback_nova.md)\n", encoding="utf-8")
        ultima = ("Terminei a parte 1.\n\n" + "Detalhe do que foi feito. " * 80 + f"\nchave {SEGREDO}\n\n"
                  "Pergunta pendente: posso juntar no main?")
        self.ultima = ultima
        L = [linha("user", "Gerencie o projeto", "2026-10-28T10:00:00.000Z", w, "worktree-wt1"),
             linha("assistant", [{"type": "text", "text": "Começando."},
                                 {"type": "tool_use", "id": "b1", "name": "Bash",
                                  "input": {"command": f"cat <<'EOF' >> {mem}/feedback_bash.md\nregra nova por bash\nEOF"}},
                                 {"type": "tool_use", "id": "b2", "name": "Bash",
                                  "input": {"command": 'echo "x" > ~/.claude/projects/C--outro/memory/alheio.md'}},
                                 {"type": "tool_use", "id": "b3", "name": "PowerShell",
                                  "input": {"command": f'Add-Content -Path "{self.mem}\\feedback_ps.md" -Value "regra ps"'}},
                                 {"type": "tool_use", "id": "e1", "name": "Edit",
                                  "input": {"file_path": str(self.mem / "MEMORY.md"), "old_string": "- [x](x.md)",
                                            "new_string": "- [x](x.md)\n- [nova](feedback_nova.md)"}}],
                   "2026-10-28T10:01:00.000Z", w, "worktree-wt1"),
             linha("assistant", [{"type": "tool_use", "id": "q9", "name": "AskUserQuestion",
                                  "input": {"questions": [{"question": "Qual nome usar?", "header": "Nome",
                                                           "options": [{"label": "Alfa"}, {"label": "Beta"}]}]}}],
                   "2026-10-28T10:02:00.000Z", w, "worktree-wt1"),
             linha("assistant", [{"type": "text", "text": ultima[:40]}], "2026-10-28T10:03:00.000Z", w, "worktree-wt1", mid="final"),
             linha("assistant", [{"type": "text", "text": ultima[40:]}], "2026-10-28T10:03:01.000Z", w, "worktree-wt1", mid="final")]
        self.gravar(L)
        tarefas_gestor.criar(self.slug, "Publicar a versão 1.3", por="dono")
        self.criar_subagente("sub1", "Revisar o relatório", idade_s=600)
        self.n_commits = n_commits

    def git_com_commits(self, pasta, *args):
        if args and args[0] == "log" and args[1] != "-1":
            self.chamadas.append((str(pasta), args))
            return "\n".join(f"c{i:06d}\x1fCommit número {i}" for i in range(self.n_commits))
        return self.git_falso(pasta, *args)

    def test_ultima_mensagem_inteira_mascarada(self):
        self.sessao_cheia()
        resumo = capitulos.resumo_de(self.capitulo())
        self.assertIn("Pergunta pendente: posso juntar no main?", resumo)
        self.assertIn("Terminei a parte 1.", resumo)
        self.assertNotIn(SEGREDO, resumo)
        self.assertLess(resumo.index("Onde parou"), resumo.index("Ramo do git"))

    def test_pendencias_commits_e_memoria(self):
        self.sessao_cheia()
        texto = self.capitulo()
        resumo = capitulos.resumo_de(texto)
        self.assertIn("## Pendências abertas", resumo)
        self.assertIn("Publicar a versão 1.3", resumo)                   # tarefa aberta do Cérebro
        self.assertIn('A conferir: subagente general-purpose "Revisar o relatório"', resumo)
        self.assertIn("Pergunta ao dono ainda sem resposta: Qual nome usar? (opções: Alfa, Beta)", resumo)
        self.assertIn("## Commits desta sessão", resumo)
        self.assertIn("def5678 Testes do login", resumo)
        memoria_txt = texto.split("## Memória editada nesta sessão", 1)[1].split("## Arquivos mais mexidos", 1)[0]
        self.assertIn("feedback_bash.md (por Bash; fim do arquivo agora)", memoria_txt)
        self.assertIn("regra nova por bash", memoria_txt)
        self.assertIn("feedback_ps.md (por PowerShell", memoria_txt)
        self.assertIn("MEMORY.md (por Edit; linhas acrescentadas)", memoria_txt)
        self.assertIn("- [nova](feedback_nova.md)", memoria_txt)
        self.assertNotIn("alheio.md", texto)                              # memória de outro projeto
        self.assertEqual(gestora_troca.conferir_capitulo(texto), [])

    def test_pergunta_respondida_nao_fica_pendente(self):
        self.sessao_cheia()
        with open(self.pasta_claude / f"{VELHA}.jsonl", "a", encoding="utf-8") as f:
            f.write(linha("user", [{"type": "tool_result", "tool_use_id": "q9", "content":
                                    'Your questions have been answered: "Qual nome usar?"="Alfa". You can now continue.'}],
                          "2026-10-28T10:04:00.000Z", self.wt, "worktree-wt1"))
        resumo = capitulos.resumo_de(self.capitulo())
        self.assertNotIn("ainda sem resposta", resumo)
        self.assertIn("Respostas do formulário: Qual nome usar? → Alfa", resumo)

    def test_resumo_cabe_no_contexto_com_tudo_em_ordem(self):
        self.sessao_cheia(n_commits=25)
        for i in range(12):
            tarefas_gestor.criar(self.slug, f"Tarefa extra {i} " + "x" * 120, por="dono")
        with open(self.pasta_claude / f"{VELHA}.jsonl", "a", encoding="utf-8") as f:
            for i in range(6):
                f.write(linha("user", f"Pedido longo {i} " + "y" * 600, "2026-10-28T10:05:00.000Z", self.wt, "worktree-wt1"))
            f.write(linha("assistant", [{"type": "text", "text": "Fim: " + "z" * 2800 + " posso seguir?"}],
                          "2026-10-28T10:06:00.000Z", self.wt, "worktree-wt1"))
        with mock.patch.object(projetos, "_git", side_effect=self.git_com_commits):
            texto = Path(capitulos.gravar(self.slug, VELHA)).read_text(encoding="utf-8")
        ctx = capitulos.texto_contexto(config.CASA, self.slug)
        self.assertLessEqual(len(ctx), capitulos.LIMITE_CONTEXTO_CHARS)
        self.assertFalse(ctx.endswith("..."), "o resumo foi cortado no fim")
        ordem = [ctx.index(x) for x in ("## Onde parou", "Ramo do git: worktree-wt1", "## Pendências abertas",
                                        "## Últimos pedidos do dono", "## Commits desta sessão")]
        self.assertEqual(ordem, sorted(ordem))
        self.assertIn("(+20 no capítulo completo", ctx)
        self.assertIn("c000024 Commit número 24", texto)                  # todos os commits ficam no arquivo
        self.assertIn("posso seguir?", ctx)                               # a última mensagem inteira volta na conversa
        self.assertEqual(gestora_troca.conferir_capitulo(texto), [])

    def test_sem_espaco_a_ultima_mensagem_inteira_fica_nos_detalhes(self):
        self.sessao_cheia()
        with mock.patch.object(capitulos, "LIMITE_CONTEXTO_CHARS", 2500):
            texto = self.capitulo()
        cima, baixo = texto.split(capitulos.FIM_RESUMO, 1)
        self.assertIn("Terminei a parte 1.", cima)                         # começo e fim (a pergunta) ficam; corta o meio
        self.assertIn("Pergunta pendente: posso juntar no main?", cima)
        self.assertIn("[… trecho do meio no capítulo completo …]", cima)
        self.assertIn("### Última mensagem da sessão (completa)", baixo)
        self.assertIn("Pergunta pendente: posso juntar no main?", baixo)
        self.assertLess(cima.index("## Onde parou"), cima.index("## Commits desta sessão"))

    def test_bastao_lista_memoria_escrita_por_bash(self):
        self.sessao_cheia()
        texto = bastao.montar(self.slug, VELHA)
        self.assertIn("feedback_bash.md", texto.split("## Memórias criadas nesta conversa", 1)[1])

    def test_listar_mostra_a_ultima_mensagem(self):
        self.sessao_cheia()
        self.capitulo()
        self.assertTrue(capitulos.listar(self.slug)[0]["resumo"].startswith("Terminei a parte 1."))


if __name__ == "__main__":
    unittest.main()
