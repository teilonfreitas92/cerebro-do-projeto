# Mudanças

Formato simples, em português. A versão atual fica em `cerebro/__init__.py`.

## Próxima versão

- **Janelas (terminal)**: mosaico de janelas de prompt lado a lado (ideia do MAESTRI). **Controle a sessão pelo painel**: o Cérebro
  abre o `claude` (sessão nova ou retomando uma) num terminal de verdade e você digita, aprova e interrompe ali, como no cmd.
  Janelas de leitura acompanham sozinhas os agentes que estão trabalhando. Nova dependência no Windows: `pywinpty`; o xterm.js
  6.0.0 vem junto (licença MIT, em NOTICE).
- **Outras IAs como subagentes**: o gestor manda OpenAI, DeepSeek, Grok ou Gemini fazer o serviço de um subagente
  (`python cerebro_cli.py ia rodar <projeto> --ia deepseek --tarefa "..."`). A IA trabalha numa cópia separada do projeto (git
  worktree), presa a ela e só com comandos permitidos; aparece em Agentes ao vivo; o gestor confere o diff e junta ou descarta.
  Chaves em Configurações › Outras IAs (só a conta do dono lê; fora do backup).
- **Agentes ao vivo com cara de terminal**: `>` pedido, `●` texto e ferramentas, `⎿` resultado, rodapé com "Trabalhando…".
- Cartão de título longo não alarga mais a coluna (Agentes ao vivo e Memória).

## 1.3.0 — cópia de segurança, agentes instantâneos e mais controle (29/10/2026)

Esta versão **escreve fora de `~/.cerebro` pela primeira vez** (conversas, memória, `settings.json` do Claude Code, arquivos do projeto).
Regra de tudo o que é novo: só com o seu clique (ou `--confirmar` na linha de comando), mostrando antes o que vai mudar, com cópia de
segurança antes e sem apagar nada do seu.

- **Backup e restauração**: um arquivo `.zip` por dia com as conversas e a memória de todos os projetos (e a pasta de dados do Cérebro),
  guardado fora de `.claude` e de `.cerebro` (padrão `~\CerebroBackup`, na pasta do usuário; nunca em AppData, que o Windows desvia para apps instalados como pacote). Guarda os 7 dias mais recentes, confere cada cópia
  (lista de arquivos com SHA-256) e protege a cópia boa se o backup novo vier bem menor (aviso até você liberar). **Restaurar** mostra o que
  falta, o que é diferente e o que só cresceu depois; copia de volta o que falta, troca o diferente só se você marcar (a versão de hoje vai
  antes para uma pasta de cópias) e nunca apaga. Na página (Configurações) e em `cerebro_cli.py backup`.
- **Rotinas no Windows**: backup, análise, novidades e mapa podem rodar sozinhos pelo Agendador de Tarefas, mesmo com o painel fechado
  (`cerebro_cli.py agendar` ou o botão "Ligar no Windows"). Só tarefas da pasta `CerebroDoProjeto`; se o PC estava desligado, roda assim
  que ligar. Cada rotina guarda um registro e o último resultado. O `desinstalar.py` pergunta antes de tirar as tarefas e, à parte
  (padrão NÃO), antes de apagar as cópias de segurança.
- **Memória mais forte**: editar, criar e arquivar memórias pela página (arquivar move para `memory/_arquivo/`, nunca apaga; se o Claude
  Code mexeu no arquivo enquanto você editava, recusa e pede para recarregar); **compactar o `MEMORY.md` sem IA** com verificador que
  garante que nenhuma regra some; **avisos de memória velha ou contraditória** (sempre "a conferir", nada muda sozinho); decisões ganham
  editar e arquivar (nenhuma linha é apagada); **passa-bastão**: aviso de conversa longa e botão que monta o resumo da sessão, sem IA.
- **Agentes ao vivo pelos ganchos + anéis de limite**: ligando os ganchos do Claude Code (com a sua aprovação), a aba Agentes passa a
  mostrar o estado na hora (trabalhando, parado, "usando X", "precisa de você") em vez de esperar a leitura dos arquivos. A statusLine
  do Cérebro alimenta os **anéis de limite de 5 horas e da semana**. O instalador mostra a diferença exata no `settings.json`, faz cópia
  antes, preserva o que já existe e desliga tudo com um clique. O receptor tem segredo próprio (`hooks_token`), separado da chave da página.
