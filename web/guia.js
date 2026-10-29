/* Cérebro do Projeto — página "Como usar" (texto fixo, escrito com h(); nada vem de fora). */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h } = UI;

  const secao = (titulo, ...filhos) => h('section', { class: 'cartao guia' }, h('h3', null, titulo), ...filhos);
  const lista = itens => h('ul', null, itens.map(i => h('li', null, ...(Array.isArray(i) ? i : [i]))));
  const cod = t => h('code', null, t);
  const bloco = t => h('pre', { class: 'saida pequeno' }, t);

  UI.telas.guia = function telaGuia(raiz) {
    raiz.replaceChildren(h('div', { class: 'titulo-pagina' }, h('h2', null, 'Como usar o Cérebro do Projeto'), h('span', { class: 'muted' }, 'escolha o assunto à esquerda')),
      h('div', { class: 'guia-grade' },
        secao('O que é',
          h('p', null, 'O Cérebro é o painel de gestão dos seus projetos. Num lugar só você vê o que cada projeto tem, quem está trabalhando agora (sessões e subagentes do Claude Code), o que já foi decidido, quanto custa, o mapa do código e as ferramentas de qualidade. A ideia central: a conversa principal (o gestor, você + o melhor modelo) delega o trabalho pesado a modelos menores e CONFERE tudo o que eles entregam. Qualidade vem antes de economia; a economia vem da memória persistente.')),
        secao('Primeiro uso',
          lista([['Na primeira vez, o painel geral mostra a faixa "Primeiro uso". Ela leva à tela ', h('a', { href: '#/bem-vindo' }, 'Bem-vindo'), ', que guia 5 passos: seus projetos, a sessão gestora de cada um, gerar o mapa, aprovar os comandos sugeridos e concluir.'],
            'O mapa só é gerado quando você clica: o Graphify roda dentro da pasta do projeto e cria lá a pasta graphify-out (sugestão: ponha "graphify-out/" no .gitignore).',
            'Um dos passos oferece ligar os ganchos do Claude Code (recomendado): mostra o que muda no settings.json e só grava com o seu sim.',
            'Dá para pular qualquer passo e voltar depois.',
            ['Quer ver antes, sem nada seu? Na pasta do Cérebro rode ', cod('python demo/rodar_demo.py'), ': ele sobe com três projetos inventados.']])),
        secao('Como abrir',
          lista([[cod('abrir_cerebro.py'), ' (ou o atalho "Cérebro do Projeto" da área de trabalho, quando criado): sobe o servidor se preciso e abre o navegador já com a chave de acesso.'],
            'Fechar a página NÃO derruba o servidor. Ele encerra sozinho depois de 30 minutos sem nenhuma página aberta (Configurações muda isso) e há um botão para encerrar.',
            ['Endereço: ', cod('http://127.0.0.1:8188/'), ' (só nesta máquina). Sem a chave, a página recusa; a chave fica em ', cod('~/.cerebro/token'), '.'],
            'Enquanto o servidor está aberto, o mapa se atualiza sozinho, a análise roda no prazo e a fila "a conferir" fica em dia.'])),
        secao('A tela do painel',
          lista(['Em cima: a marca (volta para todos os projetos), os anéis de limite do plano, Como usar, Configurações e o tema (escuro ou claro).',
            [h('b', null, 'Barra lateral, à esquerda'), ': "Todos os projetos", a lista dos projetos (o ponto verde pulsando = agente escrevendo agora; azul = ativo nas últimas 24 h; o selo amarelo = subagentes a conferir) e, com um projeto aberto, as seções dele com os contadores. Um clique troca de projeto e fica na mesma seção.'],
            [h('b', null, 'Precisa de você'), ': fica no pé da barra lateral, com o número de pendências. O clique abre uma gaveta por cima da tela com cada aviso e o botão Abrir.'],
            'O botão "Recolher" deixa a barra só com ícones (o painel lembra a escolha). Em janela estreita ou no celular, a barra vira um menu: toque em ☰.',
            [h('b', null, 'Sem barra de rolagem'), ': cada tela cabe na área do meio. Listas longas viram páginas (‹ 1 2 3 ›), telas com muitas partes ganham abas internas e Configurações mostra uma seção por vez, escolhida no menu à esquerda. Só o passo a passo de um agente e o texto de uma memória aberta rolam, dentro do próprio quadro.']])),
        secao('As seções de um projeto',
          lista([[h('b', null, 'Visão geral'), ': números do projeto, gestora, fila do gestor e atividade recente.'],
            [h('b', null, 'Agentes ao vivo'), ': sessões e subagentes em tempo real; clique para ver o passo a passo. Mostra a regra de tarefa aplicada a cada subagente (tipo → modelo → revisor) e se já foi conferido.'],
            [h('b', null, 'A conferir'), ': todo subagente que terminou na sessão gestora espera aqui até o gestor marcar aprovado, corrigido ou recusado. Mostra quanto cada modelo (Haiku, Sonnet, Opus) acerta de primeira.'],
            [h('b', null, 'Tarefas'), ': o que você quer que o gestor faça. Crie aqui ou no mapa ("Criar tarefa aqui"). Estados: nova, recebida, em andamento, a conferir, feita e recusada, com histórico.'],
            [h('b', null, 'Sessões'), ': todas as conversas do projeto, com título melhor que o rótulo "### ... ###", resumo, tokens e custo. Conversa muito longa ganha o aviso "passar o bastão" e o botão Gerar resumo.'],
            [h('b', null, 'Memória e decisões'), ': a memória do Claude Code, o contexto fixo (o que toda conversa paga) e a linha do tempo de decisões e regras (as registradas aqui + as REGRA/DECISÃO dos arquivos de memória). Aqui você também edita, cria, arquiva e compacta a memória (veja "Cuidar da memória" abaixo).'],
            [h('b', null, 'Custos'), ': tokens e custo estimado (preço de lista; pode diferir da fatura) por modelo, sessão, subagente e dia, o cartão Orçamento e os anéis de limite de 5 horas e da semana.'],
            [h('b', null, 'Mapa'), ': o grafo do código (Graphify por dentro) ocupando a área do meio inteira, com departamentos coloridos, painel lateral e linha do tempo. Atualiza sozinho quando o graph.json do projeto muda. Em cima fica uma linha com a hora do mapa e os botões Atualizar, "Explicar com IA" (abre uma gaveta) e "Tela cheia". Dentro do mapa: o botão # mostra ou esconde a faixa de números, "Departamentos" recolhe a legenda, "− Espaço +" afasta ou aproxima as bolinhas (fica lembrado) e "Voltar ao padrão" enquadra tudo de novo. Tem também o botão "Criar tarefa aqui".'],
            [h('b', null, 'Ferramentas'), ': o que está instalado no PC (ruff, ESLint, cargo/clippy, gitleaks, semgrep, pip-audit, cargo-deny, OSV-Scanner, coverage, Lighthouse), os comandos que o projeto liberou para rodar com um clique e o histórico das últimas 20 execuções. As ferramentas que faltam têm o botão Instalar….'],
            [h('b', null, 'Análise'), ': botão "Analisar agora" (sem IA) com relatório e PROPOSTAS (motivo, esforço P/M/G, risco). Você aprova ou descarta; aprovada vira "tarefa para o gestor".'],
            [h('b', null, 'Novidades'), ': busca sob demanda de versões novas de ferramentas e do Claude Code em páginas públicas.'],
            [h('b', null, 'Inventário'), ': o que o projeto já tem (instruções, testes, lint, CI, ganchos, agentes, memória, mapa) e o plano de encaixe sugerido. Cada item pode ser aplicado depois de você ver o que muda, e há o botão Desfazer.'],
            [h('b', null, 'Configurações'), ': sessão gestora e apelido, projetos visíveis, preços, rotinas, agentes por tipo de tarefa, departamentos do mapa, tema, porta e, novos: Backup, Rotinas no Windows, Agentes ao vivo instantâneo, Avisos no Windows e Orçamento.']])),
        secao('Backup e restauração',
          lista(['Em Configurações › Backup das conversas e da memória. Uma vez por dia o Cérebro guarda um arquivo .zip com as conversas e a memória de todos os projetos (e os dados do próprio Cérebro).',
            ['Fica FORA das pastas do Claude Code e do Cérebro, por padrão em ', cod('~\\CerebroBackup'), '. Guarda os 7 dias mais recentes e confere cada cópia (botão Conferir).'],
            'Se um backup novo vier com menos da metade do anterior, o anterior fica protegido e o painel avisa em "Precisa de você" até você clicar "está tudo certo, liberar".',
            'Restaurar: escolha o dia, veja por projeto o que falta, o que é diferente e o que só cresceu depois do backup. O que falta é copiado de volta; o diferente só é trocado se você marcar (a versão de hoje vai antes para uma pasta de cópias). NADA é apagado. Exige um segundo clique de confirmação.',
            'Pela linha de comando: backup --agora, backup --listar, backup --conferir DATA, backup --restaurar DATA (sem --confirmar só mostra o que faria).'])),
        secao('Rotinas no Windows',
          lista(['Em Configurações › Rotinas no Windows. Cria tarefas no Agendador de Tarefas (pasta CerebroDoProjeto) para backup, análise, novidades e mapa rodarem sozinhas, mesmo com o painel fechado.',
            'Backup: todo dia (12:30 por padrão) e 5 minutos depois de você entrar no Windows. Se o PC estava desligado, roda assim que ligar. Análise a cada 7 dias, novidades a cada 3 (só consulta pública) e mapa a cada 6 horas (só refaz a página, não roda o Graphify).',
            'Só roda com você conectado ao Windows, sem senha e sem administrador. Cada rotina guarda um registro e o último resultado. "Desligar" remove só a tarefa dela.',
            'Pela linha de comando: agendar backup --ligar, agendar backup --estado, agendar backup --desligar. Importante: isto nunca foi testado no Agendador real; se o Windows recusar, o erro aparece na tela.'])),
        secao('Cuidar da memória',
          lista(['Na aba Memória e decisões: abra uma memória e use Editar ou Arquivar. Arquivar MOVE para memory/_arquivo/ (nunca apaga). "+ Nova memória" cria o arquivo e a linha no MEMORY.md.',
            'Toda gravação mostra a diferença, pede confirmação e guarda cópia antes. Se o Claude Code mexeu no arquivo enquanto você editava, a página recusa e pede para recarregar. Memória que contém senha ou chave não deixa mudar o texto.',
            '"Propor compactação do índice" encurta o MEMORY.md SEM IA e prova antes de gravar que nenhuma regra some (linhas com "sempre", "nunca", "obrigatório" etc. ficam inteiras).',
            'Avisos de memória velha ou contraditória aparecem em "a conferir" e em "Precisa de você". Nada muda sozinho; é um palpite por palavras e pode dar alarme falso.',
            'Passa-bastão: conversa que passou de 60% do contexto ganha o aviso "Conversa longa — passar o bastão". Gerar resumo monta, sem IA, o objetivo, os últimos pedidos, arquivos mexidos, decisões e tarefas abertas, para você colar numa conversa nova.'])),
        secao('Agentes ao vivo na hora e anéis de limite',
          lista(['Em Configurações › Agentes ao vivo instantâneo. Ligando os "ganchos" do Claude Code, o estado dos agentes muda na hora (trabalhando, parado, "usando X", "precisa de você") em vez de esperar a leitura dos arquivos.',
            'Isto mexe no settings.json do Claude Code. Por isso: "Ver o que muda" mostra a diferença exata, Ligar pede um segundo clique, a cópia do arquivo é guardada antes, o que você já tinha é preservado e Desligar tira só o que é do Cérebro.',
            'O modo padrão ("seguro") nunca atrasa o Claude Code. O modo direto só vale se você deixa o Cérebro sempre aberto.',
            'A statusLine do Cérebro alimenta os anéis de limite de 5 horas e da semana (planos Pro e Max). Se você já tem uma statusLine, o Cérebro pergunta se encadeia (as duas rodam) ou substitui.',
            'O receptor dos ganchos usa um segredo próprio (hooks_token), diferente da chave da página. Importante: isto ainda não foi testado com o Claude Code real.'])),
        secao('Avisos no Windows',
          lista(['Em Configurações › Avisos no Windows. Um aviso na tela quando: chega item a conferir na sessão gestora, o Claude Code precisa de você, uma sessão longa termina, o gasto passa do limite ou o backup falha.',
            'Liga/desliga geral e por tipo, "não perturbe" por horário, minutos sem repetir. Alerta de orçamento e de backup avisa no máximo 1 vez por dia. Botão "Testar aviso" para ver se o Windows mostra.',
            'Os avisos de item a conferir, do Claude Code e de sessão terminada dependem dos ganchos ligados.'])),
        secao('Tarefas para o gestor',
          lista(['Crie na aba Tarefas (título, descrição, prioridade, tipo de agente, pontos do mapa) ou no mapa, com o botão "Criar tarefa aqui". Se você deixar o tipo em branco, o Cérebro sugere.',
            'Com os ganchos ligados, o gestor recebe as tarefas novas como contexto da conversa. No modo padrão elas chegam na mensagem SEGUINTE. Sem ganchos, o gestor lê com tarefas --novas.',
            'O gestor muda o estado pela linha de comando (tarefa PROJETO ID --estado andamento). Você pode editar, marcar feita, recusar, devolver ao gestor e reabrir pela página.'])),
        secao('Orçamento de gasto',
          lista(['Defina limites em US$ por dia, semana e mês (geral e por projeto) em Configurações › Orçamento de gasto, ou pela CLI (orcamento PROJETO --mes 80). O cartão Orçamento fica na aba Custos.',
            'É ESTIMATIVA pelo preço de lista (plano por assinatura não cobra por token). O Cérebro só avisa (80% = atenção, 100% = estourou, mais a projeção do mês); nunca bloqueia.'])),
        secao('Instalar ferramentas e aplicar o encaixe',
          lista(['Aba Ferramentas › Instalar…: instala ruff, pip-audit, coverage, Semgrep, cargo-deny, gitleaks ou Lighthouse. Mostra o comando exato, de onde vem e onde instala; só uma instalação por vez, sem administrador.',
            'Aba Inventário › "Ver o que muda e aplicar…": acrescenta o bloco do Cérebro no CLAUDE.md, copia os agentes para .claude/agents, liga o gitleaks no pre-commit, cria ruff.toml ou o Dependabot. Só CRIA ou ACRESCENTA, nunca reescreve nem apaga, e guarda cópia.',
            '"Desfazer" (rodapé do Inventário) volta a última aplicação. Projetos ocultos e a lista nunca_escrever do config.json são recusados.'])),
        secao('Explicar o mapa com IA',
          lista(['Na seção Mapa, botão "Explicar com IA" (abre uma gaveta à direita). A maioria dos pontos do código não tem texto; o botão pede ao Haiku uma frase simples para cada um.',
            'Ao abrir, o cartão mostra a ESTIMATIVA (pontos, chamadas, tokens). Você escolhe até quantos pontos por clique, vê o progresso e pode parar. Gasta tokens do seu plano.',
            'Só vai para a IA um trecho curto de cada ponto (segredos mascarados); arquivos sensíveis (.env, chaves, senhas) são pulados pelo nome. A frase aparece marcada como "explicação automática (IA)" porque pode errar.'])),
        secao('Conversa longa da gestora, sem toque',
          lista(['A gestora nunca é trocada. Quando a conversa dela enche, o Claude Code compacta sozinho: antes, o Cérebro grava um capítulo e, logo depois, devolve o resumo para a gestora. Você não precisa fazer nada.',
            'Capítulo = onde parou, a última pergunta pendente, os últimos pedidos que VOCÊ digitou, pendências, pasta de trabalho, ramo e commits, memória editada, arquivos e decisões.',
            'Opcional, desligada: a limpeza na mesma sessão (Configurações). A gestora avisa, limpa a conversa (o app pede o seu ok) e só recomeça quando você mandar uma mensagem; aí ela diz que a conversa foi limpa e que pode prosseguir.',
            'Aba Sessões: a corrente da gestora (transcrição anterior → atual) e a linha do tempo dos capítulos. Capítulos e decisões ficam para sempre.',
            'Transcrições antigas só saem se você autorizar (uma vez por projeto, na aba Sessões), depois de 7 dias e só se estiverem no backup mais novo, conferido e idêntico.',
            'Precisa dos ganchos do Claude Code ligados (Configurações › Agentes ao vivo instantâneo, ou o passo do primeiro uso). Com eles ligados, se o Cérebro estiver fechado (por exemplo, o PC reiniciou), o próprio gancho o liga em segundo plano, sem janela, no máximo uma vez a cada 2 minutos.',
            [cod('~/.cerebro/GESTOR.md'), ': o manual que a gestora lê (refeito a cada versão). Em Configurações do projeto, "Manual do gestor neste projeto" liga a leitura automática pelo CLAUDE.local.md.']])),
        secao('O gestor pela linha de comando',
          h('p', null, 'O gestor (a conversa principal) usa o ', cod('cerebro_cli.py'), ', que funciona mesmo com o servidor fechado e grava nos mesmos arquivos:'),
          bloco('python cerebro_cli.py estado MeuProjeto\n' +
            'python cerebro_cli.py a-conferir MeuProjeto\n' +
            'python cerebro_cli.py conferir MeuProjeto <id-ou-trecho-da-descrição> --resultado aprovado --nota "diff e testes ok"\n' +
            'python cerebro_cli.py decisao MeuProjeto "texto" --tipo decisao --origem dono\n' +
            'python cerebro_cli.py tarefas MeuProjeto --novas\n' +
            'python cerebro_cli.py tarefa MeuProjeto <id> --estado andamento --nota "comecei"\n' +
            'python cerebro_cli.py tarefa-feita MeuProjeto <id> --nota "feito"\n' +
            'python cerebro_cli.py analisar MeuProjeto\n' +
            'python cerebro_cli.py orcamento MeuProjeto --mes 80\n' +
            'python cerebro_cli.py backup --agora\n' +
            'python cerebro_cli.py agendar backup --ligar\n' +
            'python cerebro_cli.py memoria MeuProjeto --avisos\n' +
            'python cerebro_cli.py hooks --previa\n' +
            'python cerebro_cli.py encaixe MeuProjeto --previa\n' +
            'python cerebro_cli.py explicar MeuProjeto --estimar'),
          h('p', { class: 'nota' }, 'Resultados de conferência: aprovado (serviu como veio), corrigido (o gestor precisou mexer), recusado (não serviu). Rode estes comandos na pasta onde você instalou o Cérebro. Os comandos que escrevem fora do ~/.cerebro (backup --restaurar, hooks --instalar, encaixe --aplicar, instalar-ferramenta, agentes-copiar) só gravam com --confirmar; sem ele mostram só a prévia. python cerebro_cli.py --help lista todos.')),
        secao('Onde ficam os dados',
          lista([[cod('~/.cerebro/'), ': tudo do Cérebro.'],
            [cod('config.json'), ': projetos, gestoras, preços, rotinas, agentes por tipo, departamentos, comandos permitidos.'],
            [cod('projetos\\<projeto>\\'), ': indice.json (cache das conversas, pode apagar), mapa\\ (dados da página do mapa), revisoes.json (fila a conferir), decisoes.jsonl, propostas.json, tarefas.json, analises.json, ferramentas\\ (execuções e saídas), previa_agentes\\.'],
            [cod('novidades.json'), ' e ', cod('projetos\\_cerebro\\'), ': novidades e propostas do próprio Cérebro.'],
            [cod('hooks_token'), ', ', cod('ganchos.json'), ', ', cod('claude_status.json'), ', ', cod('eventos\\'), ': segredo e estado dos ganchos, limites de 5 horas e da semana e os eventos dos últimos 7 dias. ', cod('avisos.json'), ' e ', cod('orcamento.json'), ': avisos e limites de gasto.'],
            [cod('copias\\'), ': cópia de tudo o que o Cérebro trocou (memória, decisões, settings.json, arquivos de projetos, restaurações). ', cod('rotinas\\'), ': registro de cada rotina do Windows.'],
            [cod('~\\CerebroBackup\\'), ': os backups diários (.zip). Fica fora de ~/.cerebro de propósito.'],
            'Fora disso, o Cérebro só grava, e só com a sua confirmação: memórias em ~/.claude/projects/<projeto>/memory, o settings.json do Claude Code e os arquivos do plano de encaixe dentro dos projetos.'])),
        secao('Segurança',
          lista(['O servidor só escuta em 127.0.0.1 e exige a chave (cookie HttpOnly). Nada sai do PC, exceto a busca de novidades (que você dispara e que só pergunta a versão mais nova de ferramentas públicas) e a explicação do mapa por IA, só quando você clica em Explicar.',
            'Segredos que aparecem em conversas (chaves, senhas, tokens) são mascarados antes de qualquer texto ir para a tela, inclusive na saída dos comandos.',
            'Comandos de ferramentas só rodam quando você clica em Rodar, de uma lista FECHADA por projeto no config.json (a página manda só o id), sem shell, com tempo limite e sem janela. Os comandos sugeridos (testes, lint...) só entram nessa lista se você aprovar na aba Ferramentas.',
            'O Cérebro NÃO escreve fora do ~/.cerebro sem o seu clique de confirmação (ou --confirmar na linha de comando). Isso vale para backup e restauração, edição de memória, ganchos no settings.json, tarefas do Windows, instalação de ferramentas e plano de encaixe. Cada um mostra antes o que vai mudar, guarda cópia e nunca apaga o que é seu.',
            'Apagar: só dentro do ~/.cerebro (uma trava central), mais a rotação das cópias antigas de backup, que nunca remove a mais nova.',
            'O que vai para uma IA: só a explicação do mapa, quando você clica, com trechos curtos e segredos mascarados. Nada mais sai do PC, fora a busca de novidades.'])),
        secao('O que roda sozinho e o que só com o seu sim',
          lista(['Sozinho, com o servidor aberto: refazer a página do mapa quando o graph.json muda; a análise sem IA no prazo configurado.',
            'Só quando você clica: rodar comandos de ferramentas, "Analisar agora", "Procurar novidades" (a busca automática vem desligada), "Fazer backup agora", "Explicar" no mapa.',
            'Só com a sua aprovação (prévia + confirmação): instalar ferramentas, ligar os ganchos, criar as rotinas no Windows, restaurar um backup, gravar na memória, aplicar o plano de encaixe e copiar os agentes para .claude/agents.',
            'Sozinho, mesmo sem clique: os avisos do Windows (ligados por padrão; dá para desligar) e, depois que você ligar as rotinas no Windows, o que você escolheu agendar.',
            'Com os ganchos ligados: o capítulo da gestora é gravado antes de cada compactação (e na limpeza, se você ligar), o Cérebro é ligado sozinho quando está fechado, e as tarefas novas chegam à gestora como contexto. A remoção de transcrições antigas da gestora só acontece se você autorizar o projeto na aba Sessões.'])),
        secao('Rotina sugerida',
          lista(['De manhã: abra o painel geral e veja "Precisa de você", no pé da barra lateral.',
            'Durante o trabalho: o gestor confere cada subagente que termina (A conferir) e registra as decisões.',
            'Uma vez por semana: abra Análise, leia as propostas e aprove só o que vale a pena; as aprovadas viram tarefas para o gestor.',
            'De vez em quando: confira em Configurações se o último backup está em dia e olhe o Orçamento.'])))
    );
  };
})();
