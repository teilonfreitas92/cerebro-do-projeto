# Como contribuir

Obrigado por querer ajudar o Cérebro do Projeto! Correções, ideias, testes e textos mais claros são bem-vindos. Este guia explica como
preparar o ambiente, rodar os testes e o que nunca pode acontecer num teste.

Ao participar, você concorda com o [Código de Conduta](CODE_OF_CONDUCT.md).

## Antes de começar

- **Problema ou ideia?** Abra uma *issue* pelos modelos (Problema ou Ideia). **Não cole conversas do Claude Code, memória, caminhos com
  o seu nome nem segredos** (chaves, tokens, senhas). Se precisar mostrar algo, recorte e troque nomes por exemplos.
- **Falha de segurança?** Não abra issue pública: siga o [SECURITY.md](SECURITY.md).
- **Mudança grande?** Abra uma issue antes para combinar o caminho; assim ninguém perde trabalho.

## Preparar o ambiente

Requisitos: Python 3.11 ou mais novo (a verificação automática usa o 3.12) e Git.

```
git clone <endereço do seu fork>
cd cerebro-do-projeto
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt ruff==0.17.1
```

Para ver o painel funcionando sem nenhum dado seu: `python demo/rodar_demo.py --abrir` (dados inventados em `demo/saida`).

## Rodar os testes e o ruff

```
python -m unittest discover -s testes -t . -p "test_*.py"
ruff check .
```

- A suíte imprime primeiro as pastas que vai usar: confira que estão dentro de `~/.cerebro-testes`. Se não estiverem, ela aborta.
- No Windows, se algum teste parecer esperar o teclado, rode com a entrada fechada: `... -p "test_*.py" < NUL` (no Git Bash, `< /dev/null`).
- `python testes/ci_instalador.py` (ou `--rapido`) prova o instalador num "PC limpo" de mentira.
- O GitHub roda tudo isso sozinho em cada envio e pull request, no Windows e no Linux (`.github/workflows/testes.yml`). O pull request
  só entra com tudo verde.
- O `ruff.toml` liga só as regras que apontam erro de verdade; não precisa formatar o arquivo inteiro.

## Regras de segurança dos testes (obrigatórias)

Estas regras existem porque um teste mal isolado pode apagar as conversas e a memória de quem roda a suíte. Um pull request que quebre
qualquer uma delas não entra.

1. **Todo teste importa o pacote `testes`** (`from testes import _ambiente`). Ele aponta `CEREBRO_HOME`, `CEREBRO_CLAUDE`,
   `CEREBRO_BACKUP` e o `settings.json` do Claude Code para pastas temporárias em `~/.cerebro-testes/t_*`.
2. **Nunca tocar** em `~/.claude`, `~/.cerebro`, no `settings.json` real, no Agendador de Tarefas, no registro do Windows, na rede,
   e nunca rodar `claude`, `pip`, `winget`, `cargo`, `npm` ou `schtasks` de verdade. Todo programa externo é chamado por uma função
   própria do módulo, que o teste troca por uma falsa (mock).
3. **Nunca apagar fora da pasta temporária do teste.** Nos testes, só `testes/_ambiente.apagar()`; no código do app, só
   `config.remover()` / `config.remover_em()`, que têm as travas. Nada de `shutil.rmtree`, `os.remove` ou `Path.unlink` direto.
4. Precisa de uma pasta sensível nova? Crie uma variável de ambiente para ela, isole em `testes/_ambiente.py` e cubra com a trava
   `garantir_isolamento()`.
5. **Dados de teste e fotos são sempre fictícios.** Nada de transcrição, nome, e-mail ou caminho real (o `test_portatil` procura isso
   em todos os arquivos do repositório). Use amostras sintéticas ou a demonstração (`demo/`).

## Regras do próprio app

- Rota nova exige a chave da página (cookie), como as outras; `POST` exige `Origin` da própria página e JSON.
- Texto de conversa ou memória passa por `segredos.mascarar()` antes de ir para a tela; a tela usa `textContent`, nunca `innerHTML` com dado.
- Servidor só em `127.0.0.1`. Comando externo: sem shell, lista de argumentos, tempo limite, sem janela.
- Escrever fora de `~/.cerebro` (memória, `settings.json`, projeto, Agendador) só com confirmação na página ou `--confirmar` na CLI,
  sempre com prévia da diferença, cópia de segurança antes, escrita atômica e **sem apagar** o que existe.
- Detalhes em [docs/referencia.md](docs/referencia.md#segurança).

## Estilo

- **Tudo em português do Brasil**: nomes, comentários e textos de tela. A tela é para quem não programa: frases curtas, sem jargão.
- Siga o código vizinho: funções pequenas, comentários na densidade dos arquivos ao lado, nomes em português.
- Python sem dependências novas sem conversar antes (as versões ficam fixas no `requirements.txt`). Front-end em JavaScript puro, sem build.
- Mudou algo que a pessoa vê? Atualize o guia **Como usar** (`web/guia.js`), o `README.md` e, se for técnico, o `docs/referencia.md`.
  Anote no `CHANGELOG.md`.
- Mensagens de commit em português, dizendo o que mudou e por quê.

## Pull request

1. Crie um ramo a partir do `main`.
2. Faça a mudança com testes.
3. Rode a suíte e o `ruff check .`.
4. Abra o pull request preenchendo o modelo (o que muda, como testou, o que escreve fora de `~/.cerebro`).

Obrigado!