- **Avisos no Windows**: aviso na tela quando chega item a conferir na gestora, quando o Claude Code precisa de você e quando uma sessão
  longa termina. Liga/desliga geral e por tipo, "não perturbe" por horário, sem repetir o mesmo aviso e botão "Testar aviso".
- **Tarefas para o gestor**: crie tarefas na aba Tarefas ou no mapa ("Criar tarefa aqui", já com o ponto do código). Estados nova,
  recebida, em andamento, a conferir, feita e recusada, com histórico. O gestor recebe as tarefas novas sozinho como contexto da conversa
  (pelo gancho `UserPromptSubmit`; no modo padrão, que não atrasa o Claude Code, elas chegam na mensagem seguinte) ou pela CLI
  (`tarefas --novas`, `tarefa --estado`).
- **Orçamento**: limites opcionais em US$ por dia, semana e mês, por projeto e geral, com aviso (padrão 80%) e projeção do mês. Cartão na
  aba Custos e tela em Configurações. É estimativa pelo preço de lista; o Cérebro só avisa, nunca bloqueia. Estouro de limite vira aviso
  do Windows (no máximo 1 vez por dia).
- **Instalar ferramentas**: botão "Instalar…" para ruff, pip-audit, coverage, Semgrep, cargo-deny, gitleaks e Lighthouse, com receitas
  fechadas no código, comando exato mostrado antes, sem shell e com histórico. Novos comandos sugeridos de cobertura de testes.
- **Encaixe e agentes no projeto**: o plano de encaixe do Inventário agora pode ser **aplicado** (instruções no CLAUDE.md, agentes em
  `.claude/agents`, gitleaks no pre-commit, `ruff.toml`, Dependabot), sempre com prévia, só criando ou acrescentando, com cópia antes e
  botão **Desfazer**. Projetos ocultos, worktrees e a lista `nunca_escrever` são recusados.
- **Explicação por IA no mapa**: botão que pede ao Haiku uma frase simples para os pontos do mapa sem texto. Mostra a estimativa de gasto
  antes, tem limite por clique e botão Parar, e a frase aparece marcada como "explicação automática (IA)". Manda só um trecho curto,
  com segredos mascarados, e pula arquivos sensíveis pelo nome.
- **Verificação automática no GitHub**: roteiro (`.github/workflows/testes.yml`) que roda ruff, os testes e a prova do instalador num PC
  limpo, no Windows e no Linux, mais Dependabot semanal. Só funciona quando o repositório estiver no GitHub e **ainda não rodou lá**.
- **Pronto para repositório público**: README completo (para quem é, todas as funções com fotos, instalação passo a passo, o que
  mexe no PC, segurança, perguntas frequentes, limites, resumo em inglês), `CONTRIBUTING.md`, `SECURITY.md` (relato privado pelo
  GitHub), `CODE_OF_CONDUCT.md`, modelos de issue (Problema, Ideia; com aviso para não colar conversas nem segredos) e de pull request,
  selos locais (sem serviço externo). A demonstração (`demo/rodar_demo.py`) agora traz dados da 1.3 (tarefas, orçamento, avisos de
  memória, capítulos e corrente da gestora, explicações de exemplo no mapa e um backup), e as fotos novas e a apresentação
  (`docs/apresentacao`, 44 páginas, com dois gráficos de consumo medido e estimado num projeto real) mostram as funções da 1.3.
- **Painel no estilo dashboard**: barra lateral à esquerda (todos os projetos, lista de projetos com ponto de atividade e selo
  "a conferir", seções do projeto com contadores e "Precisa de você (N)", que abre uma gaveta), recolhível para ícones; área principal
  que cabe na tela sem rolar (abas internas, menu de seções e páginas numeradas no lugar da rolagem); o mapa ocupa o centro inteiro, com
  "Explicar com IA" numa gaveta e o controle "− Espaço +" para afastar as bolinhas. Em janela estreita, a barra lateral vira menu ☰.
  Todas as fotos do README e da apresentação foram refeitas com o visual novo (1366×768; celular em 390×844).
