# Segurança

O Cérebro do Projeto lê as suas conversas e a memória do Claude Code, por isso levamos segurança a sério. Obrigado por relatar com cuidado.

## Como relatar uma falha (em particular)

**Não abra uma issue pública** para falha de segurança: ela fica visível para todo mundo antes da correção.

1. Na página do repositório no GitHub, abra a aba **Security** (Segurança).
2. Clique em **Report a vulnerability** (Relatar uma vulnerabilidade). Isso abre um *security advisory* privado, que só você e quem
   mantém o projeto veem.
3. Descreva:
   - o que acontece e qual o risco (o que alguém conseguiria ler, gravar ou apagar);
   - a versão do Cérebro (está em Configurações › Aparência e servidor, ou no `CHANGELOG.md`) e o sistema (Windows, macOS, Linux);
   - os passos para reproduzir, de preferência com a **demonstração** (`python demo/rodar_demo.py`), que usa dados inventados.

**Não mande** conversas reais, memória, chaves, tokens, senhas nem caminhos com o seu nome. Se precisar de um exemplo, use dados fictícios.

Você recebe uma resposta assim que possível (é um projeto mantido por voluntários, sem prazo garantido). Combinamos juntos quando a
falha pode ser divulgada, depois que a correção sair. Se quiser, seu nome entra nos agradecimentos da versão.

## O que está no escopo

Falhas no código deste repositório, por exemplo:

- acesso ao painel ou às rotas **sem a chave** (token/cookie), ou a partir de outro site (Host, Origin, CSRF, DNS rebinding);
- o servidor aceitando conexões de fora de `127.0.0.1`;
- **segredo** de uma conversa (chave, token, senha) aparecendo na tela sem o mascaramento;
- texto de conversa ou memória sendo interpretado como HTML ou script na página;
- o Cérebro **escrevendo ou apagando** fora do que está documentado (fora de `~/.cerebro` sem a sua confirmação, ou apagando algo seu);
- comando externo rodando sem aprovação, com shell, ou com argumentos vindos da página;
- o receptor dos ganchos (`/api/hooks/evento`) aceitando chamada sem o segredo próprio, ou devolvendo dado a quem não deveria;
- algo saindo do computador além do documentado (consulta pública de Novidades e a explicação por IA, só quando você clica);
- o instalador, o desinstalador ou as rotinas no Windows fazendo mais do que dizem.

## Fora do escopo

- Falhas do **Claude Code**, do **Graphify** ou das ferramentas que o Cérebro detecta ou instala: relate a quem mantém cada uma.
- Ataques que já exigem controle total da sua conta no computador (quem já é você pode ler `~/.cerebro` direto).
- A estimativa de custo diferir da fatura (é estimativa por definição; isso é uma issue comum).
- Pedidos de recurso de segurança novo sem uma falha concreta: abra como **Ideia**.

## Versões atendidas

Correções de segurança saem na versão mais nova. Atualize com `git pull` e `python instalar.py`.
