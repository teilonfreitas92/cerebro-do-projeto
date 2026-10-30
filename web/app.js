/* Cérebro do Projeto — painel (JS puro, sem build). Os utilitários ficam em ui.js; as abas novas em abas.js e abas2.js.
   Regra de segurança: NADA que vem de transcrição, memória ou configuração entra na página como HTML. Tudo é criado com
   h() / textContent, então um texto malicioso num transcrito não executa nada. */
(() => {
  'use strict';
  const { raiz, limpar, limpezas, h, s, trocar, num, tok, usd, haQuanto, dataCurta, hora, modeloCurto, tamanho, guardar, lembrar, api, post, cada, aoVivo,
    icone, gaveta, abasInternas, encaixar } = window.CerebroUI;

  /* ---------- tema e anéis de limite ---------- */
  function aplicarTema(escuro) {
    document.documentElement.setAttribute('data-tema', escuro ? 'escuro' : 'claro');
    guardar('tema', escuro ? 'escuro' : 'claro');
  }
  document.getElementById('b-tema').addEventListener('click', () => {
    const escuro = document.documentElement.getAttribute('data-tema') !== 'escuro';
    aplicarTema(escuro);
    post('/api/config', { tema: escuro ? 'escuro' : 'claro' }).catch(() => {});
  });
  function anel(rotulo, pct, renova) {
    const p = Math.max(0, Math.min(100, Number(pct) || 0)), r = 12, c = 2 * Math.PI * r;
    const cor = p > 85 ? 'var(--danger)' : p > 60 ? 'var(--warn)' : 'var(--accent)';
    return h('div', { class: 'anel', title: rotulo + ': ' + p.toFixed(0) + '% usado' + (renova ? ' · renova ' + renova : '') },
      s('svg', { viewBox: '0 0 30 30' }, s('circle', { cx: 15, cy: 15, r, fill: 'none', stroke: 'var(--surface-3)', 'stroke-width': 4 }),
        s('circle', { cx: 15, cy: 15, r, fill: 'none', stroke: cor, 'stroke-width': 4, 'stroke-linecap': 'round', 'stroke-dasharray': c, 'stroke-dashoffset': c * (1 - p / 100), transform: 'rotate(-90 15 15)' })),
      h('span', null, rotulo + ' ', h('b', null, p.toFixed(0) + '%')));
  }
  function desenharAneis(l) {
    const el = document.getElementById('aneis');
    el.replaceChildren();
    if (!l || !l.disponivel) return;
    if (l.cinco_horas && l.cinco_horas.percentual != null) el.append(anel('5 h', l.cinco_horas.percentual));
    if (l.sete_dias && l.sete_dias.percentual != null) el.append(anel('7 dias', l.sete_dias.percentual));
    if (l.contexto) el.append(anel('contexto', l.contexto.percentual));
  }

  /* ---------- roteador ---------- */
  function rota() {
    limpar();
    const [caminho, consulta] = location.hash.replace(/^#\/?/, '').split('?');
    const p = caminho.split('/').filter(Boolean).map(decodeURIComponent);
    raiz.scrollTop = 0;
    window.scrollTo(0, 0);
    const tela = p[0] === 'p' && p[1] ? 'projeto' : ['config', 'guia', 'bem-vindo'].includes(p[0]) ? p[0] : 'hub';
    raiz.className = 'principal tela-' + tela;
    const slug = tela === 'projeto' ? p[1] : null;
    if (slug !== LAT.rota.slug) LAT.info = null;
    LAT.rota = { tela, slug, aba: tela === 'projeto' ? (p[2] || 'visao') : null };
    abrirMenu(false);
    desenharLateral();
    if (tela === 'config') return telaConfig(null);
    if (tela === 'guia') {                     // um assunto por vez, escolhido no menu à esquerda
      window.CerebroUI.telas.guia(raiz);
      const grade = raiz.querySelector('.guia-grade');
      if (grade) { grade.classList.add('conteudo'); encaixar(grade, { chave: 'guia', menu: true }); }
      return;
    }
    if (tela === 'bem-vindo') return window.CerebroUI.telas.bemvindo(raiz);
    if (tela === 'projeto') return telaProjeto(p[1], p[2] || 'visao', new URLSearchParams(consulta || ''));
    return telaHub();
  }
  window.addEventListener('hashchange', rota);

  /* ====================================================================================================== */
  /* Barra lateral: todos os projetos, a lista de projetos, as seções do projeto aberto e "Precisa de você"   */
  /* ====================================================================================================== */
  const lateral = document.getElementById('lateral'), lateralFundo = document.getElementById('lateral-fundo'), bMenu = document.getElementById('b-menu');
  const LAT = { projetos: null, fila: [], info: null, rota: { tela: 'hub', slug: null, aba: null } };
  const iniciais = nome => (String(nome).replace(/[^\p{L}\p{N}]+/gu, ' ').trim().split(' ').filter(Boolean).slice(0, 2).map(x => x[0]).join('') || '?').toUpperCase();
  function aplicarRecolhida() {
    document.body.classList.toggle('lateral-recolhida', lembrar('lateral') === 'recolhida');
  }
  function abrirMenu(abrir) {
    document.body.classList.toggle('menu-aberto', !!abrir);
    lateralFundo.hidden = !abrir;
    bMenu.setAttribute('aria-expanded', String(!!abrir));
  }
  bMenu.addEventListener('click', () => abrirMenu(!document.body.classList.contains('menu-aberto')));
  lateralFundo.addEventListener('click', () => abrirMenu(false));
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && document.body.classList.contains('menu-aberto')) abrirMenu(false); });

  function contadorLat(n, classe, titulo) { return n ? h('span', { class: 'lat-n' + (classe ? ' ' + classe : ''), title: titulo || null }, String(n)) : null; }
  function itemLat(href, ico, rotulo, extra, ativo) {
    return h('a', { class: 'lat-item' + (ativo ? ' ativo' : ''), href, title: rotulo, 'aria-current': ativo ? 'page' : null }, icone(ico), h('span', { class: 'lat-rot' }, rotulo), extra);
  }
  function contadoresAba(id, info) {
    if (!info) return null;
    if (id === 'agentes' && info.agentes_ativos) return contadorLat(info.agentes_ativos, 'ok', 'agentes escrevendo agora');
    if (id === 'conferir' && info.conferir && info.conferir.a_conferir) return contadorLat(info.conferir.a_conferir, 'alerta', 'subagentes esperando o gestor');
    if (id === 'analise' && info.propostas && (info.propostas.novas || info.propostas.tarefas_abertas)) return contadorLat(info.propostas.novas + info.propostas.tarefas_abertas, 'ok', 'propostas novas + tarefas abertas');
    if (id === 'tarefas' && info.tarefas && info.tarefas.abertas) return contadorLat(info.tarefas.abertas, info.tarefas.conferir ? 'alerta' : 'ok', 'tarefas abertas (a conferir: ' + info.tarefas.conferir + ')');
    return null;
  }
  function desenharLateral() {
    const r = LAT.rota, ps = LAT.projetos || [];
    const antes = lateral.querySelector('.lat-projetos');
    const rolagem = antes ? antes.scrollTop : 0;
    const projetos = h('div', { class: 'lat-projetos' }, LAT.projetos === null ? h('div', { class: 'lat-vazio' }, 'Carregando…')
      : ps.length ? ps.map(p => {
        const conf = p.conferir && p.conferir.a_conferir;
        const estado = p.agentes_ativos ? 'trabalhando' : p.ultima_atividade && Date.now() / 1000 - p.ultima_atividade < 86400 ? 'recente' : 'quieto';
        const destino = '#/p/' + encodeURIComponent(p.slug) + '/' + (r.slug && r.aba ? r.aba : 'visao');   // troca de projeto e fica na mesma seção
        return h('a', { class: 'lat-proj' + (p.slug === r.slug ? ' ativo' : ''), href: destino, 'aria-current': p.slug === r.slug ? 'page' : null,
          title: p.nome + (p.agentes_ativos ? ' · ' + p.agentes_ativos + ' agente(s) escrevendo agora' : estado === 'recente' ? ' · ativo nas últimas 24 h' : '') + (conf ? ' · ' + conf + ' a conferir' : '') },
          h('span', { class: 'lat-av', 'aria-hidden': 'true' }, iniciais(p.nome), h('span', { class: 'ponto ' + estado })),
          h('span', { class: 'lat-rot' }, p.nome), conf ? h('span', { class: 'lat-selo', title: 'subagentes a conferir' }, conf + ' a conferir') : null);
      }) : h('div', { class: 'lat-vazio' }, 'Nenhum projeto.'));
    const info = r.slug ? (LAT.info || ps.find(p => p.slug === r.slug)) : null;
    const secoes = r.slug ? [h('div', { class: 'lat-titulo', title: info ? info.nome : r.slug }, h('span', { class: 'lat-rot' }, 'Seções' + (info ? ' · ' + info.nome : ''))),
      h('nav', { class: 'lat-secoes', 'aria-label': 'Seções do projeto' },
        ABAS.map(([id, nome]) => itemLat('#/p/' + encodeURIComponent(r.slug) + '/' + id, id, nome, contadoresAba(id, info), id === r.aba)))]
      : [h('div', { class: 'lat-espaco' })];
    const nFila = LAT.fila.length, nAcao = LAT.fila.filter(i => i.nivel === 'acao' || i.nivel === 'aviso').length;
    const recolhida = lembrar('lateral') === 'recolhida';
    lateral.replaceChildren(
      h('div', { class: 'lat-bloco' }, itemLat('#/', 'todos', 'Todos os projetos', null, r.tela === 'hub')),
      h('div', { class: 'lat-titulo' }, h('span', { class: 'lat-rot' }, 'Projetos')), projetos, secoes,
      h('div', { class: 'lat-base' },
        h('button', { type: 'button', class: 'lat-item fila-lat' + (nAcao ? ' tem' : ''), title: 'Precisa de você (' + nFila + ')', onclick: abrirFila },
          icone('fila'), h('span', { class: 'lat-rot' }, 'Precisa de você'), h('span', { class: 'lat-n' + (nAcao ? ' alerta' : '') }, String(nFila))),
        h('button', { type: 'button', class: 'lat-item so-largo', title: recolhida ? 'Abrir a barra lateral' : 'Recolher a barra lateral (só ícones)',
          'aria-label': recolhida ? 'Abrir a barra lateral' : 'Recolher a barra lateral', onclick: () => {
            guardar('lateral', recolhida ? 'aberta' : 'recolhida'); aplicarRecolhida(); desenharLateral();
            window.dispatchEvent(new Event('resize'));
          } }, icone(recolhida ? 'abrir' : 'recolher'), h('span', { class: 'lat-rot' }, 'Recolher'))));
    const novo = lateral.querySelector('.lat-projetos');
    if (novo) novo.scrollTop = rolagem;
  }
  function abrirFila() {
    const itens = LAT.fila;
    const conta = n => itens.filter(i => i.nivel === n).length;
    const partes = [[conta('acao'), 'ação', 'ações'], [conta('aviso'), 'aviso', 'avisos'], [itens.length - conta('acao') - conta('aviso'), 'informação', 'informações']]
      .filter(x => x[0]).map(x => x[0] + ' ' + (x[0] > 1 ? x[2] : x[1]));
    abrirMenu(false);
    gaveta('Precisa de você (' + itens.length + ')', h('div', { class: 'fila' },
      h('p', { class: 'muted', estilo: { margin: '0 0 10px' } }, itens.length ? partes.join(' · ') : 'Nada esperando você agora.'),
      h('ul', null, itens.map(i => h('li', null,
        h('span', { class: 'chip nv ' + (i.nivel === 'acao' ? 'warn' : i.nivel === 'aviso' ? 'perigo' : '') }, i.nivel === 'acao' ? 'ação' : i.nivel === 'aviso' ? 'aviso' : 'info'),
        h('div', null, h('b', null, i.titulo), h('span', null, i.texto)),
        i.projeto && i.aba ? h('a', { class: 'bt leve fino recolher', href: '#/p/' + encodeURIComponent(i.projeto) + '/' + i.aba }, 'Abrir')
          : i.link === '#/config' ? h('a', { class: 'bt leve fino recolher', href: '#/config' }, 'Abrir') : null)))), { lado: 'esquerda', classe: 'gaveta-fila' });
  }
  async function atualizarLateral() {
    try {
      const [d, f] = await Promise.all([api('/api/projetos?ocultos=0'), api('/api/fila')]);
      LAT.projetos = d.projetos; LAT.fila = f.itens || [];
      desenharAneis(d.limites);
      if (LAT.rota.slug) { const p = d.projetos.find(x => x.slug === LAT.rota.slug); if (p) LAT.info = p; }
      desenharLateral();
    } catch (e) { /* tenta de novo na próxima volta */ }
  }

  /* ====================================================================================================== */
  /* Painel geral (hub)                                                                                      */
  /* ====================================================================================================== */
  function telaHub() {
    let ocultos = false;
    const grade = h('div', { class: 'grade hub caixa-pag' }), topo = h('div', { class: 'titulo-pagina' }), faixa = h('div');
    raiz.replaceChildren(topo, faixa, window.CerebroUI.faixaHub ? window.CerebroUI.faixaHub() : null, grade);
    grade.append(h('div', { class: 'vazio' }, 'Carregando projetos…'));
    encaixar(raiz, { chave: 'hub' });       // os cartões viram páginas (1 2 3) em vez de rolar

    function cartao(p) {
      const g = p.git || {};
      const ativos = p.agentes_ativos || 0;
      return h('article', { class: 'cartao proj', tabindex: 0, role: 'link', 'aria-label': 'Abrir o cérebro de ' + p.nome,
        onclick: () => { location.hash = '#/p/' + encodeURIComponent(p.slug) + '/visao'; },
        onkeydown: e => { if (e.key === 'Enter') location.hash = '#/p/' + encodeURIComponent(p.slug) + '/visao'; } },
        h('h3', null, p.oculto ? h('span', { class: 'chip' }, 'oculto') : null, h('span', { class: 'nome-proj', title: p.nome }, p.nome),
          ativos ? h('span', { class: 'chip ok', title: 'agentes escrevendo agora' }, h('span', { class: 'ponto trabalhando' }), ativos + (ativos > 1 ? ' agentes' : ' agente')) : null),
        h('div', { class: 'caminho', title: p.caminho }, p.caminho),
        h('div', { class: 'linha' },
          g.repositorio ? h('span', { class: 'chip accent' }, '⎇ ' + g.ramo) : h('span', { class: 'chip' }, 'sem git'),
          g.commit ? h('span', { class: 'commit', title: g.assunto }, g.commit + ' · ' + g.assunto) : null),
        h('div', { class: 'nums' },
          h('div', { class: 'num' }, h('b', null, usd(p.hoje.custo, p.hoje.sem_preco)), h('small', null, 'hoje · ' + tok(p.hoje.tokens) + ' tokens')),
          h('div', { class: 'num' }, h('b', null, usd(p.semana.custo, p.semana.sem_preco)), h('small', null, '7 dias · ' + tok(p.semana.tokens) + ' tokens'))),
        h('div', { class: 'linha' },
          h('span', { class: 'chip', title: num(p.sessoes_total) + ' sessões no total' }, num(p.sessoes_recentes) + (p.sessoes_recentes === 1 ? ' sessão' : ' sessões') + ' (7 d) · ' + num(p.sessoes_total) + ' no total'),
          p.mapa.gerado ? h('span', { class: 'chip ok' }, 'mapa pronto') : p.mapa.graphify ? h('span', { class: 'chip warn' }, 'mapa não gerado') : h('span', { class: 'chip' }, 'sem mapa'),
          p.gestora ? h('span', { class: 'chip violet', title: 'sessão gestora' }, 'Gestor: ' + p.gestora) : null,
          p.indexando ? h('span', { class: 'chip warn' }, 'lendo sessões…') : null,
          p.conferir && p.conferir.a_conferir ? h('span', { class: 'chip warn', title: 'subagentes que o gestor ainda não conferiu' }, p.conferir.a_conferir + ' a conferir') : null,
          p.propostas && p.propostas.tarefas_abertas ? h('span', { class: 'chip violet', title: 'propostas aprovadas, esperando o gestor' }, p.propostas.tarefas_abertas + ' tarefa(s)') : null,
          p.tarefas && p.tarefas.do_dono_abertas ? h('span', { class: 'chip violet', title: 'tarefas que você criou e ainda não terminaram' + (p.tarefas.conferir ? ' (' + p.tarefas.conferir + ' a conferir)' : '') }, p.tarefas.do_dono_abertas + ' tarefa(s) sua(s)') : null,
          p.mapa.defasado ? h('span', { class: 'chip perigo', title: 'o mapa do Graphify está mais velho que o último commit' }, 'mapa atrasado') : null),
        h('div', { class: 'muted ultima' }, 'Última atividade: ' + (p.ultima_atividade ? haQuanto(p.ultima_atividade) + ' (' + dataCurta(p.ultima_atividade) + ')' : 'nenhuma sessão ainda')));
    }

    async function atualizar() {
      try {
        const d = await api('/api/projetos?ocultos=' + (ocultos ? 1 : 0));
        desenharAneis(d.limites);
        aplicarTema(lembrar('tema') ? lembrar('tema') !== 'claro' : d.tema !== 'claro');
        faixa.replaceChildren(...(!d.primeiro_uso_concluido && d.projetos.length ? [h('section', { class: 'cartao fila', estilo: { marginBottom: '12px' } },
          h('div', { class: 'barra', estilo: { justifyContent: 'space-between', margin: 0 } }, h('div', null, h('b', null, 'Primeiro uso: vamos configurar seus projetos?'),
            h('div', { class: 'muted' }, 'Escolher a sessão gestora de cada projeto, gerar o mapa e aprovar os comandos sugeridos. Leva uns minutos e você pode pular o que quiser.')),
            h('a', { class: 'bt pri', href: '#/bem-vindo' }, 'Começar')))] : []));
        topo.replaceChildren(h('h2', null, 'Seus projetos'), h('span', { class: 'muted' }, d.projetos.length + ' no painel'),
          h('span', { class: 'espaco' }),
          h('label', { class: 'chk muted' }, h('input', { type: 'checkbox', checked: ocultos, onchange: e => { ocultos = e.target.checked; atualizar(); } }), 'mostrar ocultos'));
        grade.replaceChildren(...(d.projetos.length ? d.projetos.map(cartao) : [h('div', { class: 'vazio' }, 'Nenhum projeto encontrado em .claude/projects.')]));
      } catch (e) { grade.replaceChildren(h('div', { class: 'vazio' }, 'Não consegui carregar os projetos: ' + e.message)); }
    }
    atualizar();
    cada(10000, atualizar);
  }

  /* ====================================================================================================== */
  /* Cérebro do projeto                                                                                      */
  /* ====================================================================================================== */
  const ABAS = [['visao', 'Visão geral'], ['agentes', 'Agentes ao vivo'], ['conferir', 'A conferir'], ['tarefas', 'Tarefas'], ['sessoes', 'Sessões'], ['memoria', 'Memória e decisões'],
    ['custos', 'Custos'], ['mapa', 'Mapa'], ['ferramentas', 'Ferramentas'], ['analise', 'Análise'], ['novidades', 'Novidades'], ['inventario', 'Inventário'],
    ['configuracoes', 'Configurações']];
  const TELAS = { visao: abaVisao, agentes: abaAgentes, sessoes: abaSessoes, memoria: abaMemoria, custos: abaCustos, mapa: abaMapa, configuracoes: abaConfig,
    ...window.CerebroUI.telas };

  async function telaProjeto(slug, aba, params) {
    const conteudo = h('div', { class: 'conteudo aba-' + aba });
    const cab = h('div', { class: 'cab-proj' });
    raiz.replaceChildren(cab, conteudo);
    let info = null;
    try {
      const d = await api('/api/projetos?ocultos=1');
      desenharAneis(d.limites);
      info = d.projetos.find(p => p.slug === slug);
    } catch (e) { /* segue sem cabeçalho */ }
    if (!info) { conteudo.append(h('div', { class: 'vazio' }, 'Projeto não encontrado.')); return; }
    LAT.info = info;
    desenharLateral();
    const g = info.git || {};
    const nomeAba = (ABAS.find(a => a[0] === aba) || ABAS[0])[1];
    cab.append(h('h2', { title: info.nome }, info.nome), h('span', { class: 'cab-secao' }, '› ' + nomeAba),
      g.repositorio ? h('span', { class: 'chip accent' }, '⎇ ' + g.ramo) : null,
      g.commit ? h('span', { class: 'chip', title: g.assunto }, g.commit + ' · ' + (g.assunto || '').slice(0, 60)) : null,
      info.gestora ? h('span', { class: 'chip violet' }, 'Gestor: ' + info.gestora) : h('span', { class: 'chip warn' }, 'sem gestora'),
      h('span', { class: 'caminho mono muted', title: info.caminho }, info.caminho));
    (TELAS[aba] || abaVisao)(slug, conteudo, info, params);
    if (aba !== 'mapa') encaixar(conteudo, { chave: 'p.' + aba, menu: aba === 'configuracoes' });   // cabe na tela: abas internas e páginas
  }

  /* ---------- Visão geral ---------- */
  function abaVisao(slug, el) {
    el.append(h('div', { class: 'vazio' }, 'Carregando…'));
    async function carregar() {
      let d;
      try { d = await api('/api/p/' + encodeURIComponent(slug) + '/visao'); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const n = d.numeros;
      const ges = d.gestora && d.gestora.nome;
      const caixa = (v, r, extra) => h('div', { class: 'num' }, h('b', null, v), h('small', null, r), extra);
      trocar(el,
        d.avisos.length ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '14px' } }, d.avisos.join(' ')) : null,
        h('div', { class: 'grade estreita', estilo: { marginBottom: '14px' } },
          caixa(num(n.sessoes), 'sessões'), caixa(num(n.subagentes), 'subagentes registrados'), caixa(num(n.agentes_ativos), 'agentes escrevendo agora'),
          caixa(num(n.memorias), 'itens de memória'), caixa(tok(n.contexto_fixo_tokens), 'tokens de contexto fixo por conversa'),
          caixa(usd(d.hoje.custo, d.hoje.sem_preco), 'custo estimado hoje'), caixa(usd(d.semana.custo, d.semana.sem_preco), 'custo estimado em 7 dias'),
          caixa(usd(d.total.custo, d.total.sem_preco), 'total · ' + tok(d.total.entrada + d.total.saida + d.total.cache_leitura + d.total.cache_escrita) + ' tokens')),
        d.indexando ? h('div', { class: 'aviso-caixa info', estilo: { marginBottom: '14px' } }, 'Lendo as sessões antigas em segundo plano: os totais crescem até terminar.') : null,
        h('div', { class: 'duas' },
          h('section', { class: 'cartao' }, h('h3', null, 'Atividade recente'),
            h('ul', { class: 'lista' }, d.recentes.map(r => h('li', null,
              h('span', { class: 'chip ' + (r.tipo === 'sessao' ? 'accent' : '') }, r.tipo === 'sessao' ? 'sessão' : 'subagente'),
              h('span', { class: 't', title: r.titulo }, r.titulo), r.modelo ? h('span', { class: 'chip' }, modeloCurto(r.modelo)) : null,
              h('span', { class: 'muted' }, haQuanto(r.mtime)),
              h('a', { class: 'bt leve fino', href: '#/p/' + encodeURIComponent(slug) + '/agentes?a=' + encodeURIComponent(r.rel) }, 'Ver')))),),
          h('div', { estilo: { display: 'grid', gap: '14px', alignContent: 'start' } },
            h('section', { class: 'cartao' }, h('h3', null, 'Sessão gestora'),
              ges ? h('div', null, h('div', { estilo: { fontSize: '17px', fontWeight: 600 } }, d.gestora.nome), h('code', { class: 'muted' }, d.gestora.conversa),
                h('p', { class: 'nota' }, 'Os subagentes dela aparecem como "delegados pelo gestor" em Agentes ao vivo.'))
                : h('div', null, h('p', { class: 'muted' }, 'Nenhuma sessão escolhida.'), h('a', { class: 'bt pri fino', href: '#/p/' + encodeURIComponent(slug) + '/configuracoes' }, 'Escolher a gestora'))),
            h('section', { class: 'cartao' }, h('h3', null, 'Fila do gestor'),
              h('div', { class: 'linha' },
                h('a', { class: 'chip ' + (d.conferir && d.conferir.a_conferir ? 'warn' : 'ok'), href: '#/p/' + encodeURIComponent(slug) + '/conferir' }, ((d.conferir || {}).a_conferir || 0) + ' a conferir'),
                h('a', { class: 'chip ' + ((d.propostas || {}).tarefas_abertas ? 'violet' : ''), href: '#/p/' + encodeURIComponent(slug) + '/analise' }, ((d.propostas || {}).tarefas_abertas || 0) + ' tarefa(s) aprovada(s)'),
                h('a', { class: 'chip', href: '#/p/' + encodeURIComponent(slug) + '/analise' }, ((d.propostas || {}).novas || 0) + ' proposta(s) nova(s)'),
                h('a', { class: 'chip ' + ((d.tarefas || {}).do_dono_abertas ? 'violet' : ''), href: '#/p/' + encodeURIComponent(slug) + '/tarefas' }, ((d.tarefas || {}).do_dono_abertas || 0) + ' tarefa(s) sua(s)' + ((d.tarefas || {}).conferir ? ' · ' + d.tarefas.conferir + ' a conferir' : ''))),
              h('p', { class: 'nota' }, 'Todo subagente que termina espera a conferência do gestor antes de entrar no projeto.')),
            h('section', { class: 'cartao' }, h('h3', null, 'Projeto'),
              h('dl', { class: 'kv' }, h('dt', null, 'Pasta'), h('dd', { class: 'mono' }, d.projeto.caminho),
                h('dt', null, 'Ramo'), h('dd', null, d.git.ramo || '—'), h('dt', null, 'Último commit'), h('dd', null, d.git.commit ? d.git.commit + ' · ' + d.git.assunto : '—'),
                h('dt', null, 'Mapa'), h('dd', null, d.mapa.gerado ? 'atualizado ' + haQuanto(d.mapa.gerado_em) + (d.mapa.defasado ? ' · MAIS VELHO que o último commit' : '') : d.mapa.graphify ? 'Graphify existe; página não gerada' : 'sem Graphify neste projeto')))))
      );
    }
    carregar();
    cada(10000, carregar);
  }

  /* ---------- Agentes ao vivo ---------- */
  function abaAgentes(slug, el, info, params) {
    let todas = false, dados = null, selecionado = null, abertoRel = null, es = null;
    const arvore = h('div', { class: 'arvore caixa-pag' });          // caixa-pag: vira páginas da altura da coluna
    const cab = h('header'), lista = h('div', { class: 'passos' }), rodape = h('footer');
    const painel = h('section', { class: 'cartao painel-passos terminal' }, cab, lista, rodape);          // visual de terminal (Claude Code no cmd)
    const base = '/api/p/' + encodeURIComponent(slug);

    function chipEstado(est) { return h('span', { class: 'chip ' + (est === 'trabalhando' ? 'ok' : est === 'parado' ? 'warn' : '') }, h('span', { class: 'ponto ' + est }), est); }
    function chipConferencia(a) {
      if (!a.conferencia) return null;
      if (a.conferencia === 'a_conferir') return h('span', { class: 'chip warn', title: 'terminou; o gestor ainda não conferiu' }, 'a conferir');
      return h('span', { class: 'chip ' + (a.conferencia === 'aprovado' ? 'ok' : a.conferencia === 'recusado' ? 'perigo' : ''), title: 'resultado da conferência do gestor' }, a.conferencia);
    }
    function chipRegra(a) {
      const r = a.regra;
      if (!r) return null;
      if (!r.regra) return h('div', { class: 'regra muted' }, 'Sem regra clara para esta descrição (tabela em Configurações).');
      const aviso = r.situacao === 'acima' ? ' · modelo MAIOR que o previsto (gasta mais que o necessário)' : r.situacao === 'abaixo' ? ' · modelo MENOR que o previsto: conferir com mais cuidado' : '';
      return h('div', { class: 'regra' }, h('span', { class: 'chip ' + (r.situacao === 'conforme' ? 'accent' : r.situacao === 'sem_regra' ? '' : 'warn'), title: r.regra_nome }, 'Regra: ' + r.regra_nome.split(/[:,]/)[0].trim() + ' → ' + r.modelo_previsto),
        h('span', { class: 'muted' }, ' revisor: ' + r.revisor + aviso));
    }
    function metaNo(n, grande) {
      return h('div', { class: 'meta' }, chipEstado(n.estado),
        n.espera_dono ? h('span', { class: 'chip warn', title: n.aviso_dono || 'o Claude Code está esperando você' }, 'precisa de você') : null,
        n.ferramenta_agora ? h('span', { class: 'chip accent', title: n.ferramenta_agora.alvo || '' }, 'usando ' + n.ferramenta_agora.nome.replace('mcp__', '').slice(0, 22)) : null,
        n.modelo ? h('span', { class: 'chip' }, modeloCurto(n.modelo)) : null,
        h('span', { class: 'muted' }, haQuanto(n.mtime)), n.tokens ? h('span', { class: 'chip', title: 'tokens somados' }, tok(n.tokens) + ' tokens') : null,
        n.custo != null && n.tokens ? h('span', { class: 'chip' }, usd(n.custo)) : null,
        n.ferramentas_total ? h('span', { class: 'chip', title: (n.ferramentas || []).map(f => f[0] + ' ×' + f[1]).join(', ') }, n.ferramentas_total + ' chamadas') : null,
        grande && n.ferramentas ? n.ferramentas.slice(0, 3).map(f => h('span', { class: 'chip', title: 'ferramenta mais usada' }, f[0].replace('mcp__', '').slice(0, 22) + ' ×' + f[1])) : null);
    }
    function desenharArvore() {
      arvore.replaceChildren();
      if (!dados) return;
      if (!dados.sessoes.length) arvore.append(h('div', { class: 'vazio cartao' }, 'Nenhuma sessão ativa nas últimas 24 h.'));
      dados.sessoes.forEach(n => {
        const caixa = h('div', { class: 'no' + (n.gestora ? ' gestora' : '') + (selecionado === n.rel ? ' sel' : ''), onclick: () => abrir(n) },
          h('div', { class: 'topo-no' }, h('span', { class: 'ponto ' + n.estado }), n.gestora ? h('span', { class: 'chip violet' }, 'Gestor') : null,
            h('span', { class: 'nome', title: n.titulo + (n.titulo_original && n.titulo_original !== n.titulo ? ' · título do app: ' + n.titulo_original : '') }, n.titulo),
            n.aberta ? h('span', { class: 'chip ok', title: 'aberta no Claude Code agora (claude agents)' }, 'aberta') : null),
          n.resumo ? h('div', { class: 'resumo-no muted' }, n.resumo) : null,
          metaNo(n, true));
        if (n.subagentes.length) {
          const sub = h('div', { class: 'sub' });
          n.subagentes.slice(0, 25).forEach(a => sub.append(h('div', { class: 'filho' + (selecionado === a.rel ? ' sel' : ''), onclick: ev => { ev.stopPropagation(); abrir(a, n); } },
            h('div', { class: 'topo-no' }, h('span', { class: 'ponto ' + a.estado }), h('span', { class: 'nome', title: a.descricao }, a.descricao),
              a.delegado_pelo_gestor ? h('span', { class: 'chip violet', title: 'delegado pela sessão gestora' }, 'delegado pelo gestor') : null,
              chipConferencia(a)),
            metaNo(a, false), chipRegra(a))));
          if (n.subagentes.length > 25) sub.append(h('div', { class: 'muted' }, '+ ' + (n.subagentes.length - 25) + ' subagentes mais antigos'));
          caixa.append(sub);
        }
        arvore.append(caixa);
      });
    }
    function achar(rel) {
      if (!dados) return null;
      for (const n of dados.sessoes) { if (n.rel === rel) return n; for (const a of n.subagentes) if (a.rel === rel) return a; }
      return null;
    }
    function desenharCab() {
      const n = achar(selecionado);
      cab.replaceChildren();
      rodape.replaceChildren(n && n.estado === 'trabalhando' ? h('span', { class: 'trabalhando' }, '✻ Trabalhando…') : null,
        h('div', { class: 'prompt' }, h('span', null, '>'), h('span', { class: 'cursor' }), h('span', { class: 'dica' }, 'só leitura: responda na própria sessão')));
      if (!n) { cab.append(h('span', { class: 'muted' }, 'Clique num agente para ver o passo a passo ao vivo.')); return; }
      cab.append(h('b', null, n.descricao || n.titulo), chipEstado(n.estado), n.modelo ? h('span', { class: 'chip' }, modeloCurto(n.modelo)) : null,
        n.tipo === 'subagente' ? h('span', { class: 'chip' }, n.tipo_agente || 'subagente') : h('span', { class: 'chip accent' }, 'sessão'),
        h('span', { class: 'muted' }, 'atualizado ' + haQuanto(n.mtime)), h('span', { class: 'chip ok', title: 'conexão ao vivo' }, 'ao vivo'));
    }
    function abrir(n) {
      if (abertoRel === n.rel) return;
      selecionado = abertoRel = n.rel;
      if (es) es.close();
      lista.replaceChildren(h('div', { class: 'vazio' }, 'Carregando o passo a passo…'));
      desenharArvore(); desenharCab();
      const subagente = n.tipo === 'subagente';
      es = new EventSource(base + '/passos?arquivo=' + encodeURIComponent(n.rel));
      es.onmessage = ev => {
        let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
        if (d.tipo === 'inicio') {
          lista.replaceChildren();
          if (d.cortado || d.omitidos) lista.append(h('div', { class: 'passo sistema' }, 'Mostrando só o final da conversa (os passos mais antigos ficam de fora).'));
          if (!d.passos.length) lista.append(h('div', { class: 'passo sistema', id: 'sem-passos' }, 'Nada novo ainda. Os passos aparecem aqui assim que o agente escrever.'));
        } else { const v = document.getElementById('sem-passos'); if (v) v.remove(); }
        const noFim = lista.scrollHeight - lista.scrollTop - lista.clientHeight < 80;
        d.passos.forEach(p => lista.append(linhaPasso(p, subagente)));
        while (lista.children.length > 400) lista.firstChild.remove();
        if (noFim || d.tipo === 'inicio') lista.scrollTop = lista.scrollHeight;
      };
    }
    limpezas.push(() => { if (es) es.close(); });
    /* cada passo vira uma linha como o Claude Code desenha no terminal: "> pedido", "● texto", "● Ferramenta(alvo)", "⎿ resultado" */
    function linhaPasso(p, subagente) {
      const quando = { title: hora(p.t) };
      const linha = (classe, marca, ...corpo) => h('div', { class: 'passo ' + classe, ...quando }, h('span', { class: 'marca' }, marca), h('div', { class: 'corpo' }, ...corpo));
      if (p.tipo === 'texto') return linha('texto', '●', p.texto);
      if (p.tipo === 'usuario') return linha('usuario', '>', subagente ? h('span', { class: 'rotulo' }, 'tarefa recebida') : null, p.texto);
      if (p.tipo === 'ferramenta') return linha('ferramenta', '●', h('b', null, p.nome.replace('mcp__', '')), p.alvo ? '(' + p.alvo + ')' : '');
      if (p.tipo === 'resultado') {
        const linhas = String(p.texto || '').split('\n'), mostrar = linhas.slice(0, 4);           // como o terminal: só o começo
        return linha('resultado' + (p.erro ? ' erro' : ''), '⎿', (p.erro ? 'erro: ' : '') + mostrar.join('\n'),
          linhas.length > 4 ? h('span', { class: 'mais' }, '\n… +' + (linhas.length - 4) + ' linhas') : null);
      }
      return linha('sistema', '·', p.texto);
    }
    const origem = h('span', { class: 'chip' }, 'por leitura dos arquivos');
    function lerLista() {
      const url = base + '/agentes/stream?todas=' + (todas ? 1 : 0);
      const fonte = aoVivo(url, d => {
        dados = d;
        const pelosHooks = d.fonte === 'hooks' || d.hooks_ativos;
        origem.className = 'chip ' + (pelosHooks ? 'ok' : '');
        origem.textContent = pelosHooks ? 'ao vivo pelos hooks' : 'por leitura dos arquivos';
        origem.title = pelosHooks ? 'O Claude Code avisa o Cérebro na hora (ganchos ligados em Configurações).' : 'Sem ganchos: o estado vem da data dos arquivos das conversas (alguns segundos de atraso). Ligue em Configurações › Agentes ao vivo instantâneo.';
        desenharArvore();
        if (!selecionado) {
          const alvo = params.get('a') ? achar(params.get('a')) : (d.sessoes.find(n => n.gestora) || d.sessoes[0]);
          if (alvo) abrir(alvo);
        } else desenharCab();
      });
      return fonte;
    }
    let fonte = lerLista();
    el.append(
      h('div', { class: 'barra' }, h('span', { class: 'muted' }, 'Sessões e subagentes que escreveram nas últimas 24 h, em tempo real. Só leitura.'),
        origem, h('span', { class: 'espaco' }),
        h('label', { class: 'chk muted' }, h('input', { type: 'checkbox', onchange: e => { todas = e.target.checked; fonte.close(); fonte = lerLista(); } }), 'mostrar sessões antigas')),
      h('div', { class: 'ao-vivo encher' }, h('div', { class: 'coluna' }, arvore), painel));
    desenharCab();
  }

  /* ---------- Sessões ---------- */
  function abaSessoes(slug, el) {
    const base = '/api/p/' + encodeURIComponent(slug);
    let todas = [], filtro = '';
    const busca = h('input', { type: 'search', class: 'campo-busca', placeholder: 'Filtrar por título ou ramo', 'aria-label': 'Filtrar sessões', oninput: e => { filtro = e.target.value.toLowerCase(); tabela(); } });
    const corpo = h('div', { class: 'cartao rolagem-x' }), aviso = h('div');
    // duas partes em abas internas: a lista (com páginas) e a corrente da gestora
    const pLista = h('div', { class: 'painel-aba' }, h('div', { class: 'barra' }, busca, h('span', { class: 'muted', id: 'cont-sessoes' })), aviso, corpo);
    if (window.CerebroUI.sessoesTopo) {
      const pCorrente = h('div', { class: 'painel-aba' }, window.CerebroUI.sessoesTopo(slug));
      el.append(abasInternas([['lista', 'Sessões', pLista], ['corrente', 'Corrente da gestora', pCorrente]], 'sessoes').barra, pLista, pCorrente);
    } else el.append(pLista);
    function tabela() {
      const itens = todas.filter(s => !filtro || (s.titulo + ' ' + s.primeira + ' ' + s.ramo).toLowerCase().includes(filtro));
      document.getElementById('cont-sessoes').textContent = itens.length + ' de ' + todas.length + ' sessões';
      corpo.replaceChildren(h('table', { class: 'tabela' },
        h('thead', null, h('tr', null, ['Sessão', 'Última atividade', 'Mensagens', 'Tokens', 'Custo est.', 'Modelo', 'Subag.', 'Mais usadas', ''].map((t, i) => h('th', { class: i >= 2 && i <= 4 ? 'n' : '' }, t)))),
        h('tbody', null, itens.map(s => h('tr', null,
          h('td', { class: 'tit' }, s.gestora ? h('span', { class: 'chip violet' }, 'Gestor ') : null, ' ', h('span', { title: (s.primeira || s.id) + (s.titulo_original && s.titulo_original !== s.titulo ? ' · título do app: ' + s.titulo_original : '') }, s.titulo || s.primeira || '(sem título) ' + s.id.slice(0, 8)),
            s.resumo && s.resumo !== s.titulo ? h('div', { class: 'muted', estilo: { fontSize: '12px' } }, s.resumo) : null,
            h('div', { class: 'muted mono', estilo: { fontSize: '11px' } }, s.id + ' · ' + tamanho(s.tam) + (s.ramo ? ' · ' + s.ramo : '')),
            window.CerebroUI.sessaoBastao ? window.CerebroUI.sessaoBastao(slug, s) : null),
          h('td', null, haQuanto(s.mtime), h('div', { class: 'muted', estilo: { fontSize: '11.5px' } }, dataCurta(s.fim))),
          h('td', { class: 'n' }, s.indexado ? num(s.mensagens) : '…'), h('td', { class: 'n' }, s.indexado ? tok(s.tokens) : '…'),
          h('td', { class: 'n' }, s.indexado ? usd(s.custo) : '…'), h('td', null, modeloCurto(s.modelo)), h('td', { class: 'n' }, num(s.subagentes)),
          h('td', null, s.ferramentas.slice(0, 3).map(f => h('span', { class: 'chip', estilo: { marginRight: '4px' } }, f[0].replace('mcp__', '').slice(0, 18) + ' ×' + f[1]))),
          h('td', null, h('div', { class: 'barra', estilo: { margin: 0, flexWrap: 'nowrap' } },
            h('a', { class: 'bt leve fino', href: '#/p/' + encodeURIComponent(slug) + '/agentes?a=' + encodeURIComponent(s.rel) }, 'Passo a passo'),
            s.gestora ? null : h('button', { type: 'button', class: 'bt leve fino', onclick: ev => escolherGestora(s, ev.target) }, 'Definir gestora'))))))));
    }
    async function escolherGestora(s, botao) {
      botao.disabled = true;
      try { await post(base + '/gestora', { conversa: s.id }); carregar(); } catch (e) { botao.textContent = e.message; }
    }
    async function carregar() {
      let d;
      try { d = await api(base + '/sessoes'); } catch (e) { corpo.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      todas = d.sessoes;
      aviso.replaceChildren(d.indexando ? h('div', { class: 'aviso-caixa info', estilo: { marginBottom: '12px' } }, 'Lendo as sessões (' + d.progresso.feito + ' de ' + d.progresso.total + ' arquivos). Os números das mais antigas aparecem aos poucos.') : '');
      tabela();
    }
    carregar();
    cada(4000, () => { if (todas.some(s => !s.indexado) || document.querySelector('.aviso-caixa.info')) carregar(); });
  }

  /* ---------- Memória e decisões ---------- */
  function abaMemoria(slug, el) {
    const base = '/api/p/' + encodeURIComponent(slug);
    let dados = null, filtro = 'tudo', termo = '', selecionado = null, tempo = null;
    const ctx = h('div'), chips = h('div', { class: 'filtros-mem' }), lista = h('div', { class: 'itens-mem caixa-pag' }), leitor = h('div', { class: 'leitor' }, 'Escolha um item à esquerda.');
    const busca = h('input', { type: 'search', class: 'campo-busca', placeholder: 'Buscar em toda a memória (mín. 2 letras)', 'aria-label': 'Buscar na memória',
      oninput: e => { termo = e.target.value.trim(); clearTimeout(tempo); tempo = setTimeout(desenhar, 250); } });
    const decBox = h('section', { class: 'cartao', estilo: { marginBottom: '14px' } });
    const extras = h('div');                       // memoria.js: criar, compactar, avisos (e Editar/Arquivar no leitor)
    // uma parte por vez (abas internas): os itens ocupam a altura toda; o texto aberto rola dentro do leitor
    const pItens = h('div', { class: 'painel-aba encher pilha' }, h('div', { class: 'barra' }, busca, chips),
      h('div', { class: 'memoria encher' }, h('div', { class: 'coluna' }, lista), h('section', { class: 'cartao leitor-caixa' }, leitor)));
    const pDec = h('div', { class: 'painel-aba' }, decBox), pCuidar = h('div', { class: 'painel-aba' }, extras), pCtx = h('div', { class: 'painel-aba' }, ctx);
    const abasMem = abasInternas([['itens', 'Itens de memória', pItens], ['decisoes', 'Decisões e regras', pDec], ['cuidar', 'Cuidar da memória', pCuidar], ['contexto', 'Contexto fixo', pCtx]], 'memoria');
    el.append(abasMem.barra, pItens, pDec, pCuidar, pCtx);
    const ctxMem = {
      abrir: (id, titulo) => abrir(id, titulo),
      recarregar: nome => api(base + '/memoria').then(d => {
        dados = d; desenharCtx(); desenhar(); carregarDecisoes();
        const i = nome && dados.itens.find(x => x.id === 'mem/' + nome);
        if (i) abrir(i.id, i.titulo); else { selecionado = null; leitor.textContent = 'Escolha um item à esquerda.'; }
      }),
    };
    if (window.CerebroUI.memoriaExtras) window.CerebroUI.memoriaExtras(slug, extras, ctxMem);
    async function carregarDecisoes() {
      let d;
      try { d = await api(base + '/decisoes'); } catch (e) { decBox.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const tipo = h('select', { 'aria-label': 'Tipo' }, [['decisao', 'Decisão'], ['regra', 'Regra'], ['ideia', 'Ideia']].map(([v, n]) => h('option', { value: v }, n)));
      const origem = h('select', { 'aria-label': 'Origem' }, [['dono', 'Dono'], ['gestor', 'Gestor']].map(([v, n]) => h('option', { value: v }, n)));
      const texto = h('input', { type: 'text', maxlength: 2000, placeholder: 'Escreva a decisão, regra ou ideia (ex.: botões com 28 px)', 'aria-label': 'Texto', estilo: { flex: 1, minWidth: '260px' } });
      const msg = h('span', { class: 'muted' });
      const registrar = async () => {
        try { await post(base + '/decisoes', { texto: texto.value, tipo: tipo.value, origem: origem.value }); texto.value = ''; carregarDecisoes(); }
        catch (e) { msg.className = 'msg-erro'; msg.textContent = e.message; }
      };
      texto.addEventListener('keydown', ev => { if (ev.key === 'Enter') registrar(); });
      const linhas = [
        ...d.registradas.map(x => ({ t: x.em, tipo: x.tipo, origem: x.origem, texto: x.texto, did: x.id, estado: x.estado, mudou_em: x.mudou_em })),
        ...d.dos_arquivos.map(x => ({ t: x.modificado, tipo: x.regra ? 'regra' : 'decisao', origem: 'memória', texto: x.titulo + (x.descricao ? ' — ' + x.descricao : ''), id: x.id, titulo: x.titulo })),
      ].sort((a, b) => (b.t || 0) - (a.t || 0));
      const COR = { decisao: 'violet', regra: 'warn', ideia: 'accent' };
      const NOME = { decisao: 'DECISÃO', regra: 'REGRA', ideia: 'IDEIA' };
      decBox.replaceChildren(h('h3', null, 'Decisões e regras (linha do tempo)'),
        h('div', { class: 'linha-cfg' }, tipo, origem, texto, h('button', { type: 'button', class: 'bt pri fino', onclick: registrar }, 'Registrar'), msg),
        h('p', { class: 'nota' }, 'As registradas aqui ficam em decisoes.jsonl do Cérebro; as de memória vêm dos arquivos REGRA/DECISÃO do Claude Code (clique para ler). O gestor registra pela linha de comando.'),
        h('ul', { class: 'lista linha-tempo' }, linhas.slice(0, 40).map(x => h('li', { class: x.id ? 'clicavel' : '', onclick: x.id ? () => abrir(x.id, x.titulo) : null },
          h('span', { class: 'chip ' + (COR[x.tipo] || '') }, NOME[x.tipo] || x.tipo), h('span', { class: 'chip' }, x.origem),
          h('span', { class: 't', title: x.texto, estilo: x.estado && x.estado !== 'ativa' ? { opacity: 0.55, textDecoration: 'line-through' } : null }, x.texto), h('span', { class: 'muted' }, x.t ? dataCurta(x.t) : ''),
          x.did && window.CerebroUI.decisaoAcoes ? window.CerebroUI.decisaoAcoes(slug, x, carregarDecisoes) : null))),
        linhas.length > 40 ? h('p', { class: 'nota' }, '+ ' + (linhas.length - 40) + ' mais antigas (use a busca ou os filtros abaixo).') : null,
        !linhas.length ? h('div', { class: 'vazio' }, 'Nada registrado ainda.') : null);
    }
    carregarDecisoes();
    const FILTROS = [['tudo', 'Tudo'], ['regra', 'Regras'], ['decisao', 'Decisões'], ['plano', 'Planos'], ['user', 'user'], ['feedback', 'feedback'], ['project', 'project'], ['reference', 'reference'], ['doc', 'Documentos do projeto']];
    function passa(i) {
      if (filtro === 'tudo') return true;
      if (['regra', 'decisao', 'plano'].includes(filtro)) return i[filtro];
      if (filtro === 'doc') return i.origem !== 'memoria';
      return i.tipo === filtro;
    }
    function desenharCtx() {
      const c = dados.contexto_fixo;
      const maximo = Math.max(1, ...c.arquivos.map(a => a.tokens));
      ctx.replaceChildren(h('section', { class: 'cartao', estilo: { marginBottom: '14px' } }, h('h3', null, 'Contexto fixo: o que toda conversa paga antes de começar'),
        h('div', { estilo: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } },
          h('div', null, h('div', { estilo: { fontSize: '30px', fontFamily: 'var(--font-display)', fontWeight: 700 } }, '≈ ' + num(c.total_tokens) + ' tokens'),
            h('small', { class: 'muted' }, num(c.total_chars) + ' caracteres ÷ 4 (estimativa)' + (c.global_tokens ? ' · + ≈ ' + num(c.global_tokens) + ' do CLAUDE.md global' : ''))),
          h('div', { estilo: { flex: 1, minWidth: '260px' } }, c.arquivos.map(a => h('div', null, h('div', { class: 'barra', estilo: { margin: 0, justifyContent: 'space-between' } }, h('span', null, a.nome), h('span', { class: 'muted' }, '≈ ' + num(a.tokens) + ' tokens')),
            h('div', { class: 'barra-ctx' }, h('i', { estilo: { width: Math.max(2, 100 * a.tokens / maximo) + '%' } })))))),
        dados.avisos.length ? h('div', { class: 'aviso-caixa', estilo: { marginTop: '10px' } }, dados.avisos.join(' ')) : null));
    }
    function itemEl(i, trecho) {
      return h('div', { class: 'item-mem' + (selecionado === i.id ? ' sel' : ''), onclick: () => abrir(i.id, i.titulo) },
        h('b', null, i.titulo), trecho ? h('div', { class: 'desc' }, trecho) : h('div', { class: 'desc' }, i.descricao || ''),
        h('div', { class: 'linha' }, i.regra ? h('span', { class: 'chip warn' }, 'REGRA') : null, i.decisao ? h('span', { class: 'chip violet' }, 'DECISÃO') : null,
          i.plano ? h('span', { class: 'chip accent' }, 'PLANO') : null, i.tipo ? h('span', { class: 'chip' }, i.tipo) : null,
          h('span', { class: 'chip' }, i.origem === 'memoria' ? 'memória' : i.origem), h('span', { class: 'muted', estilo: { fontSize: '11.5px' } }, i.modificado ? dataCurta(i.modificado) : ''), i.tokens ? h('span', { class: 'muted', estilo: { fontSize: '11.5px' } }, '≈ ' + num(i.tokens) + ' tokens') : null));
    }
    async function desenhar() {
      if (!dados) return;
      chips.replaceChildren(...FILTROS.map(([id, nome]) => h('button', { type: 'button', class: 'bt fino ' + (filtro === id ? 'pri' : 'leve'), onclick: () => { filtro = id; desenhar(); } }, nome)));
      if (termo.length >= 2) {
        try {
          const r = await api(base + '/memoria?q=' + encodeURIComponent(termo));
          lista.replaceChildren(...(r.busca.length ? r.busca.map(b => itemEl(dados.itens.find(i => i.id === b.id) || { id: b.id, titulo: b.titulo, origem: b.origem }, '…' + b.trecho + '…  (' + b.ocorrencias + 'x)')) : [h('div', { class: 'vazio' }, 'Nada encontrado.')]));
        } catch (e) { lista.replaceChildren(h('div', { class: 'vazio' }, e.message)); }
        return;
      }
      const itens = dados.itens.filter(passa);
      lista.replaceChildren(...(itens.length ? itens.map(i => itemEl(i)) : [h('div', { class: 'vazio' }, dados.existe ? 'Nada neste filtro.' : 'Este projeto ainda não tem pasta de memória do Claude Code.')]));
    }
    async function abrir(id, titulo) {
      selecionado = id;
      if (abasMem.atual() !== 'itens') abasMem.mostrar('itens');     // clicou numa decisão: mostra o texto na parte dos itens
      desenhar();
      leitor.textContent = 'Carregando…';
      try {
        const r = await api(base + '/memoria/arquivo?id=' + encodeURIComponent(id));
        leitor.replaceChildren(h('b', { estilo: { display: 'block', marginBottom: '8px', fontFamily: 'var(--font-display)', fontSize: '15px' } }, titulo));
        r.texto.split('\n').forEach(l => leitor.append(/\b(REGRA|DECIS[ÃA]O|REQUISITO|ARQUITETURA|PRIORIDADE)\b/.test(l) ? h('span', { class: 'dest' }, l + '\n') : document.createTextNode(l + '\n')));
        if (window.CerebroUI.memoriaAoAbrir) window.CerebroUI.memoriaAoAbrir(slug, id, leitor, ctxMem);
        if (termo.length >= 2) {
          const alvo = [...leitor.childNodes].find(n => n.textContent.toLowerCase().includes(termo.toLowerCase()));
          if (alvo && alvo.scrollIntoView) alvo.scrollIntoView({ block: 'center' });
        }
      } catch (e) { leitor.textContent = e.message; }
    }
    api(base + '/memoria').then(d => { dados = d; desenharCtx(); desenhar(); }).catch(e => lista.replaceChildren(h('div', { class: 'vazio' }, e.message)));
  }

  /* ---------- Custos ---------- */
  function abaCustos(slug, el) {
    const base = '/api/p/' + encodeURIComponent(slug);
    el.append(h('div', { class: 'vazio' }, 'Somando os tokens…'));
    function grafico(dias) {
      const usaCusto = dias.some(([, v]) => v.custo > 0 && !v.sem_preco);
      const valor = v => (usaCusto ? v.custo : v.entrada + v.saida + v.cache_leitura + v.cache_escrita);
      const maximo = Math.max(1e-9, ...dias.map(([, v]) => valor(v)));
      const W = 1200, H = 210, baseY = 178, larg = Math.max(8, Math.min(44, (W - 60) / Math.max(dias.length, 1) - 6));
      const svg = s('svg', { class: 'grafico', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Gasto por dia' },
        s('defs', null, s('linearGradient', { id: 'gradbarra', x1: 0, y1: 0, x2: 0, y2: 1 }, s('stop', { offset: '0%', 'stop-color': '#6ee2ff' }), s('stop', { offset: '100%', 'stop-color': '#0057d6' }))),
        s('line', { x1: 30, x2: W - 6, y1: baseY, y2: baseY, stroke: 'var(--border-2)' }));
      dias.forEach(([dia, v], i) => {
        const x = 34 + i * ((W - 44) / Math.max(dias.length, 1)), alt = Math.max(2, 150 * valor(v) / maximo);
        svg.append(s('rect', { class: 'barra-svg', x, y: baseY - alt, width: larg, height: alt, rx: 3 },
          s('title', null, dia.split('-').reverse().join('/') + ': ' + (usaCusto ? usd(v.custo, v.sem_preco) : tok(valor(v)) + ' tokens') + ' · ' + tok(v.entrada + v.saida + v.cache_leitura + v.cache_escrita) + ' tokens')));
        if (i % Math.ceil(dias.length / 10) === 0) svg.append(s('text', { x: x + larg / 2, y: baseY + 14, 'text-anchor': 'middle' }, dia.slice(8) + '/' + dia.slice(5, 7)));
      });
      svg.append(s('text', { x: 30, y: 14 }, usaCusto ? 'pico: ' + usd(maximo) : 'pico: ' + tok(maximo) + ' tokens'));
      return svg;
    }
    function tabelaPor(titulo, itens, rotulo) {
      return h('section', { class: 'cartao rolagem-x' }, h('h3', null, titulo), h('table', { class: 'tabela' },
        h('thead', null, h('tr', null, [rotulo, 'Entrada', 'Saída', 'Cache leitura', 'Cache escrita', 'Mensagens', 'Custo est.'].map((t, i) => h('th', { class: i ? 'n' : '' }, t)))),
        h('tbody', null, itens.map(([nome, v, extra]) => h('tr', null, h('td', { class: 'tit', title: nome }, extra || null, nome), h('td', { class: 'n' }, tok(v.entrada)), h('td', { class: 'n' }, tok(v.saida)),
          h('td', { class: 'n' }, tok(v.cache_leitura)), h('td', { class: 'n' }, tok(v.cache_escrita)), h('td', { class: 'n' }, num(v.mensagens)), h('td', { class: 'n' }, usd(v.custo, v.sem_preco)))))));
    }
    async function carregar() {
      let d;
      try { d = await api(base + '/custos'); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const t = d.total, totalTok = t.entrada + t.saida + t.cache_leitura + t.cache_escrita;
      const hoje = d.por_dia.length ? d.por_dia[d.por_dia.length - 1] : null;
      trocar(el,
        d.indexando ? h('div', { class: 'aviso-caixa info', estilo: { marginBottom: '14px' } }, 'Lendo as sessões: ' + d.progresso.feito + ' de ' + d.progresso.total + ' arquivos.', h('div', { class: 'prog', estilo: { marginTop: '6px' } }, h('i', { estilo: { width: (d.progresso.total ? 100 * d.progresso.feito / d.progresso.total : 0) + '%' } }))) : null,
        d.modelos_sem_preco.length ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '14px' } }, 'Preço a conferir para: ' + d.modelos_sem_preco.join(', ') + '. Só os tokens são somados (preencha em Configurações).') : null,
        h('div', { class: 'grade estreita', estilo: { marginBottom: '14px' } },
          h('div', { class: 'num' }, h('b', null, usd(t.custo, t.sem_preco)), h('small', null, 'custo estimado total')), h('div', { class: 'num' }, h('b', null, tok(totalTok)), h('small', null, 'tokens no total')),
          h('div', { class: 'num' }, h('b', null, tok(t.entrada + t.saida)), h('small', null, 'entrada + saída')), h('div', { class: 'num' }, h('b', null, tok(t.cache_leitura)), h('small', null, 'lidos do cache')),
          h('div', { class: 'num' }, h('b', null, tok(t.cache_escrita)), h('small', null, 'escritos no cache')), h('div', { class: 'num' }, h('b', null, hoje ? usd(hoje[1].custo, hoje[1].sem_preco) : '—'), h('small', null, 'último dia com uso'))),
        h('section', { class: 'cartao', estilo: { marginBottom: '14px' } }, h('h3', null, 'Por dia (últimos 30 dias com uso)'), d.por_dia.length ? grafico(d.por_dia) : h('div', { class: 'vazio' }, 'Sem uso registrado.')),
        window.CerebroUI.cartaoOrcamento ? window.CerebroUI.cartaoOrcamento(slug) : null,
        h('div', { estilo: { display: 'grid', gap: '14px' } },
          tabelaPor('Por modelo', Object.entries(d.por_modelo).sort((a, b) => b[1].custo - a[1].custo).map(([m, v]) => [modeloCurto(m), v]), 'Modelo'),
          tabelaPor('Por sessão (as 30 maiores)', d.por_sessao.map(x => [x.titulo, x, x.subagentes ? h('span', { class: 'chip', title: 'inclui à parte ' + usd(x.subagentes.custo) + ' dos subagentes' }, '+' + num(x.subagentes.mensagens) + ' msgs de subagentes ') : null]), 'Sessão'),
          tabelaPor('Por subagente (os 30 maiores)', d.por_subagente.map(x => [x.titulo, x, h('span', { class: 'chip' }, modeloCurto(x.modelo) || 'subag.')]), 'Subagente')),
        h('p', { class: 'nota' }, 'Custo = tokens × tabela de preços (Configurações), preço de lista: é uma ESTIMATIVA e pode diferir da fatura. * = parte das mensagens é de um modelo sem preço. ' + d.fonte_precos));
      if (d.limites.disponivel) desenharAneis(d.limites);
    }
    carregar();
    cada(3000, () => { if (document.querySelector('.aviso-caixa.info')) carregar(); });
    cada(30000, carregar);
  }

  /* ---------- Mapa ---------- */
  function abaMapa(slug, el, info) {
    const base = '/api/p/' + encodeURIComponent(slug);
    async function desenhar() {
      let m;
      try { m = await api(base + '/mapa/estado'); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      if (!m.graphify) {
        el.replaceChildren(h('section', { class: 'cartao' }, h('h3', null, 'Mapa ainda não gerado'),
          h('p', null, 'Este projeto não tem a pasta ', h('code', null, 'graphify-out'), ' (o mapa do código feito pelo Graphify). Sem ela não há o que desenhar.'),
          h('p', { class: 'muted' }, 'O Cérebro não roda o Graphify em outros projetos por conta própria: isso entra depois, na instalação adaptativa, com um plano mostrado e a sua aprovação.')));
        return;
      }
      const botao = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
        botao.disabled = true; botao.textContent = 'Gerando…';
        try { const r = await post(base + '/mapa/gerar'); botao.textContent = r.ok ? 'Pronto' : 'Falhou'; } catch (e) { botao.textContent = e.message; }
        desenhar();
      } }, m.gerado ? 'Atualizar a página do mapa agora' : 'Gerar a página do mapa');
      if (!m.gerado) {
        el.replaceChildren(h('section', { class: 'cartao' }, h('h3', null, 'O Graphify tem o mapa; falta montar a página'),
          h('p', null, 'A página lê o graphify-out do projeto (só leitura) e guarda o resultado em ', h('code', null, '.cerebro\\projetos\\' + slug + '\\mapa'), '. Nada é escrito dentro do projeto.'), botao));
        return;
      }
      const v = m.vigia || {};
      // o mapa ocupa a área toda; o status é uma linha fina em cima e "Explicar com IA" abre numa gaveta
      botao.className = 'bt leve fino';
      botao.replaceChildren(icone('atualizar'), m.gerado ? 'Atualizar' : 'Gerar');
      botao.title = 'Refaz agora a página do mapa a partir do graph.json do Graphify';
      const status = 'Mapa atualizado ' + haQuanto(m.gerado_em) + ' (' + dataCurta(m.gerado_em) + ') · Graphify de ' + dataCurta(m.graph_em) + (v.gerando ? ' · gerando agora…' : '')
        + (m.automatico ? ' · o Cérebro vigia o graph.json a cada ' + (m.intervalo_s || 30) + ' s e refaz a página sozinho enquanto o servidor está aberto.' : ' · atualização automática desligada (Configurações).');
      const explicar = window.CerebroExplicar ? h('button', { type: 'button', class: 'bt leve fino', title: 'Explicar pontos do mapa com IA (opcional, gasta tokens só quando você clica)',
        onclick: () => { const c = window.CerebroExplicar.cartao(slug, desenhar); c.open = true; gaveta('Explicar pontos do mapa com IA', c, { classe: 'gaveta-explicar' }); } }, icone('ia'), 'Explicar com IA') : null;
      el.replaceChildren(
        m.defasado ? h('div', { class: 'aviso-caixa curto', title: 'Os ganchos do git não o refizeram: o vigia só atualiza a página quando o graph.json muda.' }, 'O mapa do Graphify (' + dataCurta(m.graph_em) + ') está mais velho que o último commit do projeto (' + dataCurta(m.commit_em) + ').') : null,
        v.ultimo_erro ? h('div', { class: 'aviso-caixa curto', title: v.ultimo_erro }, 'O gerador da página falhou (' + v.falhas + ' vez(es)); tenta de novo sozinho. Último erro: ' + v.ultimo_erro) : null,
        h('div', { class: 'mapa-status' }, h('span', { class: 'muted texto-status', title: status }, status),
          botao, explicar, h('a', { class: 'bt leve fino', href: '/mapa/' + encodeURIComponent(slug) + '/', target: '_blank', rel: 'noopener', title: 'Abre o mapa sozinho numa aba nova' }, icone('cheia'), 'Tela cheia')),
        h('iframe', { class: 'mapa-quadro encher', src: '/mapa/' + encodeURIComponent(slug) + '/', title: 'Mapa do projeto' }));
    }
    desenhar();
  }

  /* ---------- Configurações ---------- */
  function abaConfig(slug, el) { telaConfig(slug, el); }
  function telaConfig(slug, destino) {
    const el = destino || h('div');
    if (!destino) {
      el.className = 'conteudo';
      raiz.replaceChildren(h('div', { class: 'titulo-pagina' }, h('h2', null, 'Configurações'), h('span', { class: 'muted' }, 'vale para todos os projetos')), el);
      encaixar(el, { chave: 'config', menu: true });            // menu de seções à esquerda, uma por vez
    }
    el.append(h('div', { class: 'vazio' }, 'Carregando…'));
    const msg = h('span');
    const dizer = (t, ok = true) => { msg.className = ok ? 'msg-ok' : 'msg-erro'; msg.textContent = t; };
    async function montar() {
      let c, sessoes = [];
      try {
        c = await api('/api/config');
        if (slug) sessoes = (await api('/api/p/' + encodeURIComponent(slug) + '/sessoes')).sessoes;
      } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      aplicarTema(c.tema !== 'claro' ? true : false);
      const partes = [];
      if (slug) {
        const ges = (c.gestoras || {})[slug] || {};
        const sel = h('select', { 'aria-label': 'Sessão gestora' }, h('option', { value: '' }, '(nenhuma)'),
          sessoes.slice(0, 80).map(x => h('option', { value: x.id, selected: x.id === ges.conversa }, (x.titulo || x.primeira || x.id.slice(0, 8)).slice(0, 70) + ' · ' + dataCurta(x.mtime))));
        const apelido = h('input', { type: 'text', value: ges.nome || '', maxlength: 80, placeholder: 'Apelido da gestora (ex.: Gestora principal)', 'aria-label': 'Apelido da gestora', estilo: { flex: 1, minWidth: '260px' } });
        partes.push(h('section', { class: 'cartao secao' }, h('h3', null, 'Sessão gestora deste projeto'),
          h('div', { class: 'linha-cfg' }, sel, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
            try { await post('/api/p/' + encodeURIComponent(slug) + '/gestora', { conversa: sel.value, nome: apelido.value.trim() }); dizer('Gestora salva.'); } catch (e) { dizer(e.message, false); }
          } }, 'Salvar')),
          h('div', { class: 'linha-cfg' }, h('label', null, 'Apelido mostrado no lugar do título da conversa: '), apelido),
          h('p', { class: 'nota' }, 'A gestora é a conversa principal do projeto (você + o melhor modelo). Trocar quando ela ficar longa é só mudar a escolha: memória, decisões e mapa ficam no Cérebro.')));
      }
      // projetos visíveis
      const ocultos = new Set(c.ocultos || []);
      const campoPasta = h('input', { type: 'text', placeholder: 'Pasta de um projeto, por exemplo C:\\Projetos\\MeuProjeto', 'aria-label': 'Pasta do projeto', estilo: { flex: 1, minWidth: '280px' } });
      partes.push(h('section', { class: 'cartao secao' }, h('h3', null, 'Projetos no painel'),
        c.projetos.map(p => h('div', { class: 'linha-cfg' }, h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: !ocultos.has(p.slug), onchange: async e => {
          if (e.target.checked) ocultos.delete(p.slug); else ocultos.add(p.slug);
          try { await post('/api/config', { ocultos: [...ocultos] }); dizer('Salvo.'); } catch (er) { dizer(er.message, false); }
        } }), p.nome), h('span', { class: 'mono muted' }, p.caminho), p.extra ? h('span', { class: 'chip' }, 'adicionado') : null)),
        h('div', { class: 'linha-cfg' }, campoPasta, h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
          try { await post('/api/projetos/extra', { caminho: campoPasta.value.trim() }); dizer('Projeto adicionado.'); montar(); } catch (e) { dizer(e.message, false); }
        } }, 'Adicionar projeto')),
        h('p', { class: 'nota' }, 'Os projetos vêm de .claude/projects. Worktrees e pastas temporárias nunca entram; para esconder um projeto para sempre, use "nunca_entrar" no config.json.')));
      // preços
      const campos = ['entrada', 'saida', 'cache_leitura', 'cache_escrita_5m', 'cache_escrita_1h'];
      const linhas = Object.entries(c.precos).map(([modelo, v]) => ({ modelo, v }));
      const corpoPrecos = h('tbody');
      const desenharPrecos = () => {
        corpoPrecos.replaceChildren(...linhas.map(l => h('tr', null, h('td', null, h('input', { type: 'text', value: l.modelo, class: 'modelo-in', 'aria-label': 'Modelo', oninput: e => { l.modelo = e.target.value.trim(); } })),
          campos.map(k => h('td', null, h('input', { type: 'number', step: '0.01', min: '0', class: 'preco-in', value: l.v[k], 'aria-label': k, oninput: e => { l.v[k] = parseFloat(e.target.value); } }), (l.v.derivados || []).includes(k) ? h('span', { class: 'muted', title: 'valor derivado da regra geral do cache: a conferir' }, '*') : null)),
          h('td', null, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { linhas.splice(linhas.indexOf(l), 1); desenharPrecos(); } }, 'Remover')))));
      };
      desenharPrecos();
      partes.push(h('section', { class: 'cartao secao rolagem-x' }, h('h3', null, 'Tabela de preços (US$ por milhão de tokens)'),
        h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Modelo (prefixo)', 'Entrada', 'Saída', 'Cache leitura', 'Cache escrita 5 min', 'Cache escrita 1 h', ''].map(t => h('th', null, t)))), corpoPrecos),
        h('div', { class: 'linha-cfg' }, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { linhas.push({ modelo: 'claude-novo-modelo', v: { entrada: 0, saida: 0, cache_leitura: 0, cache_escrita_5m: 0, cache_escrita_1h: 0, derivados: [] } }); desenharPrecos(); } }, 'Adicionar modelo'),
          h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
            const precos = {};
            for (const l of linhas) precos[l.modelo] = Object.fromEntries(campos.map(k => [k, l.v[k]]).concat([['derivados', l.v.derivados || []]]));
            try { await post('/api/config', { precos }); dizer('Preços salvos. Os custos já usam a tabela nova.'); } catch (e) { dizer(e.message, false); }
          } }, 'Salvar preços')),
        h('p', { class: 'nota' }, c.fonte_precos + ' O modelo é casado pelo maior prefixo (claude-opus-5-5 vale para claude-opus-5-5-2026…). Modelo sem linha aqui fica "a conferir" e só conta tokens.')));
      // rotinas
      const au = h('input', { type: 'number', min: 1, max: 365, value: c.rotinas.autoevolucao_dias, 'aria-label': 'Dias entre autoanálises' });
      const vi = h('input', { type: 'number', min: 1, max: 365, value: c.rotinas.vigia_novidades_dias, 'aria-label': 'Dias entre buscas de novidades' });
      const rd = h('input', { type: 'number', min: 1, max: 90, value: c.revisao_dias, 'aria-label': 'Dias da fila a conferir' });
      const mv = h('input', { type: 'number', min: 10, max: 3600, value: c.rotinas.mapa_vigia_segundos, 'aria-label': 'Segundos entre conferências do mapa' });
      const caixa = (chave, rotulo) => { const i = h('input', { type: 'checkbox', checked: !!c.rotinas[chave] }); i.dataset.chave = chave; return h('label', { class: 'chk' }, i, rotulo); };
      const cA = caixa('analise_automatica', 'rodar a análise sozinha'), cN = caixa('novidades_automatica', 'buscar novidades sozinho (consulta a internet)'), cM = caixa('mapa_automatico', 'refazer a página do mapa sozinha');
      partes.push(h('section', { class: 'cartao secao' }, h('h3', null, 'Rotinas (rodam só com o servidor aberto)'),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Autoevolução (análise sem IA que propõe melhorias) a cada ', au, ' dias'), cA),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Vigia de novidades (ferramentas e técnicas novas) a cada ', vi, ' dias'), cN),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Conferir o graph.json do Graphify a cada ', mv, ' segundos'), cM),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Fila "a conferir": subagentes que terminaram nos últimos ', rd, ' dias')),
        h('div', { class: 'linha-cfg' }, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          try {
            await post('/api/config', { revisao_dias: parseInt(rd.value, 10), rotinas: { autoevolucao_dias: parseInt(au.value, 10), vigia_novidades_dias: parseInt(vi.value, 10),
              mapa_vigia_segundos: parseInt(mv.value, 10), analise_automatica: cA.querySelector('input').checked, novidades_automatica: cN.querySelector('input').checked, mapa_automatico: cM.querySelector('input').checked } });
            dizer('Rotinas salvas.');
          } catch (e) { dizer(e.message, false); }
        } }, 'Salvar')),
        h('p', { class: 'nota' }, 'Estas rotinas só rodam enquanto o servidor está aberto. Para rodarem sozinhas no Windows, mesmo com o painel fechado, use "Rotinas no Windows" mais abaixo. A análise não usa IA e só PROPÕE; nada é aplicado sem a sua aprovação.')));
      window.CerebroUI.secoesConfig.forEach(fn => { try { const x = fn({ slug, c, dizer, montar }); if (x) partes.push(x); } catch (e) { /* seção opcional */ } });
      // tema, porta, servidor
      const porta = h('input', { type: 'number', min: 1024, max: 65535, value: c.porta, 'aria-label': 'Porta' });
      const minutos = h('input', { type: 'number', min: 5, max: 1440, value: c.sem_pagina_minutos, 'aria-label': 'Minutos sem página' });
      let confirmando = false;
      const bEncerrar = h('button', { type: 'button', class: 'bt perigo fino', onclick: async () => {
        if (!confirmando) { confirmando = true; bEncerrar.textContent = 'Clique de novo para encerrar'; setTimeout(() => { confirmando = false; bEncerrar.textContent = 'Encerrar o servidor'; }, 4000); return; }
        try { await post('/api/encerrar'); } catch (e) { /* o servidor fecha a conexão */ }
        document.body.append(h('div', { class: 'cobertura' }, h('div', { class: 'cartao' }, h('h2', null, 'Cérebro encerrado'), h('p', { class: 'muted' }, 'Para abrir de novo use abrir_cerebro.py.'))));
      } }, 'Encerrar o servidor');
      partes.push(h('section', { class: 'cartao secao' }, h('h3', null, 'Aparência e servidor'),
        h('div', { class: 'linha-cfg' }, h('span', null, 'Tema:'), ['escuro', 'claro'].map(t => h('button', { type: 'button', class: 'bt fino ' + (c.tema === t ? 'pri' : 'leve'), onclick: async () => { aplicarTema(t === 'escuro'); try { await post('/api/config', { tema: t }); montar(); } catch (e) { dizer(e.message, false); } } }, t))),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Porta ', porta, ' (vale na próxima vez que o servidor subir; em uso agora: ' + c.porta_em_uso + ')'),
          h('label', null, 'Encerrar sozinho após ', minutos, ' min sem página aberta'),
          h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
            try { await post('/api/config', { porta: parseInt(porta.value, 10), sem_pagina_minutos: parseInt(minutos.value, 10) }); dizer('Salvo.'); } catch (e) { dizer(e.message, false); }
          } }, 'Salvar')),
        h('div', { class: 'linha-cfg' }, bEncerrar, h('span', { class: 'muted' }, 'Versão ' + c.versao_cerebro + ' · escuta só em 127.0.0.1 (nada sai do PC).'))));
      el.replaceChildren(h('div', { class: 'linha-cfg msg-cfg' }, msg), ...partes);      // a mensagem fica visível em qualquer seção
    }
    montar();
  }

  /* ---------- partida ---------- */
  const salvo = lembrar('tema');
  if (salvo) aplicarTema(salvo !== 'claro');
  aplicarRecolhida();
  atualizarLateral();
  setInterval(atualizarLateral, 10000);
  const batida = () => fetch('/api/ping').catch(() => {});
  batida();
  setInterval(batida, 20000);
  rota();
})();