- **Conversa longa da gestora, sem toque do dono** (padrão): a gestora nunca é trocada. Quando o contexto enche, o Claude Code
  compacta sozinho; antes (`PreCompact`) o Cérebro grava um **capítulo** e logo depois (`SessionStart` "compact", síncrono, 5 s)
  devolve o resumo à gestora. A aba Sessões mostra a **corrente da gestora** (transcrições anterior → atual) e a **linha do tempo
  dos capítulos**. Capítulos e decisões ficam para sempre.
- **Limpeza na mesma sessão (opcional, desligada)**: liga em Configurações (`config.json` > `gestora_rotacao` > `ativo`). Passando
  de 60% de 200 mil tokens, a gestora recebe UMA vez o recado de avisar o dono, rodar `gestora limpar` (grava e confere o capítulo)
  e só então chamar `clear_session` (o app pede o ok). Vem desligada porque, testado com o app real, a conversa limpa só recomeça
  quando o dono manda uma mensagem. A conversa nova chega com `source` "startup" (não "clear"): o Cérebro só a trata como da
  gestora com limpeza pendente do projeto (vale 24 h, e só se a conversa antiga parou de ser escrita logo depois do capítulo). Na
  primeira resposta a gestora diz que a conversa foi limpa e que o dono pode prosseguir. O grupo síncrono do gancho usa o matcher
  "startup|clear|compact"; um `/clear` digitado funciona igual.
- **Cérebro no ar sempre que precisa**: ele não fecha sozinho enquanto chegam eventos dos ganchos (últimos 30 min), mesmo sem página
  aberta. Se estiver fechado (por exemplo, o PC reiniciou), o próprio gancho o liga em segundo plano, sem janela, no máximo 1 vez a
  cada 2 minutos e só se os ganchos estão configurados; o evento daquele instante se perde, os próximos chegam. O gancho só sobe o
  próprio Cérebro (programa fixo, sem shell).
- **Capítulo mais completo**: pasta de trabalho, ramo e commit vêm do `cwd` e do `gitBranch` das últimas mensagens (e as worktrees
  são listadas); "últimos pedidos do dono" traz só o que ele digitou (inclui respostas de formulário e mensagens enviadas no meio do
  turno; deixa de fora avisos do sistema, recados entre sessões e notificações). O capítulo traz também a última mensagem inteira da
  gestora (a pergunta pendente), as pendências abertas, os commits da sessão e a memória editada (inclusive por comandos do terminal).
- **Visto com o app real do Claude Code (29/10)**: ganchos, capítulo na compactação com o resumo devolvido, limpeza da gestora e o
  gancho que liga o Cérebro funcionaram. Falta ver a retenção de transcrições antigas contra conversas reais.
- **Transcrições antigas da gestora**: com a sua autorização (uma vez por projeto, botão na aba Sessões ou
  `gestora limpeza <projeto> --autorizar --confirmar`), a rotina apaga só as transcrições "anterior" do mesmo projeto com mais de
  7 dias que estão no backup mais novo, conferido e com o mesmo sha256. Trava própria e estreita (a trava geral continua recusando
  `.claude`); cada remoção fica em `apagamentos.jsonl`.
- **Ganchos recomendados**: o `instalar.py` e o primeiro uso (`#/bem-vindo`) oferecem "Ligar os ganchos (recomendado)", mostram
  o que muda no `settings.json` e só gravam com o seu sim na hora (cópia antes, mescla sem apagar, botão Desligar).
- **Manual do gestor automático** (`~/.cerebro/GESTOR.md`, menos de 1.500 tokens): comandos, delegação e revisão, e o que fazer em conversa longa.
  Refeito sozinho a cada versão; a página mostra "Cérebro atualizado" (fecha com um clique) e cada sessão gestora
  recebe o aviso uma vez. Em Configurações do projeto, "Manual do gestor neste projeto: Ligar/Desligar" põe (ou tira) um bloco
  no `CLAUDE.local.md` (recusa se o arquivo estiver no repositório; se não estiver ignorado, acrescenta-o ao `.git/info/exclude`).
