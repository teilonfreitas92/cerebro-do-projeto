# Módulo mapa

Página do mapa do código do projeto (grafo 2D em forma de "cérebro" + painel de leitura com linha do tempo), feita a partir
do mapa do **Graphify** do projeto (`<projeto>\graphify-out\`). É a v0 construída pela sessão coordenadora, trazida para
dentro do Cérebro como módulo. Motor de forças (Barnes-Hut) e desenho em Canvas 2D são próprios (`cerebro.js`), sem
biblioteca. Visual próprio (escuro por padrão, claro com ◐; usa a mesma preferência de tema do painel).

Quem mostra a página é o servidor do Cérebro (aba **Mapa** do projeto, rota `/mapa/<slug>/`), com o mesmo token e cookie.
Os dados vêm do projeto escolhido. A auto-recarga continua: a página confere sozinha a cada 30 s se há `dados.js` novo e
atualiza sem perder zoom nem posição, avisando "Atualizado: +N / −M".

## Gerar o mapa de um projeto

```
python mapa\gerar.py --projeto C:\Projetos\MeuProjeto
python mapa\gerar.py --projeto C:\Projetos\MeuProjeto --esperar     # espera o graph.json ficar mais novo (até 15 min)
python mapa\gerar.py --entrada PASTA --saida PASTA                       # caminhos explícitos (testes)
python mapa\gerar.py --projeto PASTA --standalone                        # copia a página junto: abre por file://
```

* `--projeto` lê `<projeto>\graphify-out\` (graph.json, .graphify_analysis.json, .graphify_labels.json, `.graphify_root`)
  e os arquivos-fonte (só o cabeçalho de cada um, para "o que faz").
* A saída padrão é `~/.cerebro\projetos\<slug>\mapa\`: `dados.js`, `historico.json` (o que entrou/saiu entre
  uma geração e a anterior) e `.estado.json.gz` (foto da geração anterior, só para comparar). **Nada é escrito dentro do
  projeto.** `<slug>` = nome de pasta do Claude Code (`C--Users-ana-Projetos-Loja`).
* Só **lê** o Graphify; nunca roda comandos dele. Sem `graphify-out`, sai com a explicação (código 2) e a aba Mapa mostra
  um aviso. Gerar o Graphify de outros projetos fica para a instalação adaptativa, com aprovação do dono.
* Roda em ~2 s. A aba Mapa também tem o botão "Atualizar a página do mapa agora" (chama o mesmo `gerar.py`).

## Atualização automática (ainda NÃO ligada: depende da autorização do dono)

Linha que os ganchos do git do projeto devem chamar (em segundo plano, para não travar o commit):

```
python mapa\gerar.py --projeto C:\Projetos\MeuProjeto --esperar
```

Com `--esperar` o gerador aguarda o `graph.json` ficar mais novo que o momento do disparo (o Graphify reescreve o mapa
depois do commit), espera o arquivo parar de crescer e então gera; se em 15 minutos o mapa não mudar, sai sem gerar nada.

## Sessão gestora

Vem do `config.json` global do Cérebro (`gestoras.<slug>`), não mais de arquivo ao lado do script. O `gerar.py` grava
no `dados.js`, e o servidor entrega `gestora.json` ao vivo: trocar a gestora em Configurações vale na hora, sem refazer o mapa.

## O que cada parte faz

* **Visão geral:** os grupos do Graphify (tamanho = nº de itens, cor = departamento, linha = ligações entre grupos). Os
  nomes vêm de `.graphify_labels.json`.
* **Duplo clique / "Abrir grupo":** arquivos e funções do grupo, com os vizinhos de outros grupos apagados (até 110).
  Linhas tracejadas = ligação *inferida* pelo Graphify.
* **Janela lateral (clique num ponto):** nome, departamento, grupo, arquivo:linha, **o que faz** (texto real do
  código), números e "Ligado a" por tipo, com vizinhos clicáveis. Sem texto no código, só os fatos.
* **Interação:** arrastar prende o ponto (alfinete); duplo clique solta; arrastar o fundo move; roda dá zoom (pinça no
  toque); "Voltar ao padrão"; "Centralizar"; "Soltar pontos"; busca (`/`); legenda liga/desliga departamentos; ✦ pulsos;
  ◐ tema. Teclas: `/` busca, `Esc` fecha o painel, `0` volta ao padrão.
* **Aba Painel (só leitura):** sessão gestora, última atualização (data, commit, ramo), maiores centros, surpresas, barras
  por departamento, "quem fala com quem", tipos de ligação e **linha do tempo** clicável (últimas 100 gerações).

## Departamentos (cores)

Configuráveis por projeto em `~/.cerebro/config.json` > `departamentos` (ou na tela Configurações do projeto). Sem configuração, uma cor por pasta
de primeiro nível (as 10 maiores; o resto vira "Outros"). Com regras, vale o PRIMEIRO departamento da lista que casar; cada regra de caminho pode
ser um prefixo (`src/`), um curinga (`*.test.js`), uma palavra (`chat`) ou uma expressão regular (`re:^app/.*\\.ts$`); cada departamento pode
levar `cor` e, opcionalmente, `ancora` [x, y] (a posição dele no desenho do "cérebro").

## Limites conhecidos

* Só ~13% dos itens têm explicação (é o que o código tem de docstring/comentário); o resto mostra fatos.
* Um grupo aberto mostra no máximo 110 vizinhos de outros grupos; a lista completa está na janela lateral de cada ponto.
* O mapa é o do Graphify (extração estática): chamadas dinâmicas e ligações entre linguagens podem faltar ou aparecer
  como "inferidas".
* Fontes IBM Plex Sans / Chakra Petch só aparecem se instaladas no PC (sem internet a página usa as do sistema).
* A comparação da linha do tempo é entre duas gerações seguidas; mapa refeito sem mudança não cria entrada.
* Dentro do Cérebro a página roda num iframe com `allow-same-origin` (precisa do cookie para ler `dados.js`): é código
  nosso, servido de `mapa\`, não de fora.
