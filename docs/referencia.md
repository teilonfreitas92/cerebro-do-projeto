# Cérebro do Projeto: referência técnica

> Esta é a referência detalhada. Para instalar e começar, leia o [README](../README.md).

Ferramenta local que mostra, num painel só, **todos os seus projetos do Claude Code** e, dentro de cada um, o **cérebro do
projeto**: agentes trabalhando ao vivo, sessões, memória e decisões, custo de tokens, mapa do código e configurações.
Tudo em português do Brasil, tudo no seu PC: o servidor só escuta em `127.0.0.1` e não envia nada para fora (sem telemetria). Exceções, sempre por clique seu: a consulta pública de versões (Novidades) e, se você usar, a explicação por IA do mapa (ver Segurança).

Versão 1.3.0 (gestor: fila "a conferir", decisões, ferramentas, análise, novidades, inventário, agentes por tipo; e, novos na 1.3: backup e restauração, rotinas no Windows, memória editável, agentes ao vivo pelos ganchos, avisos no Windows, tarefas para o gestor, orçamento, instalação de ferramentas, plano de encaixe aplicável e explicação por IA no mapa). O mapa do código usa o **Graphify como motor** (crédito e licença no arquivo `NOTICE`).

## Como abrir

```
python abrir_cerebro.py            # sobe o servidor, se preciso, e abre o navegador padrão já com a chave de acesso
pythonw abrir_cerebro.py           # o mesmo, sem nenhuma janela (também: abrir_cerebro.bat, duplo clique)
python abrir_cerebro.py --sem-navegador   # só garante o servidor no ar e imprime o link
python cerebro.py                  # sobe o servidor "à mão" (porta 8188; --porta N muda; --link imprime o link)
```

* Fechar a página **não** derruba o servidor. Ele encerra sozinho depois de 30 minutos sem nenhuma página aberta
  (a página manda um sinal a cada 20 s; mudar o tempo: Configurações). Também dá para encerrar pelo botão em
  Configurações.
* O link de abertura é `http://127.0.0.1:8188/?t=<chave>`. A chave fica em `~/.cerebro\token` (criada na
  primeira vez, aleatória, só o seu usuário lê). Sem o link, a página mostra "abra pelo atalho".
* Requisitos: Python 3.11 ou mais novo (a verificação automática usa o 3.12) e `aiohttp` (o `instalar.py` instala no `.venv`,
  versões fixas em `requirements.txt`). Sem build, sem npm.

### Demonstração (dados fictícios)

```
python demo/rodar_demo.py [--abrir] [--porta N] [--destino PASTA] [--refazer] [--so-gerar]
```

Gera (na primeira vez) três projetos inventados com conversas, subagentes, custos, memória, decisões, mapa e, desde a 1.3, tarefas
em vários estados, orçamento, avisos de memória, capítulos e a corrente da gestora, explicações de exemplo no mapa e um backup. Tudo
fica em `demo/saida` (ou em `--destino`): `CEREBRO_HOME`, `CEREBRO_CLAUDE` e `CEREBRO_BACKUP` apontam para lá e o Agendador do Windows
nunca é usado (`CEREBRO_DEMO`). As fotos do README e da apresentação vêm dela.

## O que tem

**O jeito da página (dashboard).** Em tela larga (1024 px ou mais) a página ocupa a altura da janela, sem rolagem: uma barra fina
em cima (marca, anéis de limite de 5 h, semana e contexto, *Como usar*, *Configurações*, tema), a **barra lateral à esquerda**
(*Todos os projetos*; a lista de projetos com o ponto de atividade e o selo "a conferir"; as **seções do projeto** aberto com
contadores; no pé, **Precisa de você (N)**, que abre uma gaveta por cima da tela, e *Recolher*, que deixa só os ícones e fica lembrado
no navegador) e a **área principal**. O que não cabe nela vira **abas internas** (Sessões, Memória e decisões, Custos, Ferramentas),
**menu de seções** (Configurações, Como usar) ou **páginas numeradas** (listas e tabelas). Em janela estreita a barra lateral vira um
menu ☰ e a página rola, sem rolagem horizontal. Nas tabelas abaixo, "aba" = seção da barra lateral.