- Para o gestor: leia o ~/.cerebro/GESTOR.md; ele é refeito a cada versão.
- Para o gestor: conversa longa, por padrão, segue pela compactação automática (sem toque); a limpeza é opcional: no recado de contexto alto, rode `gestora limpar <projeto>` e só com OK chame clear_session com session_id "self".
- Para o gestor: depois de uma limpeza ou compactação você recebe o resumo do último capítulo; confira o estado real antes de continuar.
- Para o gestor: a gestora nunca é trocada por outra sessão; a troca por start_session ficou só na CLI, fora do padrão.
- Para o gestor: tarefas novas do dono chegam sozinhas como contexto; marque o andamento com `tarefa --estado`.
- Versão do `config.json` e da documentação em 1.3.0.

## 1.2.0 — instalável por qualquer pessoa

- **Nada de uma pessoa específica no código**: caminhos, nomes de projeto, departamentos, comandos, portas e arquivo da statusLine saíram
  do programa. O que era "padrão de alguém" agora é configuração local (`~/.cerebro/config.json`), que não vai para o repositório.
- **Comandos sugeridos** (aba Ferramentas): o Cérebro lê o projeto (package.json, pytest/unittest, cargo, ruff, ESLint) e SUGERE comandos.
  Só entram na lista fechada se você aprovar na página; rodar continua exigindo o clique em "Rodar". Nada roda sozinho.
- **`instalar.py`** (um passo só: venv, dependências com versões fixas, Graphify opcional, pasta de dados, atalho, abrir o painel) e
  **`desinstalar.py`** (tira o atalho e o .venv; pergunta antes de apagar `~/.cerebro`). Os dois explicam cada passo e podem rodar de novo.
- **Primeiro uso guiado** na página (`#/bem-vindo`): seus projetos, sessão gestora, gerar o mapa (só com clique), comandos sugeridos, pronto.
- **Departamentos do mapa** configuráveis com regras por caminho, curinga ou regex (`re:`), cor e posição opcional; sem configuração, uma cor por
  pasta de topo. O mapa também funciona com a saída do `graphify update` (sem o arquivo de análise).
- **Multiplataforma**: Windows é o principal; nada quebra no macOS/Linux (token com chmod 600, `abrir_cerebro.sh`, sem `icacls`/`pythonw`/atalho fora do Windows).
- **Demonstração** com dados 100% fictícios: `python demo/rodar_demo.py`.
- Marca neutra (sem logotipo de terceiros), licença MIT, NOTICE com o crédito ao Graphify, README em português.
- Migração automática do `config.json` (versão 4): quem já usava mantém gestoras, comandos, preços e departamentos.

## 1.1.0

- Fila "a conferir" (revisão do gestor), registro de decisões e CLI do gestor (`cerebro_cli.py`).
- Aba Ferramentas de verdade (detecção só de leitura de 10 ferramentas, lista fechada de comandos com "Rodar", histórico de 20 execuções).
- "Analisar agora" (sem IA) com propostas e tarefas; vigia de novidades (só GET público); inventário com plano de encaixe.
- Agentes por tipo de tarefa (tipo → modelo → revisor) com prévia dos `.md`; departamentos do mapa por projeto; títulos melhores das sessões.
- O mapa se atualiza sozinho (vigia do `graph.json`); guia "Como usar" dentro do app.
- Segurança: toda remoção passa por `config.remover` (só dentro de `~/.cerebro`); testes só apagam dentro da pasta temporária.
- Revisão independente: mascaramento de segredos ampliado, detecção sem executar código do projeto, token/cookie não-ASCII, caminhos com `..`,
  trava de arquivo, dois servidores, layout em 390 px, `servidor.py` dividido em módulos.

## 1.0.0

- Primeira versão: painel geral, agentes ao vivo (sessões e subagentes em tempo real), sessões, memória, custos e o mapa do código (Graphify por dentro).
- Servidor só em 127.0.0.1 com token e cookie; mascaramento de segredos; sem telemetria.
