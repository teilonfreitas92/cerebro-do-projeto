/* Cérebro do Projeto — tela "Bem-vindo" (primeiro uso guiado). Texto fixo e dados da própria máquina; nada vem de fora e nada vira HTML. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, haQuanto, api, post } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);

  UI.telas.bemvindo = function telaBemVindo(raiz) {
    const passos = ['Seus projetos', 'Sessão gestora', 'Mapa', 'Comandos sugeridos', 'Ganchos (recomendado)', 'Pronto'];
    let passo = 0, projetos = [];
    const palco = h('div'), trilha = h('nav', { class: 'abas', 'aria-label': 'Passos do primeiro uso' });
    raiz.replaceChildren(h('a', { class: 'bt leve fino', href: '#/' }, '← Todos os projetos'),
      h('div', { class: 'titulo-pagina' }, h('h2', null, 'Bem-vindo ao Cérebro do Projeto')), trilha, palco);

    const ir = n => { passo = Math.max(0, Math.min(passos.length - 1, n)); desenhar(); window.scrollTo(0, 0); };
    const navegacao = (proximoTexto) => h('div', { class: 'barra', estilo: { marginTop: '14px' } },
      passo > 0 ? h('button', { type: 'button', class: 'bt leve', onclick: () => ir(passo - 1) }, '← Voltar') : null, h('span', { class: 'espaco' }),
      h('button', { type: 'button', class: 'bt leve', title: 'Você pode voltar a este guia pelo botão Como usar', onclick: () => ir(passo + 1) }, 'Pular'),
      passo < passos.length - 1 ? h('button', { type: 'button', class: 'bt pri', onclick: () => ir(passo + 1) }, proximoTexto || 'Próximo →') : null);

    /* ---------- 1. projetos ---------- */
    function passoProjetos() {
      trocar(palco, h('section', { class: 'cartao guia' }, h('h3', null, 'Os projetos que encontrei'),
        h('p', null, 'O Cérebro lê as pastas do Claude Code no seu computador (', h('code', null, '~/.claude/projects'), ') e mostra cada projeto que você já abriu por lá. Tudo fica nesta máquina; nada é enviado a lugar nenhum.'),
        projetos.length
          ? h('ul', { class: 'lista' }, projetos.map(p => h('li', null, h('b', null, p.nome), h('span', { class: 'muted t' }, p.caminho), p.git && p.git.repositorio ? h('span', { class: 'chip accent' }, '⎇ ' + p.git.ramo) : h('span', { class: 'chip' }, 'sem git'))))
          : h('div', { class: 'vazio' }, 'Ainda não achei nenhum projeto. Abra uma pasta no Claude Code (ou adicione uma pasta em Configurações › "Adicionar projeto") e volte aqui.'),
        h('p', { class: 'nota' }, 'Quer esconder algum? Em Configurações você desmarca o projeto. Para nunca mostrar certos projetos, use "nunca_entrar" no config.json.')),
        navegacao('Escolher a sessão gestora →'));
    }

    /* ---------- 2. gestora ---------- */
    async function passoGestora() {
      trocar(palco, h('div', { class: 'vazio' }, 'Lendo as sessões…'));
      const blocos = [];
      for (const p of projetos) {
        let sessoes = [];
        try { sessoes = (await api(base(p.slug) + '/sessoes')).sessoes || []; } catch (e) { sessoes = []; }
        const atual = p.gestora_conversa || '';
        const sel = h('select', { 'aria-label': 'Sessão gestora de ' + p.nome }, h('option', { value: '' }, '(nenhuma por enquanto)'),
          sessoes.slice(0, 40).map(s => h('option', { value: s.id, selected: s.id === atual }, (s.titulo || s.id).slice(0, 70) + (s.ultima ? ' · ' + haQuanto(s.ultima) : ''))));
        const apelido = h('input', { type: 'text', maxlength: 80, placeholder: 'Apelido (opcional), ex.: Gestora principal', 'aria-label': 'Apelido da gestora' });
        const msg = h('span', { class: 'muted' });
        const salvar = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          salvar.disabled = true; msg.textContent = '';
          try { await post(base(p.slug) + '/gestora', { conversa: sel.value, nome: apelido.value }); msg.textContent = sel.value ? 'Salvo.' : 'Sem gestora.'; } catch (e) { msg.textContent = e.message; }
          salvar.disabled = false;
        } }, 'Salvar');
        blocos.push(h('section', { class: 'cartao' }, h('h3', null, p.nome), sessoes.length ? h('div', { class: 'acoes-conf' }, sel, apelido, salvar, msg) : h('p', { class: 'muted' }, 'Este projeto ainda não tem sessões do Claude Code.')));
      }
      trocar(palco, h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'A sessão gestora é a conversa principal do projeto: nela você conversa com o melhor modelo, e ela delega o trabalho pesado a agentes menores e CONFERE o que eles entregam. O Cérebro mostra os subagentes dela na fila "a conferir". Escolha uma por projeto (dá para trocar quando quiser em Configurações).'),
        h('div', { class: 'grade' }, blocos.length ? blocos : [h('div', { class: 'vazio' }, 'Nenhum projeto ainda.')]), navegacao('Gerar o mapa →'));
    }

    /* ---------- 3. mapa ---------- */
    async function passoMapa() {
      trocar(palco, h('div', { class: 'vazio' }, 'Olhando os mapas…'));
      const blocos = [];
      for (const p of projetos) {
        let m = {};
        try { m = await api(base(p.slug) + '/mapa/estado'); } catch (e) { m = {}; }
        const msg = h('div', { class: 'nota' });
        const botao = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          botao.disabled = true; msg.textContent = 'Gerando… (pode levar alguns minutos em projetos grandes)';
          try {
            const r = await post(base(p.slug) + '/mapa/criar', {});
            msg.textContent = 'Pronto! O mapa foi criado. ' + (r.ja_no_gitignore ? '' : 'Dica: ponha "graphify-out/" no .gitignore do projeto, para a pasta não subir no seu repositório.');
          } catch (e) { msg.textContent = e.message; botao.disabled = false; }
        } }, m.graphify ? 'Refazer o mapa' : 'Gerar o mapa');
        blocos.push(h('section', { class: 'cartao' }, h('h3', null, p.nome, m.graphify ? h('span', { class: 'chip ok' }, m.gerado ? 'mapa pronto' : 'Graphify pronto') : h('span', { class: 'chip' }, 'sem mapa')),
          h('div', { class: 'acoes-conf' }, botao), msg));
      }
      trocar(palco, h('section', { class: 'cartao guia' }, h('h3', null, 'O mapa do código'),
        h('p', null, 'O mapa mostra os arquivos e como eles se ligam, em departamentos coloridos. Quem desenha é o ', h('b', null, 'Graphify'), ' (opcional, instalado à parte).'),
        h('p', null, h('b', null, 'O que acontece ao clicar em "Gerar o mapa": '), 'o Graphify roda ', h('b', null, 'dentro da pasta do projeto'), ' (comando ', h('code', null, 'graphify update .'), ') e cria lá a pasta ', h('code', null, 'graphify-out'), '. Isso só acontece quando você clica. O Cérebro então monta a página do mapa em ', h('code', null, '~/.cerebro'), '. Sugestão: ponha ', h('code', null, 'graphify-out/'), ' no ', h('code', null, '.gitignore'), ' do projeto (o Cérebro não mexe no seu .gitignore).'),
        h('p', { class: 'nota' }, 'Ainda não instalou o Graphify? ', h('code', null, 'uv tool install graphifyy'), ' ou ', h('code', null, 'pip install graphifyy'), ' (o instalar.py oferece isso). Dá para pular este passo e voltar depois.')),
        h('div', { class: 'grade' }, blocos.length ? blocos : [h('div', { class: 'vazio' }, 'Nenhum projeto ainda.')]), navegacao('Comandos sugeridos →'));
    }

    /* ---------- 4. comandos ---------- */
    async function passoComandos() {
      trocar(palco, h('div', { class: 'vazio' }, 'Procurando comandos nos projetos…'));
      const blocos = [];
      for (const p of projetos) {
        let lista = [];
        try { lista = (await api(base(p.slug) + '/comandos/sugeridos')).sugestoes || []; } catch (e) { lista = []; }
        const caixa = h('div');
        const pintar = (l) => { trocar(caixa, UI.secaoSugestoes(p.slug, l, async () => { try { pintar((await api(base(p.slug) + '/comandos/sugeridos')).sugestoes || []); } catch (e) { /* mantém */ } })); };
        pintar(lista);
        blocos.push(h('div', null, h('h3', { class: 'sub-titulo' }, p.nome), caixa));
      }
      trocar(palco, h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'Para cada projeto, o Cérebro SUGERE comandos de teste e de verificação que achou lendo os arquivos. Nenhum roda sozinho: você aprova o que quer ter à mão na aba Ferramentas, e depois só roda quando clicar em "Rodar".'),
        ...blocos, navegacao());
    }

    /* ---------- 5. pronto ---------- */
    function passoPronto() {
      trocar(palco, h('section', { class: 'cartao guia' }, h('h3', null, 'Pronto!'),
        h('p', null, 'Seus projetos estão no painel. Algumas dicas para começar:'),
        h('ul', null, h('li', null, 'Abra um projeto e veja a ', h('b', null, 'Visão geral'), ' e os ', h('b', null, 'Agentes ao vivo'), '.'),
          h('li', null, 'A aba ', h('b', null, 'A conferir'), ' mostra cada subagente que terminou e espera o seu gestor conferir.'),
          h('li', null, 'Em ', h('b', null, 'Análise'), ' clique em "Analisar agora" para receber propostas de melhoria (sem IA).'),
          h('li', null, 'O botão ', h('b', null, 'Como usar'), ' (no topo) explica cada aba.')),
        h('div', { class: 'barra' }, h('button', { type: 'button', class: 'bt pri', onclick: async () => {
          try { await post('/api/config', { primeiro_uso_concluido: true }); } catch (e) { /* não impede de entrar */ }
          location.hash = '#/';
        } }, 'Ir para o painel'))),
        h('div', { class: 'barra', estilo: { marginTop: '10px' } }, h('button', { type: 'button', class: 'bt leve', onclick: () => ir(passo - 1) }, '← Voltar')));
    }

    function desenhar() {
      trilha.replaceChildren(...passos.map((nome, i) => h('a', { class: 'aba' + (i === passo ? ' ativa' : ''), href: '#/bem-vindo', onclick: ev => { ev.preventDefault(); ir(i); } }, (i + 1) + '. ' + nome)));
      [passoProjetos, passoGestora, passoMapa, passoComandos, () => (UI.passoGanchos ? UI.passoGanchos(palco, navegacao) : ir(passo + 1)), passoPronto][passo]();   // ganchos: gestora.js
    }

    api('/api/projetos').then(d => { projetos = d.projetos || []; desenhar(); }).catch(e => trocar(palco, h('div', { class: 'vazio' }, 'Não consegui ler os projetos: ' + e.message)));
  };
})();