| Tela | O que faz |
|---|---|
| **Painel geral** | Um cartão por projeto: nome, pasta, ramo e último commit (git, só leitura), sessões recentes, agentes escrevendo agora, custo de hoje e de 7 dias, se tem mapa, gestor, última atividade. Clicar abre o cérebro do projeto. A faixa **"Cérebro atualizado"** começa recolhida ("Ver o que mudou"). No pé da barra lateral, **"Precisa de você (N)"** abre uma gaveta com cada pendência e o botão Abrir (gestora não escolhida, mapa não gerado, memória pesada, preço a conferir, limites indisponíveis, **backup** falhou/atrasado/encolheu, **memória a conferir**, **conversa longa** para passar o bastão, **tarefas** novas ou a conferir e **orçamento** em 80% ou estourado). |
| **Visão geral** | Números (sessões, subagentes, agentes ativos, memórias, contexto fixo, custos), gestor, atividade recente. |
| **Agentes ao vivo** | Árvore sessão → subagentes com estado (trabalhando / parado / terminou), modelo, descrição, há quanto tempo, ferramentas e tokens. A gestora fica em destaque e os subagentes dela aparecem como "delegado pelo gestor". Com os **ganchos** ligados (Configurações) o estado muda na hora e aparecem os chips "ao vivo pelos hooks", "usando X" e "precisa de você"; sem eles vale a leitura dos arquivos. Clicar abre o **passo a passo ao vivo** (mensagens resumidas, chamadas de ferramenta com nome e alvo, resultados encurtados), por SSE, lendo só o que foi escrito depois (posição em bytes). Só leitura; numa sessão, o botão **Controlar no terminal** abre a mesma conversa na aba Janelas. |
| **Janelas (terminal)** | **Mosaico de janelas de prompt** lado a lado (ideia do MAESTRI), em 1 a 4 colunas ou automático, com botão ⤢ para ampliar uma. Dois tipos de janela. **Terminal de verdade**: *+ Nova sessão do Claude* ou *Controlar uma sessão…* abre o `claude` (ou `claude --resume <sessão>`) num pseudo-terminal do Cérebro, na pasta do projeto, e você digita ali como no cmd (aprovações, Esc, `/comandos`); a tela vem por WebSocket (xterm.js) e continua de onde estava se você recarregar a página. **Janela de leitura**: o passo a passo ao vivo de qualquer sessão ou subagente (inclusive das outras IAs), sem controle; com *acompanhar quem está trabalhando*, cada agente que começa a escrever ganha uma janela sozinho (até 8), e *Fixar* deixa a janela mesmo parada. Uma sessão aberta no app do Claude e aqui ao mesmo tempo briga pela mesma conversa: o Cérebro avisa e só abre com o segundo clique. Até 8 terminais; com algum aberto o servidor não encerra sozinho, e encerrar o servidor fecha os terminais. No Windows precisa do `pywinpty` (vem no `requirements.txt`). |
| **Sessões** | Todas as sessões do projeto (título, última atividade, mensagens, tokens, custo, modelo, subagentes, ferramentas mais usadas) com filtro; botão "Definir gestora" e atalho para o passo a passo. No topo, a **corrente da gestora** (transcrições anterior → atual e o contexto em %), a **linha do tempo dos capítulos** (botão Abrir) e "Autorizar a limpeza automática" das **transcrições antigas** (apagar arquivos velhos da gestora depois de 7 dias; é outra coisa que a "limpeza na mesma sessão" da conversa, descrita abaixo). Sessão com contexto acima de 60% de 200 mil tokens ganha o chip **"Conversa longa — passar o bastão"** e o botão **Gerar resumo** (passa-bastão, sem IA, com Copiar). |
| **Memória e decisões** | Memória do Claude Code do projeto (`MEMORY.md` e um arquivo por fato) + `CLAUDE.md`/`AGENTS.md`, com busca, filtros e destaque de REGRA/DECISÃO, e o **contexto fixo** (tokens que toda conversa paga). Mais a **linha do tempo de decisões**: as registradas no Cérebro (`decisoes.jsonl`, pela página ou pela CLI) junto com as REGRA/DECISÃO achadas nos arquivos de memória. **Novo na 1.3:** cada memória tem **Editar** e **Arquivar**; a caixa **Cuidar da memória** cria memória nova, propõe a **compactação do `MEMORY.md`** (sem IA, com verificador: regras ficam inteiras) e lista **avisos** de memória velha, que cita o que não existe ou que contradiz outra. Decisões também têm Editar/Arquivar (nenhuma linha é apagada). Toda gravação mostra a diferença, pede confirmação e guarda cópia antes. |
| **Custos** | Tokens (entrada, saída, cache de leitura, cache de escrita) por sessão, subagente, modelo e dia, somados do campo `usage` das mensagens. Custo = tokens × tabela de preços editável (**estimativa** pelo preço de lista; pode diferir da fatura). Gráfico por dia. Anéis de limite 5 h / 7 dias quando houver o arquivo `claude_status.json` da statusLine do Cérebro. Cartão **Orçamento** com barra por dia, semana e mês, quanto falta e projeção do mês (estimativa pelo preço de lista; só avisa, nunca bloqueia). |
| **Mapa** | A página do mapa do código (grafo 2D, departamentos, painel lateral, linha do tempo), servida pelo próprio servidor com o mesmo token e **ocupando a área principal inteira** (linha de status compacta com *Atualizar*, *Explicar com IA*, que abre numa gaveta, e *Tela cheia*). Dentro do mapa: faixa de números recolhível (botão #), legenda recolhível, o canvas acompanha o tamanho da área e o controle **− Espaço +** muda a distância entre as bolinhas (lembrado no navegador); *Centralizar* e *Voltar ao padrão* enquadram tudo. **Se atualiza sozinho**: com o servidor no ar, a cada `mapa_vigia_segundos` (padrão 30 s) só a data do `graph.json` de cada projeto é conferida (e também ao abrir); quando fica mais novo que o `dados.js` do Cérebro, o gerador roda em segundo plano (o intervalo vem de `mapa_vigia_segundos`, padrão 30 s). Mostra "mapa atualizado há X" e avisa se o `graph.json` está mais velho que o último commit. Ver `mapa\LEIA-ME.md`. O painel lateral tem **"Criar tarefa aqui"** (grupo, arquivo ou função) e a gaveta **"Explicar pontos do mapa com IA"** (abaixo). |
| **A conferir** | Cada subagente que **terminou** na sessão gestora entra na fila até o gestor marcar **aprovado / corrigido / recusado** (com nota opcional). Contadores (a conferir, parados há mais de 24 h, conferidos, aprovados, corrigidos, recusados), **% aprovado de primeira por modelo** e destaque em "Precisa de você" do painel geral. Guardado em `projetos\<slug>\revisoes.json`. Também pela CLI (abaixo). |
| **Análise** | Botão **Analisar agora** (sem IA): arquivos maiores e que mais cresceram (git), centros e mudanças do mapa, resultado das ferramentas, tamanho do contexto fixo, custo por dia e modelo com tendência, % aprovado de primeira, itens a conferir parados, ferramentas recomendadas não instaladas. Gera **propostas** (motivo, esforço P/M/G, risco) que você aprova (vira **tarefa para o gestor**) ou descarta; histórico das análises. Com o servidor aberto roda sozinha no intervalo configurado ("próxima análise em…"). A análise do próprio Cérebro fica no escopo `_cerebro`. |
| **Novidades** | Botão **Procurar novidades**: só `GET` na API pública de releases do GitHub (Claude Code, Graphify e as ferramentas do top 10), sem login e **sem mandar nada do projeto**. Mostra "novo desde a última vez" e ferramenta instalada desatualizada como propostas. Sem rede: avisa e não quebra. |
| **Inventário** | O que o projeto já tem (CLAUDE.md, AGENTS.md, docs, testes e como rodam, CI, ganchos do git, `.claude/agents`, `.claude/settings*`, memória, `graphify-out`, lint) e um **plano de encaixe**. Cada item com ação tem **"Ver o que muda e aplicar…"**: mostra os arquivos e a diferença, pede a caixa "Conferi" e só então aplica (instruções no `CLAUDE.md`, agentes em `.claude/agents`, gitleaks no pre-commit, `ruff.toml`, Dependabot). Rodapé com o histórico e **Desfazer**. Detalhes em Segurança. |
| **Ferramentas** | Cartões das 10 ferramentas de qualidade (ruff, ESLint, cargo/clippy, gitleaks, Semgrep, pip-audit, cargo-deny, OSV-Scanner, coverage, Lighthouse) com estado (**detecção só de leitura**: procura o programa e pergunta `--version`), o estado do Graphify (versão e mapa) e, para as não instaladas, "o que faz" e o botão **Instalar…** (ruff, pip-audit, coverage, Semgrep, cargo-deny, gitleaks, Lighthouse: receita fechada, comando exato mostrado antes, sem shell, saída no histórico; OSV-Scanner e ESLint ficam sem botão). Os **comandos permitidos** do projeto (lista fechada no `config.json`) têm botão **Rodar**: sem shell, com tempo limite, sem janela, saída mascarada, um por projeto de cada vez, histórico das últimas 20 execuções com a saída rolável. Nenhum comando vem pronto: o Cérebro SUGERE (package.json, pytest/unittest, cargo, ruff, ESLint) e só entra na lista se você aprovar; rodar sempre exige o clique em "Rodar". |
| **Configurações** | Um **menu de seções** à esquerda e uma seção por vez na área principal (a global, pelo botão da barra de cima, vale para todos os projetos; a do projeto, pela barra lateral, acrescenta as seções do projeto). Sessão gestora do projeto e **apelido** ("Gestora principal" no lugar de "### Loja ###"), projetos visíveis/ocultos e adicionar projeto, **tabela de preços**, rotinas (análise, novidades, vigia do mapa, janela da fila a conferir), **agentes por tipo de tarefa** (tipo, modelo, quem revisa, com botão que gera uma **prévia** dos `.claude/agents/*.md` só dentro de `~/.cerebro`), **departamentos do mapa** por projeto, tema, porta, tempo sem página, encerrar o servidor. Seções novas na 1.3: **Backup das conversas e da memória**, **Rotinas no Windows**, **Agentes ao vivo instantâneo** (ganchos e statusLine), **Avisos no Windows** e **Orçamento de gasto**. |
| **Tarefas** | Tarefas criadas por você (título, descrição, prioridade, tipo de agente, pontos do mapa) para o gestor. Estados: nova, recebida, em andamento, a conferir, feita, recusada, com histórico (quando, quem, de→para, nota). Filtros por estado, prioridade e busca; contador na aba, no cartão do projeto e em "Precisa de você". As tarefas de proposta aprovada aparecem na mesma lista. O gestor recebe as novas como contexto (gancho `UserPromptSubmit`) ou lê com `tarefas --novas`. |
| **Backup e restauração** (Configurações) | Lista os backups diários, "Fazer backup agora", **Conferir** e **Restaurar…** (mostra por projeto o que falta, o que é diferente e o que só cresceu; restaura sem apagar, com segundo clique de confirmação). |
| **Rotinas no Windows** (Configurações) | Liga, atualiza e desliga as tarefas `CerebroDoProjeto\backup`, `analise`, `novidades` e `mapa` no Agendador de Tarefas, com horário/intervalo, estado e último resultado. |
| **Agentes ao vivo instantâneo** (Configurações) | Mostra o estado dos ganchos e da statusLine, **Ver o que muda** (diferença exata do `settings.json`), **Ligar** e **Desligar**. |
| **Avisos no Windows** (Configurações) | Liga/desliga geral e por tipo, minutos sem repetir, minutos para avisar que uma sessão parou, "não perturbe", **Testar aviso** e os últimos avisos. |
| **Orçamento de gasto** (Configurações) | Limites em US$ por dia, semana e mês (geral e por projeto) e o % em que o aviso começa (padrão 80). |
| **Manual do gestor neste projeto** (Configurações do projeto) | Liga/Desliga o bloco que faz o Claude Code ler o `~/.cerebro/GESTOR.md` (no `CLAUDE.local.md`), com prévia da diferença e cópia antes. A faixa **"Cérebro atualizado"** do painel geral mostra o que mudou para o gestor na versão nova. |
| **Bem-vindo** (primeiro uso) | Passos guiados: projetos, sessão gestora, mapa, comandos sugeridos e **ligar os ganchos (recomendado)**, sempre com prévia e o seu sim. |

### Estados dos agentes

Com os ganchos ligados, o estado vem dos eventos do Claude Code (na hora) e vale enquanto for mais novo que o arquivo da conversa. Sem eles, vale o que está abaixo.

* **trabalhando**: o arquivo da conversa foi escrito nos últimos 60 s (ou o `claude agents` diz que a sessão está ocupada);
* **parado**: ainda não terminou, mas sem escrever há um tempo;
* **terminou**: o Claude Code marcou o subagente como terminado, ou a sessão não está mais aberta e ficou parada.

## Linha de comando do gestor

```
python cerebro_cli.py estado <projeto>                       # fila e contadores
python cerebro_cli.py a-conferir <projeto>                   # lista o que espera conferência
python cerebro_cli.py conferir <projeto> <id-ou-descrição> --resultado aprovado|corrigido|recusado --nota "..."
python cerebro_cli.py decisao <projeto> "texto" --tipo decisao|regra|ideia --origem dono|gestor   # dono = você; gestor = a conversa principal
python cerebro_cli.py decisoes <projeto>
python cerebro_cli.py tarefas <projeto> [--novas] [--todas]  # tarefas (--novas: texto pronto para o gestor; --todas: com as terminadas)
python cerebro_cli.py tarefa <projeto> <id> --estado nova|recebida|andamento|conferir|feita|recusada [--agente X] [--nota "..."] [--por gestor]
python cerebro_cli.py tarefa-feita <projeto> <id> --nota "..."
python cerebro_cli.py analisar <projeto>                     # o mesmo que "Analisar agora" na página
python cerebro_cli.py orcamento [<projeto>] [--dia N] [--semana N] [--mes N] [--aviso PCT]   # sem projeto = geral; 0 tira o limite
python cerebro_cli.py projetos
```

Comandos da 1.3 (os que gravam fora de `~/.cerebro` ou instalam algo **só gravam com `--confirmar`**; sem ele mostram a prévia):

```
python cerebro_cli.py backup [--listar]                      # lista os backups (padrão)
python cerebro_cli.py backup --agora                         # faz o backup de hoje
python cerebro_cli.py backup --conferir AAAA-MM-DD           # relê o backup e compara com a lista de arquivos
python cerebro_cli.py backup --restaurar AAAA-MM-DD [--projeto X] [--so-memoria] [--trocar-diferentes] [--confirmar]
python cerebro_cli.py backup --liberar                       # devolve à rotação o backup protegido depois de um que encolheu
python cerebro_cli.py rotina backup|analise|novidades|mapa   # roda a rotina agora (é o que a tarefa agendada chama)
python cerebro_cli.py agendar <rotina> --ligar [--hora HH:MM] [--dias N] [--horas N] | --desligar | --estado
python cerebro_cli.py memoria <projeto> --compactar [--aplicar [--confirmar]]   # proposta de compactar o MEMORY.md (sem IA)
python cerebro_cli.py memoria <projeto> --avisos             # memória velha, contraditória ou citando o que não existe
python cerebro_cli.py bastao <projeto> <sessao>              # resumo de passa-bastão (id da sessão ou o começo dele)
python cerebro_cli.py hooks --estado | --previa | --instalar --confirmar | --remover --confirmar
        [--modo comando|http] [--statusline instalar|encadear|substituir] [--sem-hooks] [--so-hooks] [--so-statusline]
python cerebro_cli.py instalar-ferramenta <projeto> <ferramenta> [--confirmar] [--aceitar-termos]
python cerebro_cli.py encaixe <projeto> [--previa] | --aplicar <instrucoes|agentes|segredos|segredos-tirar|qualidade|dependencias> --confirmar
        [--gravar-ao-lado] [--modo config|encadear|novo] | --desfazer --confirmar
python cerebro_cli.py agentes-copiar <projeto> [--gravar-ao-lado] --confirmar   # copia a prévia dos agentes para .claude/agents
python cerebro_cli.py explicar <projeto> [--estimar] | --rodar [--limite N] [--via claude|api]   # --estimar é o padrão e não gasta nada
python cerebro_cli.py gestora estado <projeto>             # corrente de transcrições da gestora, contexto e capítulos
python cerebro_cli.py gestora limpar <projeto>             # só com a limpeza opcional ligada: capítulo gravado e conferido; "OK" = a gestora pode chamar clear_session
python cerebro_cli.py gestora limpeza <projeto> [--autorizar --confirmar | --desautorizar]   # transcrições antigas da gestora (arquivos velhos; outra coisa que a limpeza da conversa)
python cerebro_cli.py manual --gerar                       # refaz o ~/.cerebro/GESTOR.md
python cerebro_cli.py manual <projeto> --previa | --instalar --confirmar | --remover --confirmar   # bloco no CLAUDE.local.md
python cerebro_cli.py gestora preparar|trocar <projeto> [--marca ID]   # alternativa fora do padrão: troca por sessão nova do app
```

`<projeto>` aceita o nome, o slug ou o caminho. Os comandos básicos escrevem só em `~/.cerebro`; os da 1.3 que escrevem fora dele estão descritos em Segurança. A página tem o guia
**Como usar** (botão no topo) com cada aba, como abrir, onde ficam os dados e a segurança.

### Outras IAs como subagentes (OpenAI, DeepSeek, Grok, Gemini)

O gestor pode mandar outra IA fazer o serviço de um subagente: ler, procurar, editar arquivos e rodar testes. As quatro usam o mesmo
formato de chamada (chat completions com ferramentas), então um laço só (`cerebro/ias_externas.py`) serve para todas.

```
python cerebro_cli.py ia situacao                                    # quais têm chave e qual modelo
python cerebro_cli.py ia rodar <projeto> --ia deepseek --tarefa "..." # ou --arquivo-tarefa tarefa.md
python cerebro_cli.py ia listar <projeto>
python cerebro_cli.py ia juntar <projeto> <id>                       # depois de conferir o diff
python cerebro_cli.py ia descartar <projeto> <id>
```

- **Cópia separada**: a IA trabalha num `git worktree` em `~/.cerebro/ias_trabalho/<slug>/<id>` (ramo `ia/<ia>-<id>`); a pasta do
  projeto não muda até o gestor juntar. Projeto sem git é recusado.
- **Presa à cópia**: caminhos fora dela ou dentro de `.git` são recusados; comandos só da lista (testes, build, `git status/diff/log`),
  sem `;` `&` `|` `<` `>` crase `$` `%`. Limites: 40 voltas e 30 minutos por serviço (`config.json > ias`).
- **Visível**: a conversa vai para `~/.cerebro/ias/<slug>/<sessão do gestor>/agent-ia-*.jsonl` no formato dos subagentes do Claude Code,
  então aparece em Agentes ao vivo (com o terminal), em Custos (tokens; o custo em dólar aparece quando o modelo está na tabela de preços)
  e na conferência do gestor (`conferir <projeto> ia-<ia>-<id>`).
- **Chaves**: o dono cola em Configurações › Outras IAs. Ficam em `~/.cerebro/ias_chaves.json`, legível só pela conta do dono; a página
  nunca recebe a chave de volta (só os 4 últimos caracteres) e o backup não leva o arquivo. Modelos padrão: `gpt-5`, `deepseek-chat`,
  `grok-4`, `gemini-2.5-pro` (troque em Configurações se a sua conta usa outro).

### Conversa longa da gestora: compactação automática (padrão) e limpeza opcional

A gestora **nunca é trocada**. Há dois caminhos para a conversa longa.

**1. Compactação automática (padrão, zero toque do dono).** Quando o contexto enche, o Claude Code compacta a conversa sozinho:

1. `PreCompact`: o Cérebro grava um **capítulo** (`capitulos.py`). O resumo no topo vem em ordem de prioridade: a última mensagem
   inteira da gestora (a pergunta pendente), pasta de trabalho, ramo e commit da sessão, pendências abertas, "últimos pedidos do dono"
   e os commits da sessão. Abaixo ficam os detalhes: worktrees, memória editada (inclusive por comandos do terminal), arquivos,
   decisões e o passa-bastão completo.
   * Pasta, ramo e commit vêm do `cwd` e do `gitBranch` das últimas mensagens da conversa (a sessão pode estar numa worktree, que também é listada).
   * "Últimos pedidos do dono" traz só o que o dono digitou: inclui respostas de formulário e mensagens enviadas no meio do turno,
     e deixa de fora avisos do sistema, recados entre sessões e notificações.
2. `SessionStart` com `source: "compact"`: o grupo **síncrono** do Cérebro (`matcher: "startup|clear|compact"`, `timeout: 5`,
   `cerebro_hook.py --sincrono`) lê só `~/.cerebro` (funciona com o painel fechado; desiste em 4 s) e devolve à gestora, como
   `additionalContext`, a linha do `GESTOR.md` + o resumo do último capítulo (até ~1.500 tokens). Ela confere o estado real e segue.

**2. Limpeza na mesma sessão (opcional, DESLIGADA).** Liga em Configurações (`config.json` > `gestora_rotacao` > `ativo` = `true`).
Vem desligada porque, no teste com o app real do Claude, depois do `clear_session` a conversa limpa só recomeça quando chega uma
mensagem do dono (um lembrete agendado antes da limpeza não sobrevive). O caminho, quando ligada:

1. O contexto do último turno da gestora (lido do fim do JSONL) passa de `gestora_rotacao.limite_pct`% de `janela_tokens`
   (padrão 60% de 200 mil). No próximo `UserPromptSubmit` da gestora, `ligacoes.py` entrega UMA vez por transcrição o recado
   "Contexto em X%. Ao terminar este turno: rode `python <pasta>/cerebro_cli.py gestora limpar <projeto>` e, se ele disser OK,
   chame clear_session com session_id "self"". A gestora avisa o dono antes ("Vou limpar a conversa; mande qualquer mensagem e eu
   sigo"). Não há gancho `Stop` com contexto (ele prenderia a conversa).
2. `gestora limpar` grava o capítulo, relê, confere as seções e só então registra a limpeza pendente em `corrente.json`. Sem isso:
   "NÃO limpe" (saída 2).
3. A gestora chama `clear_session` (o app pede o ok do dono). A conversa nova nasce quando o dono manda a próxima mensagem. No app ela
   chega com `source: "startup"` (não `"clear"`; um `/clear` digitado traz `"clear"`). O Cérebro só a trata como da gestora se o
   projeto tem uma **limpeza pendente** (vale 24 h e só se a conversa antiga parou de ser escrita logo depois do capítulo). Aí troca
   `gestoras[slug].conversa` para o novo id, fecha o elo antigo (`anterior`, `fim`, capítulo ligado) e devolve o resumo do capítulo.
   Sem pendente, só o `/clear` manual (`source: "clear"` e a gestora mexida nos últimos 3 min) conta.
4. Na primeira resposta depois da limpeza, a gestora diz "Conversa limpa pelo Cérebro: o capítulo foi salvo e eu já recebi o resumo.
   Pode prosseguir."

**Retenção** (`retencao_gestora.py`): trava própria e estreita, a única que apaga dentro de `~/.claude/projects` (a trava geral
`config.remover` continua recusando `.claude`). Só depois que o dono autoriza o projeto (botão na aba Sessões ou
`gestora limpeza <projeto> --autorizar --confirmar`), a rotina do servidor (no máximo 1 vez por dia) apaga
`<slug>/<uuid>.jsonl` e a pasta `<uuid>/` de elos `anterior` do mesmo projeto com mais de 7 dias, se o snapshot de backup mais
novo passa no `backup.conferir` e tem cada arquivo com o MESMO sha256 do disco. Recusa: fora da corrente, outro projeto, a atual,
menos de 7 dias, sha diferente, backup não conferido, link/junção, `..`. As conferências se repetem logo antes de cada remoção.

**Manual do gestor** (`manual_gestor.py`): `~/.cerebro/GESTOR.md` (< 1.500 tokens, cabeçalho com versão e hash), refeito ao subir
o servidor quando muda. Versão nova: faixa "Cérebro atualizado" na página e recado único por sessão gestora. "Manual do gestor
neste projeto" (`manual_projeto.py`) põe o bloco `<!-- cerebro:gestor:inicio -->` / `@~/.cerebro/GESTOR.md` /
`<!-- cerebro:gestor:fim -->` no `CLAUDE.local.md`, pela `escrita_projeto` (recusa arquivo rastreado; se não ignorado,
acrescenta a linha no `.git/info/exclude`, a única exceção nova da trava dentro de `.git`).

## Como adicionar um projeto

* Todo projeto que você abre no Claude Code (`~/.claude\projects\`) aparece sozinho. O caminho real é lido
  do campo `cwd` das conversas e conferido com o nome da pasta; se faltar, o nome é decodificado procurando as pastas
  que existem de verdade.
* **Nunca entram:** worktrees (`--claude-worktrees-`), `Temp`, `scratch-workspaces`, subpastas `dados-*`, a pasta do
  usuário inteira e o que você mandar esconder para sempre em `nunca_entrar` do `config.json` (pedaços de nome ou de caminho).
* Qualquer pasta fora do Claude Code: Configurações › "Adicionar projeto" (grava em
  `projetos_extra` do `config.json`).
* Esconder um projeto: desmarque em Configurações (grava em `ocultos`).

## Arquitetura

```
cerebro.py              entrada: sobe o servidor (aiohttp, 127.0.0.1)
abrir_cerebro.py/.bat   sobe se preciso + abre o navegador com a chave (sem janela preta)
cerebro\                 pacote Python (comentado em pt-BR)
  config.py             caminhos, config.json global, token, cookie, preços iniciais
  segredos.py           mascaramento de chaves/tokens/senhas antes de qualquer texto ir para a tela
  transcricao.py        leitura tolerante e incremental dos JSONL (índice de tokens, passo a passo)
  indice.py             lista de sessões/subagentes + índice em cache (~/.cerebro\projetos\<slug>\indice.json)
  projetos.py           descoberta dos projetos, git (só leitura), estado do mapa
  custos.py             soma de tokens e custo, com cache
  agentes.py            árvore sessão → subagentes, estados, `claude agents --json` (tolera falha)
  memoria.py            memória, documentos fixos, contexto fixo, busca
  painel.py             limites do plano, ferramentas, fila "precisa de você"
  servidor.py           rotas, segurança (token/cookie/Host/Origin), SSE, auto-encerramento (não encerra enquanto chegam eventos dos ganchos, nos últimos 30 min)
  web_util.py           ajudantes das rotas (resposta JSON, erro, projeto da URL, chaves do aplicativo)
  rotas_gestor.py       rotas do gestor (ferramentas, a conferir, decisões, análise, novidades, inventário, agentes, departamentos)
  armazem.py            leitura/gravação de JSON tolerante, atômica e com trava
  revisoes.py           fila "a conferir" e % aprovado de primeira por modelo
  decisoes.py           decisoes.jsonl por projeto
  ferramentas.py        detecção das 10 ferramentas, lista fechada de comandos, execução, histórico
  analise.py/propostas.py  "Analisar agora" (sem IA), propostas e tarefas
  novidades.py          vigia de novidades (GET público)
  inventario.py         inventário e plano de encaixe (só leitura)
  regras_agentes.py     agentes por tipo de tarefa e prévia dos .md
  departamentos.py      departamentos do mapa por projeto
  titulos.py            melhor título de cada sessão
  mapa_auto.py          vigia que refaz a página do mapa quando o graph.json muda
  rotinas.py            análise/novidades automáticas (só com o servidor no ar)
  backup.py             backup diário em .zip, conferência, rotação, proteção e restauração
  rotas_backup.py       rotas do backup e das rotinas no Windows
  cli_backup.py         subcomandos backup/rotina/agendar da CLI
  agendador.py          cria, consulta e remove as tarefas CerebroDoProjeto\* no Agendador do Windows (schtasks, XML)
  rotinas_windows.py    o que cada rotina faz quando a tarefa agendada a chama; registro e último resultado
  memoria_edicao.py     editar, criar e arquivar memória e decisões (versão conferida, cópia antes, escrita atômica)
  memoria_compactar.py  proposta de compactar o MEMORY.md (sem IA) e o verificador
  memoria_avisos.py     avisos de memória velha ou contraditória
  rotas_memoria.py      rotas de memória, avisos e passa-bastão
  bastao.py             contexto de cada sessão e resumo de passa-bastão
  ganchos_eventos.py    anel de eventos dos ganchos, estado ao vivo, arquivo do dia e ouvintes
  rotas_ganchos.py      receptor POST /api/hooks/evento (segredo próprio) e rotas da página
  ganchos_claude.py     liga/desliga os ganchos e a statusLine no settings.json (prévia, cópia, mescla)
  avisos.py             avisos do Windows (preferências, não perturbar, anti-repetição)
  ligacoes.py           liga os módulos: tarefas novas → sessão gestora, PreCompact → passa-bastão, orçamento e backup → aviso do Windows
  tarefas_gestor.py     tarefas do dono para o gestor (estados, histórico, texto de contexto)
  rotas_tarefas.py      rotas de tarefas e de orçamento
  orcamento.py          limites em US$, uso do dia/semana/mês, projeção e alertas
  instalador.py         receitas fechadas para instalar ferramentas (pip, cargo, winget, npm)
  encaixe.py            plano de encaixe aplicável (prévia, aplicar, desfazer)
  escrita_projeto.py    única porta para escrever dentro de um projeto (trava de caminho, cópia antes, escrita atômica)
  rotas_encaixe.py      rotas do encaixe e da instalação de ferramentas
  cli_encaixe.py        subcomandos instalar-ferramenta/encaixe/agentes-copiar da CLI
  explicar_ia.py        frase simples (Haiku) para os pontos do mapa sem texto, com estimativa, limites e cache
  rotas_explicar.py     rotas da explicação por IA
cerebro_hook.py         script do gancho (modo comando): leva o evento do Claude Code ao Cérebro, sem atrasar; se o Cérebro está fechado, liga-o em segundo plano (sem janela, no máx. 1 vez a cada 2 min)
cerebro_statusline.py   script da statusLine: grava os limites de 5 h e da semana em claude_status.json
.github\                verificação automática (testes.yml), Dependabot, modelos de issue (Problema, Ideia) e de pull request;
                        testes\ci_instalador.py prova o instalador num PC de mentira
demo\                    rodar_demo.py e gerar_demo.py: a demonstração com dados fictícios
docs\                    esta referência, imagens\ (fotos da demonstração e selos) e apresentacao\ (HTML + PDF)
README.md, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, CHANGELOG.md, LICENSE (MIT), NOTICE (crédito do Graphify)
web\                     front-end em JS puro, sem build (index.html, app.js, estilo.css; backup, memoria, ganchos, tarefas, encaixe e explicar têm o seu .js)
mapa\                    módulo do mapa (gerar.py + index.html/cerebro.js/cerebro.css), ver mapa\LEIA-ME.md
testes\                  testes automatizados (unittest)
```

Como lê as conversas: `~/.claude\projects\<projeto>\<sessão>.jsonl` e
`<sessão>\subagents\agent-<id>.jsonl` (+ `.meta.json`, não documentado, usado como bônus). O formato das linhas **não é
contrato** do Claude Code: linha desconhecida ou quebrada é ignorada, linha incompleta no fim do arquivo fica para a
próxima leitura. A leitura é incremental (guarda a posição em bytes): a primeira indexação de uma pasta grande de conversas
(mais de 1 GB) leva alguns segundos e roda em segundo plano; depois só o que foi escrito é lido.

## Segurança

* Escuta **só em 127.0.0.1** (o código não aceita outro endereço). Portas proibidas, nunca usadas: 80, 8050, 8060,
  8070, 8090, 8091, 8095, 8097, 7980 (a configuração recusa mudar a porta para elas).
* **Token** aleatório em `~/.cerebro\token` (acesso restrito ao seu usuário no Windows). A página abre por
  `/?t=<token>`; o servidor troca por um **cookie HttpOnly + SameSite=Strict** (o cookie guarda um HMAC do token, não o
  token) e redireciona para `/`, tirando a chave da URL. **Toda** rota exige o cookie (só `/api/saude` é pública e não
  diz nada além de "o Cérebro está no ar").
* **Host** precisa ser `127.0.0.1:<porta>` ou `localhost:<porta>` (anti DNS-rebinding). **Origin** de outro site é
  recusada; requisições que não são GET exigem Origin da própria página e `Content-Type: application/json`.
* **Terminal de verdade** (aba Janelas): só roda o `claude` (sessão nova ou `--resume` com id validado), na pasta do projeto;
  nunca um shell livre. O WebSocket exige o cookie e a Origin da própria página. A tela do terminal é a do Claude Code como no cmd:
  ela **não** passa pelo mascaramento de segredos (o que o claude imprimir aparece como apareceria no seu terminal).
* CSP restritiva (`default-src 'self'`), `nosniff`, sem referrer. Texto de transcrição nunca vira HTML: a tela usa só
  `textContent`.
* **Segredos:** os transcritos do Claude Code guardam o que o agente leu e imprimiu (inclusive `.env`). Tudo que o
  Cérebro mostra passa por `segredos.mascarar()` (chaves `sk-`, `ghp_`/`github_pat_`, `AKIA`, JWT, `Bearer`, blocos
  `-----BEGIN`, cabeçalhos `Authorization`/`Cookie`, senhas em JSON ou `CHAVE=valor`). O conteúdo de arquivos lidos
  por um agente nunca aparece: só o tamanho. Resultados de ferramentas são encurtados (240 caracteres).
* **Apagar:** nada do que é seu é apagado. Toda remoção do app passa por `config.remover()` (recusa fora da casa do Cérebro, dentro de
  `.claude`/`projects` e a própria casa). A exceção controlada é a rotação do backup, que só remove cópias antigas da própria pasta de
  backup, só com nome no padrão `AAAA-MM-DD`, nunca a mais nova. Nos testes, `testes/_ambiente.apagar()` só apaga dentro da pasta temporária.
* **Comandos**: só a lista fechada do `config.json` (a página manda só o id), sem shell, só quando você clica em Rodar.
* **O que o Cérebro ESCREVE fora de `~/.cerebro` (novo na 1.3).** Regra de todos: só com o seu clique de confirmação na página
  (prévia, depois um segundo clique) ou `--confirmar` na linha de comando; sem isso só mostram a prévia. Sempre guardam uma cópia antes
  (em `~/.cerebro\copias\`), escrevem por arquivo temporário e troca (nunca deixam arquivo pela metade), recusam caminho fora da área
  permitida (`..`, link simbólico, outra unidade) e **nunca apagam**.
  * **Pasta de backup** (`~\CerebroBackup`, ou a que você escolher; pasta dentro de `.claude`/`.cerebro` é recusada): os `.zip` diários.
  * **`~/.claude\projects`** (conversas e memória): só pela **restauração** (copia de volta o que falta; troca o diferente só se você marcar,
    guardando a versão de hoje antes) e pela **edição de memória** (só arquivos `.md` diretamente em `<projeto>\memory\`; se o Claude Code mexeu
    no arquivo desde que você abriu, a gravação é recusada; memória com segredo não pode ter o corpo alterado). Arquivar **move** para `memory\_arquivo\`.
  * **`~/.claude\settings.json`**: só pelo instalador de ganchos/statusLine. Mostra a diferença exata, faz cópia antes, preserva tudo o que
    já existe (outros ganchos, permissões, statusLine de outra pessoa só com a sua escolha de encadear ou substituir) e **Desligar** tira só o que é do Cérebro.
  * **Dentro de um projeto** (plano de encaixe, cópia dos agentes, instalação do gitleaks no pre-commit): só pela porta única
    `escrita_projeto`, que só cria arquivo novo ou acrescenta ao fim (um bloco marcado), nunca apaga (a única troca é o gancho `pre-commit` que já existia: ele é guardado ao lado, com cópia, e o do Cérebro o chama primeiro); recusa projeto oculto, em
    `nunca_entrar` ou `nunca_escrever`, worktree, a pasta do usuário e o que estiver dentro de `.git` (exceto o gancho `pre-commit`); guarda a
    cópia do que tocou e permite **Desfazer** (o arquivo criado é movido para a pasta de cópias, não apagado). A página manda só o id da ação e a
    assinatura da prévia; se o projeto mudou desde a prévia, o servidor recusa.
  * **Agendador de Tarefas do Windows**: só tarefas da pasta `CerebroDoProjeto\` (backup, analise, novidades, mapa), do usuário atual, sem senha e
    sem administrador. Nenhuma tarefa de fora desse prefixo é tocada.
  * **Instalar ferramentas** (pip, cargo, winget, npm): só receitas fechadas no código (a página manda o id), comando exato mostrado antes,
    sem shell, sem administrador (`pip --user`), uma instalação por vez, com tempo limite.
* **Receptor dos ganchos** (`POST /api/hooks/evento`): é a única rota (fora a de saúde) que não usa o cookie da página, porque quem chama é o Claude Code. Em troca exige um
  **segredo próprio** (`X-Cerebro-Hooks`, guardado em `~/.cerebro\hooks_token` com acesso só do seu usuário; não é o token da página e não abre a página),
  recusa qualquer requisição que venha de navegador (`Origin`/`Sec-Fetch-Site`), só aceita POST, corpo de até 256 KB, descarta campos desconhecidos e
  mascara e encurta todo texto. Só devolve algum conteúdo ao Claude Code se um módulo do Cérebro pedir (hoje: tarefas novas, só para a sessão gestora do projeto).
* **Gancho que liga o Cérebro** (`cerebro_hook.py`): se o servidor está fechado (por exemplo, o PC reiniciou), o gancho sobe só o próprio Cérebro (`abrir_cerebro.py --sem-navegador`: programa fixo, sem shell, sem janela), no máximo 1 vez a cada 2 minutos e só se os ganchos estão configurados (existe o `hooks_token`). Ele não executa nada que venha do evento. O evento daquele instante se perde; os próximos chegam.
* **O que vai para a IA:** só a **explicação por IA do mapa**, e só quando você clica em "Explicar". Lotes de 20 pontos com nome, tipo, arquivo, até 6 vizinhos e as primeiras
  linhas do ponto (cerca de 700 caracteres, nunca o arquivo inteiro), com segredos mascarados; arquivos sensíveis (`.env*`, chaves, `credentials*`, nomes com
  senha/token/segredo, pastas `.ssh`/`.aws`/`secrets`) são pulados pelo nome. Vai pelo `claude` do seu plano (modo seguro: sem CLAUDE.md, ganchos, plugins nem MCP, sem
  salvar sessão; a chave `ANTHROPIC_API_KEY` é tirada dessa chamada) ou, só se você escolher `--via api`, pela API com a sua chave (cobrada por uso). Nada mais vai para uma IA
  (compactar a memória, avisos, passa-bastão e análise são sem IA).
* **Avisos do Windows:** usam um PowerShell fixo, sem janela, com título e texto passados por variável de ambiente (mascarados e encurtados). No macOS/Linux só registram.
* Nenhum transcrito real é copiado para este repositório; os testes usam amostras sintéticas.

## Onde ficam os dados

```
~/.cerebro\
  config.json                       projetos extras/ocultos, gestora por projeto, preços, rotinas, backup, rotinas_windows, tema, porta, nunca_escrever
  token                             chave de acesso da página
  hooks_token                       segredo do receptor dos ganchos (outro, só do seu usuário)
  .ligando                          marca da última vez que um gancho ligou o Cérebro (limita a 1 tentativa a cada 2 min)
  servidor.json                     PID e porta do servidor no ar (some ao encerrar)
  ganchos.json                      como os ganchos foram instalados (modo, porta, statusLine anterior)
  claude_status.json                limites de 5 h e da semana, modelo e custo, gravados pela statusLine
  eventos\<AAAA-MM-DD>.jsonl        eventos dos ganchos (mascarados; guarda 7 dias)
  avisos.json, avisos.jsonl         preferências dos avisos do Windows e o histórico
  avisos_enviados.json              quais alertas de orçamento/backup já avisaram hoje (no máximo 1 vez por dia)
  orcamento.json                    limites de gasto (geral e por projeto)
  ias_chaves.json                   chaves das outras IAs (só a sua conta lê; fora do backup)
  ias\<slug>\<sessão>\agent-ia-*.jsonl  conversas das outras IAs (aparecem como subagentes); ias\<slug>\_resultados\<id>.json
  ias_trabalho\<slug>\<id>\          cópias de trabalho das outras IAs (git worktree; fora do backup)
  novidades.json                    última consulta do vigia de novidades
  rotinas\<rotina>.log, .json, .xml registro, último resultado e a definição da tarefa agendada de cada rotina
  copias\                           cópia do que foi trocado: memoria\, decisoes\, settings\, projetos\<slug>\<data-hora>\, restauracao-<data>\
  explicar_ia\                      pasta neutra onde roda a explicação por IA
  projetos\<slug>\indice.json       cache do índice das sessões (pode apagar: é refeito)
  projetos\<slug>\revisoes.json    fila "a conferir" e resultados
  projetos\<slug>\decisoes.jsonl   decisões, regras e ideias registradas (só acrescenta linhas)
  projetos\<slug>\propostas.json, tarefas.json, analises.json   (tarefas.json guarda também as tarefas criadas por você)
  projetos\<slug>\bastao\<sessao>.md   resumos de passa-bastão (troca-*.md: os da troca pela CLI)
  projetos\<slug>\capitulos\<AAAA-MM-DD_HHMMSS>_<sessao8>.md   capítulos da gestora (para sempre; capitulos.manter_dias)
  projetos\<slug>\corrente.json   corrente de transcrições da gestora, limpezas pendentes e log
  projetos\<slug>\apagamentos.jsonl   transcrições antigas da gestora apagadas pela retenção (quando, quem, snapshot)
  GESTOR.md, gestor_manual.json      manual do gestor e quem já recebeu o aviso da versão
  retencao.json                      última rodada da retenção (feitos e recusas)
  projetos\<slug>\aplicacoes.json  histórico do plano de encaixe (últimas 50), usado pelo Desfazer
  projetos\<slug>\ferramentas\    execucoes.json e saidas\ (saída mascarada das últimas 20, inclusive instalações)
  projetos\<slug>\previa_agentes\ prévia dos .claude/agents/*.md (só vai para o projeto pelo botão de copiar)
  projetos\<slug>\mapa\           dados.js, historico.json, .estado.json.gz, explicacoes.json (frases da IA)

~\CerebroBackup\      (pasta mudável em Configurações ou em config.json > backup > pasta)
  AAAA-MM-DD.zip                    um backup por dia, com _manifesto.json (arquivo, tamanho, SHA-256); mantém os 7 mais recentes
  estado.json                       último resultado e backups protegidos (fica aqui para sobreviver se ~/.cerebro sumir)
  copias\                           só se ~/.cerebro tiver sumido durante uma restauração
```

Fora disso, o Cérebro só grava (sempre com a sua confirmação) os itens descritos em Segurança: memórias de `~/.claude\projects\<projeto>\memory\`,
o `~/.claude\settings.json`, os arquivos do plano de encaixe e o bloco do `CLAUDE.local.md` dentro dos projetos. E só apaga
dentro de `~/.claude\projects` as transcrições antigas da gestora, pela retenção autorizada (acima).

`<slug>` é o nome de pasta que o Claude Code usa (`C--Users-ana-Projetos-Loja`). As conversas do Claude Code são
apagadas por ele depois de 30 dias (`cleanupPeriodDays`); o índice guarda só números e títulos, não o texto.

## Preços e custo

A tabela inicial (US$ por milhão de tokens) vem da documentação da Anthropic (cópia de 06/10/2026) e vale como
**estimativa**. Campos marcados com `*` não vêm na tabela oficial e foram calculados pela regra geral do cache
(escrita 5 min = 1,25× a entrada, 1 h = 2×, leitura = 0,1× quando não informada): **a conferir**. A leitura de cache
do Sonnet 5.5 (US$ 0,10) foi calibrada pelo custo que o próprio Claude Code grava nas conversas. Modelo que não casa
com nenhuma linha fica "a conferir" e só conta tokens.

## Testes

```
python -m unittest discover -s testes -t . -p "test_*.py"
```

681 testes: parser de JSONL (amostras sintéticas, linha quebrada/incompleta, leitura incremental), descoberta de projetos
(exclui worktrees/Temp/scratch e o que estiver em nunca_entrar), mascaramento de segredos, soma de custos, token/cookie/Host/Origin,
rotas, SSE, auto-encerramento, o gerador do mapa, fila a conferir, decisões, CLI, ferramentas, análise/propostas,
novidades, inventário, agentes por tipo, departamentos, títulos, mapa automático, as travas de remoção e, na 1.3, backup/restauração, memória, ganchos, tarefas, orçamento, encaixe, explicação por IA, o receptor dos ganchos, a sessão gestora (limpeza, capítulos, retenção estreita) e o manual do gestor (com processos, Agendador, winget/pip/cargo/npm e `claude` falsos: nenhum real roda). Usam pastas temporárias (`CEREBRO_HOME`/`CEREBRO_CLAUDE`):
nunca tocam em `~/.cerebro` nem em `.claude`: `testes/__init__.py` isola o ambiente e imprime as pastas antes do primeiro teste (aborta se estiverem fora de `~/.cerebro-testes`).

`python testes/ci_instalador.py` (ou `--rapido`) simula um PC limpo: instala, sobe o servidor, confere a chave de acesso, desinstala e confere que nada mais foi tocado. O mesmo roteiro, mais `ruff` e a suíte, roda no GitHub (`.github/workflows/testes.yml`) a cada envio, no Windows e no Linux.

## Limites conhecidos (v1.3.0)

**O que ainda NÃO foi testado de verdade** (só com peças falsas nos testes; confira na primeira vez que usar). Já foram vistos funcionando com o app real do Claude Code em 29/10: os ganchos, o capítulo gravado na compactação com o resumo devolvido, a limpeza da gestora na mesma sessão e o gancho que liga o servidor.

* **statusLine e caminho com espaço.** A statusLine e a mescla do `settings.json` num PC de outra pessoa não foram vistas; caminho com espaço numa máquina sem Git Bash também não foi testado.
* **Tarefas chegando ao gestor.** No modo padrão (gancho `async`, que nunca atrasa o Claude Code) o texto chega **na mensagem seguinte**, não na mesma. Para chegar na mesma, o gancho teria de ser instalado em modo `http` (aí o Claude Code espera o Cérebro responder).
* **Tarefa agendada no Windows.** O XML da tarefa e o `schtasks /Create` não foram executados no Agendador de verdade. Se o Windows recusar, o erro aparece na página e o XML fica em `~/.cerebro\rotinas\` para importar à mão. A tarefa só roda com você conectado.
* **Aviso do Windows na tela.** Nunca foi visto: o PowerShell real é bloqueado nos testes. Se o Windows não mostrar, o aviso cai em "falhou" em silêncio. Use **Testar aviso** na primeira vez.
* **Instalação de ferramentas.** Nenhum pip/winget/cargo/npm real rodou. O winget não existia no PC de desenvolvimento, então o botão do gitleaks não foi visto. O trecho do gitleaks dentro do gancho do git e o bloco do `.pre-commit-config.yaml` não foram executados.
* **Backup e restauração** com a conversa real do dono: o tamanho do `.zip` (5 a 10 vezes menor que o original) é estimativa.
* **Memória real:** compactação, avisos e edição foram testados com amostras e com a demonstração, não com a memória do dono.
* **Verificação no GitHub:** o roteiro nunca rodou lá e a suíte nunca foi executada no Linux; a primeira vez pode revelar algo do Ubuntu.
* **Explicação por IA** foi testada com o `claude` falso e com uma única chamada real minúscula. A frase é dedução de poucas linhas e pode errar (por isso o rótulo "explicação automática (IA)").

**Como é e o que não faz:**

* Agentes ao vivo: sem os ganchos, vale a **leitura dos arquivos** (atraso de ~1 s). Com os ganchos, o estado vive na memória do servidor: reiniciar o Cérebro esquece o estado até o próximo evento. No modo comando cada evento custa um processo curto em segundo plano (~0,2 s); `PreToolUse` é o mais frequente (tirar só perde o "usando X").
* `claude agents --json` está em "research preview": se mudar ou falhar, o estado cai para a data do arquivo.
* Rotinas sem a tarefa agendada (análise, novidades, vigia do mapa) só rodam **com o servidor no ar**. Com as **Rotinas no Windows** ligadas, rodam também com o painel fechado. No macOS/Linux o backup e a restauração funcionam, mas o agendamento mostra "só no Windows".
* Backup: o arquivo que o Claude Code está escrevendo é lido só até o tamanho visto no início, e o que o Windows negar entra como "falha" no relatório. Um backup grande leva minutos (o limite da tarefa é 2 h). **Restaurar não apaga**: o que existe hoje e não está no backup fica, e conversa que só cresceu depois do backup nunca é trocada.
* Memória: os avisos são por palavras (dão alarme falso e deixam passar contradição escrita de outro jeito). A compactação deixa **inteiras** as linhas com palavra de regra ("sempre", "nunca", "obrigatório"...), então a economia depende de quantas linhas não têm essas palavras. Texto com segredo não pode ser editado pela página (de propósito). O aviso de conversa longa só aparece depois que a sessão foi indexada.
* Orçamento: custo é estimativa pelo preço de lista (modelo sem preço entra só em tokens); dia e mês seguem o relógio do PC; a semana começa na segunda; a projeção do mês só alerta a partir do 3º dia; o Cérebro só avisa, nunca bloqueia.
* Tarefas: "pontos do mapa" vêm do último mapa gerado (sem mapa, descreva o lugar no texto); o botão "Criar tarefa aqui" só aparece quando o mapa é servido pelo Cérebro (não aberto como arquivo).
* Encaixe: `<nome>.cerebro.md` em `.claude/agents` também é lido pelo Claude Code (mesmo `name:`): junte à mão. Recusa worktree e `core.hooksPath`. O bloco do `CLAUDE.md` leva o caminho desta instalação do Cérebro.
* Sessão gestora: a compactação automática e a limpeza opcional foram vistas funcionando com o app real em 29/10. A limpeza vem
  desligada porque a conversa limpa só recomeça com uma mensagem do dono (um lembrete agendado antes não sobrevive). Quando ligada, o
  app entrega a conversa nova com `source: "startup"`, e ela só vale como da gestora com limpeza pendente (24 h). O recado do limite
  chega na mensagem SEGUINTE no modo padrão dos ganchos (async). Um `/clear` de OUTRA sessão do mesmo projeto até 3 min depois de a
  gestora ter escrito seria tomado como `/clear` da gestora. A retenção de transcrições antigas nunca rodou contra conversas reais.
* Servidor ligado pelo gancho: o evento do instante em que o Cérebro estava fechado se perde (os próximos chegam).
* Dois Cérebros em portas diferentes no mesmo endereço compartilham o nome do cookie e se derrubam ("Sessão expirada"); abrir pelo atalho resolve.
* Departamentos do mapa: sem configuração, uma cor por pasta de primeiro nível; ou as suas regras (caminho, curinga ou `re:` regex, com cor e posição opcional).
* A API pública do GitHub limita consultas sem login (cerca de 60 por hora): o vigia avisa quando o limite é atingido.
* A análise é por regras (sem IA): propõe, não decide. Custos são estimativa pelo preço de lista.
* A primeira abertura de um projeto com muitas conversas lê tudo em segundo plano (totais crescem até terminar).
