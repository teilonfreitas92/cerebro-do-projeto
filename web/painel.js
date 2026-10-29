/* Cérebro do Projeto — peças do layout de painel (dashboard): ícones, gaveta por cima da tela, abas internas e o "encaixe"
   que faz cada tela caber na área principal SEM barra de rolagem (abas internas, menu de seções e paginação).
   Carregado logo depois de ui.js. Nada aqui recebe dado como HTML: tudo é criado com h() / s() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, s, limpezas, guardar, lembrar } = UI;
  const largo = () => window.innerWidth >= 1024;          // abaixo disso a página rola normalmente (celular e janela estreita)

  /* ---------- ícones (traço simples, 24 x 24; caminhos fixos daqui, nunca dado de fora) ---------- */
  const ICONES = {
    todos: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
    visao: 'M4 18a8 8 0 1 1 16 0M12 14l4-5',
    agentes: 'M3 12h4l3-7 4 14 3-7h4',
    conferir: 'M20 6L9 17l-5-5',
    tarefas: 'M10 6h10M10 12h10M10 18h10M4 6l1.5 1.5L8 5M4 12l1.5 1.5L8 11M4 18l1.5 1.5L8 17',
    sessoes: 'M4 5h16v11H9l-5 4z',
    memoria: 'M6 4h9a3 3 0 0 1 3 3v13H9a3 3 0 0 1-3-3zM6 17a3 3 0 0 1 3-3h9',
    custos: 'M12 3v18M16 7.5c0-1.7-1.8-3-4-3s-4 1.3-4 3 1.8 2.6 4 3 4 1.3 4 3.2-1.8 3-4 3-4-1.3-4-3',
    mapa: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM8.5 14.5L12 9l3.5 5.5z',
    ferramentas: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z',
    analise: 'M5 20V11M11 20V5M17 20v-7M3 20h18',
    novidades: 'M12 3l2.4 5.6 6.1.6-4.6 4 1.4 6L12 16l-5.3 3.2 1.4-6-4.6-4 6.1-.6z',
    inventario: 'M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10',
    configuracoes: 'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4',
    fila: 'M6 16v-5a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
    recolher: 'M15 6l-6 6 6 6',
    abrir: 'M9 6l6 6-6 6',
    menu: 'M4 6h16M4 12h16M4 18h16',
    atualizar: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
    cheia: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
    ia: 'M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z',
    fechar: 'M6 6l12 12M18 6L6 18',
  };
  function icone(nome) {
    return s('svg', { class: 'ico', viewBox: '0 0 24 24', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
      s('path', { d: ICONES[nome] || ICONES.visao }));
  }

  /* ---------- gaveta: painel que desliza por cima da tela, sem empurrar o conteúdo ---------- */
  function gaveta(titulo, conteudo, opcoes) {
    opcoes = opcoes || {};
    let aberta = true;
    const fechar = () => {
      if (!aberta) return;
      aberta = false;
      fundo.remove();
      document.removeEventListener('keydown', tecla);
      if (opcoes.aoFechar) opcoes.aoFechar();
    };
    const tecla = ev => { if (ev.key === 'Escape') fechar(); };
    const corpo = h('div', { class: 'gaveta-corpo' }, conteudo);
    const painel = h('aside', { class: 'gaveta ' + (opcoes.lado || 'direita') + (opcoes.classe ? ' ' + opcoes.classe : ''), role: 'dialog', 'aria-label': titulo },
      h('header', { class: 'gaveta-cab' }, h('h3', null, titulo),
        h('button', { type: 'button', class: 'bt leve so', title: 'Fechar (Esc)', 'aria-label': 'Fechar', onclick: fechar }, icone('fechar'))),
      corpo);
    const fundo = h('div', { class: 'gaveta-fundo', onclick: ev => { if (ev.target === fundo) fechar(); } }, painel);
    document.body.append(fundo);
    document.addEventListener('keydown', tecla);
    limpezas.push(fechar);                     // trocou de tela: a gaveta fecha junto
    const foco = painel.querySelector('button');
    if (foco) foco.focus({ preventScroll: true });
    return { fechar, corpo, painel };
  }

  /* ---------- abas internas (uma seção por vez) ---------- */
  const abaLembrada = new Map();
  function abasInternas(itens, chave) {
    let atual = abaLembrada.get(chave) || lembrar('aba.' + chave) || itens[0][0];
    if (!itens.some(i => i[0] === atual)) atual = itens[0][0];
    const barra = h('nav', { class: 'abas-int', role: 'tablist', 'aria-label': 'Partes desta seção' });
    function desenhar() {
      barra.replaceChildren(...itens.map(([id, rotulo]) => h('button', { type: 'button', role: 'tab', class: 'aba-int' + (id === atual ? ' ativa' : ''), 'aria-selected': String(id === atual),
        onclick: () => mostrar(id) }, typeof rotulo === 'function' ? rotulo() : rotulo)));
    }
    function mostrar(id) {
      atual = id;
      abaLembrada.set(chave, id); guardar('aba.' + chave, id);
      itens.forEach(([i, , painel]) => { painel.hidden = i !== id; });
      desenhar();
    }
    mostrar(atual);
    return { barra, mostrar, desenhar, atual: () => atual };
  }

  /* ---------- paginador ---------- */
  function paginador(total, pagina, primeiro, ultimo, nItens, ir) {
    const bts = [];
    const num = i => h('button', { type: 'button', class: 'bt fino ' + (i === pagina ? 'pri' : 'leve'), 'aria-current': i === pagina ? 'page' : null, onclick: () => ir(i) }, String(i + 1));
    const mostrar = new Set([0, total - 1, pagina - 1, pagina, pagina + 1].filter(i => i >= 0 && i < total));
    let ant = -1;
    [...mostrar].sort((a, b) => a - b).forEach(i => { if (ant >= 0 && i > ant + 1) bts.push(h('span', { class: 'muted' }, '…')); bts.push(num(i)); ant = i; });
    return h('div', { class: 'paginador ui-auto', role: 'navigation', 'aria-label': 'Páginas' },
      h('button', { type: 'button', class: 'bt leve fino so', 'aria-label': 'Página anterior', disabled: pagina === 0, onclick: () => ir(pagina - 1) }, '‹'),
      bts,
      h('button', { type: 'button', class: 'bt leve fino so', 'aria-label': 'Próxima página', disabled: pagina >= total - 1, onclick: () => ir(pagina + 1) }, '›'),
      h('span', { class: 'muted' }, primeiro + '–' + ultimo + ' de ' + nItens));
  }

  /* ====================================================================================================== */
  /* Encaixe: a tela cabe na área principal                                                                  */
  /* ====================================================================================================== */
  /* Depois de cada mudança na tela (MutationObserver: roda antes de pintar, sem piscar) e quando a janela muda de tamanho:
     1) se a tela passa da altura e tem 2+ partes com título (cartões com <h3>), mostra uma parte por vez com abas internas
        (opcoes.menu: sempre, como menu à esquerda — Configurações);
     2) caixas marcadas com .caixa-pag (lista com altura fixa) viram páginas do tamanho da caixa;
     3) se ainda passa da altura, a maior lista (linhas de tabela, itens de lista, cartões repetidos) vira páginas.
     Só no painel largo (>= 1024 px); no estreito a página rola como antes. O que sobrar rola dentro da área principal. */
  const IGNORAR = '.grade.estreita, .barra, .linha, .meta, .nums, .kv, dl, select, thead, .abas-int, .paginador, .chips, .tf-filtros, .tf-pontos';
  const chaveTitulo = t => t.replace(/\(.*?\)|\d+/g, '').replace(/\s+/g, ' ').trim().toLowerCase();

  function encaixar(el, opcoes) {
    opcoes = opcoes || {};
    const principal = opcoes.principal || UI.raiz;
    const chave = opcoes.chave || 'tela';
    const est = { paginas: {} };
    let ocupado = false, vivo = true, quadro = 0;
    const obs = new MutationObserver(() => { if (!ocupado) ajustar(); });
    obs.observe(el, { childList: true, subtree: true });
    const aoMudarTamanho = () => { cancelAnimationFrame(quadro); quadro = requestAnimationFrame(ajustar); };
    window.addEventListener('resize', aoMudarTamanho);
    limpezas.push(() => { vivo = false; obs.disconnect(); window.removeEventListener('resize', aoMudarTamanho); cancelAnimationFrame(quadro); });
    const sobra = () => principal.scrollHeight - principal.clientHeight;
    const visivel = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
    ajustar();
    return { ajustar };

    function ajustar() {
      if (!vivo || !el.isConnected) return;
      ocupado = true;
      try { fazer(); } catch (e) { /* o encaixe nunca derruba a tela */ } finally { obs.takeRecords(); ocupado = false; }
    }

    function fazer() {
      el.querySelectorAll('.ui-auto').forEach(x => x.remove());
      el.querySelectorAll('.fora-aba, .fora-pag').forEach(x => x.classList.remove('fora-aba', 'fora-pag'));
      el.classList.remove('com-menu');
      if (!largo() && !opcoes.menu) return;
      montarAbas();
      if (!largo()) return;
      el.querySelectorAll('.caixa-pag').forEach((caixa, i) => { if (visivel(caixa)) paginarCaixa(caixa, 'caixa' + i); });
      for (let volta = 0; volta < 5 && sobra() > 1; volta++) {
        const c = melhorLista();
        if (!c || !paginarLista(c)) break;
      }
    }

    /* 1) abas internas a partir dos títulos */
    function titulo(e) {
      if (e.tagName === 'H3') return e.textContent;
      if (!/^(SECTION|DETAILS|ARTICLE)$/.test(e.tagName) && !e.classList.contains('cartao')) return '';
      const t = e.querySelector(':scope > h3, :scope > summary, :scope > .barra > h3, :scope > div > h3');
      return t ? t.textContent : '';
    }
    function montarAbas() {
      const unidades = [];
      const achatar = n => [...n.children].forEach(c => {
        if (c.classList.contains('ui-auto')) return;
        if (c.tagName === 'DIV' && !c.className && [...c.children].some(x => titulo(x))) achatar(c); else unidades.push(c);
      });
      achatar(el);
      const grupos = [], inicio = [];
      unidades.forEach(u => {
        const t = (titulo(u) || '').replace(/\s+/g, ' ').trim();
        if (t) grupos.push({ t, k: chaveTitulo(t), els: [u] });
        else if (grupos.length) grupos[grupos.length - 1].els.push(u);
        else inicio.push(u);
      });
      if (grupos.length < 2) return;
      if (!opcoes.menu && sobra() <= 1) return;
      // o que vem antes dos títulos fica sempre à vista; se for grande (números, gráficos), vira a última aba "Resumo"
      const altInicio = inicio.reduce((a, u) => a + u.getBoundingClientRect().height, 0);
      if (!opcoes.menu && altInicio > principal.clientHeight * 0.3) {
        const fixos = inicio.filter(u => u.getBoundingClientRect().height <= 60 && !/^(P)$/.test(u.tagName));   // barras de botões continuam à vista
        const resumo = inicio.filter(u => !fixos.includes(u));
        if (resumo.length) grupos.push({ t: 'Resumo', k: 'resumo', els: resumo });
      }
      if (opcoes.menu) grupos.forEach(g => { g.t = g.t.replace(/\s*\(.*$/, '') || g.t; });   // no menu, sem o "(…)" que corta o nome
      const lembrada = abaLembrada.get(chave) || lembrar('aba.' + chave);
      const ativa = grupos.find(g => g.k === lembrada) || grupos[0];
      grupos.forEach(g => { if (g !== ativa) g.els.forEach(e => e.classList.add('fora-aba')); });
      const barra = h('nav', { class: 'abas-int ui-auto' + (opcoes.menu ? ' menu' : ''), role: 'tablist', 'aria-label': 'Partes desta tela' },
        grupos.map(g => h('button', { type: 'button', role: 'tab', class: 'aba-int' + (g === ativa ? ' ativa' : ''), 'aria-selected': String(g === ativa), title: g.t,
          onclick: () => { abaLembrada.set(chave, g.k); guardar('aba.' + chave, g.k); principal.scrollTop = 0; ajustar(); } }, g.t.length > 46 ? g.t.slice(0, 44) + '…' : g.t)));
      const primeiro = grupos.flatMap(g => g.els).sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))[0];
      if (opcoes.menu) { el.classList.add('com-menu'); el.prepend(barra); } else primeiro.before(barra);
    }

    /* agrupa itens em linhas (para grades com várias colunas) e reparte as linhas em páginas de no máximo 'altura' */
    function repartir(itens, altura) {
      const linhas = [];
      itens.forEach(e => {
        const r = e.getBoundingClientRect();
        const l = linhas.find(x => Math.abs(x.topo - r.top) < 4);
        if (l) { l.itens.push(e); l.fim = Math.max(l.fim, r.bottom); } else linhas.push({ topo: r.top, fim: r.bottom, itens: [e] });
      });
      linhas.sort((a, b) => a.topo - b.topo);
      const paginas = [];
      let atual = null, inicio = 0;
      linhas.forEach(l => {
        if (!atual || (l.fim - inicio > altura && atual.length)) { atual = []; paginas.push(atual); inicio = l.topo; }
        atual.push(...l.itens);
      });
      return paginas;
    }
    function aplicar(paginas, chaveP, nItens, inserir) {
      if (paginas.length <= 1) return false;
      const pag = Math.max(0, Math.min(paginas.length - 1, est.paginas[chaveP] || 0));
      paginas.forEach((p, i) => { if (i !== pag) p.forEach(e => e.classList.add('fora-pag')); });
      let antes = 0;
      for (let i = 0; i < pag; i++) antes += paginas[i].length;
      inserir(paginador(paginas.length, pag, antes + 1, antes + paginas[pag].length, nItens, i => { est.paginas[chaveP] = i; ajustar(); }));
      return true;
    }

    /* 2) caixa de altura fixa: as páginas têm a altura da caixa */
    function paginarCaixa(caixa, chaveP) {
      if (caixa.scrollHeight <= caixa.clientHeight + 1) return;
      const itens = [...caixa.children].filter(e => !e.classList.contains('ui-auto') && visivel(e));
      if (itens.length < 2) return;
      const marca = h('div', { class: 'paginador ui-auto' }, h('button', { type: 'button', class: 'bt leve fino' }, '1'));   // reserva a altura do paginador
      caixa.after(marca);
      const cs = getComputedStyle(caixa);
      const altura = caixa.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - 2;
      const paginas = repartir(itens, altura);
      marca.remove();
      aplicar(paginas, chaveP, itens.length, p => caixa.after(p));
      caixa.scrollTop = 0;
    }

    /* 3) a maior lista visível vira páginas do tamanho que falta */
    function dentroDeRolagem(e) {
      for (let p = e.parentElement; p && p !== principal; p = p.parentElement) {
        if (p.classList.contains('caixa-pag')) return true;
        const o = getComputedStyle(p).overflowY;          // só conta quem rola de verdade (o .rolagem-x cresce com a tabela)
        if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight + 1) return true;
      }
      return false;
    }
    function itensDe(c) {
      if (c.matches(IGNORAR)) return null;
      const filhos = [...c.children].filter(e => !e.classList.contains('ui-auto') && !e.classList.contains('fora-pag') && !/^(H3|H4|SUMMARY)$/.test(e.tagName));
      if (filhos.length < 4) return null;
      const conta = new Map();
      filhos.forEach(e => { const k = e.tagName + '.' + e.className; conta.set(k, (conta.get(k) || 0) + 1); });
      const [sig, n] = [...conta.entries()].sort((a, b) => b[1] - a[1])[0];
      if (n < 4) return null;
      const itens = filhos.filter(e => e.tagName + '.' + e.className === sig);
      const disp = getComputedStyle(itens[0]).display;
      if (disp.startsWith('inline') || disp === 'none' || disp === 'contents') return null;
      return itens;
    }
    function melhorLista() {
      let melhor = null;
      el.querySelectorAll('tbody, ul, ol, div, section').forEach(c => {
        if (!visivel(c) || c.closest('.fora-aba') || dentroDeRolagem(c)) return;
        const itens = itensDe(c);
        if (!itens) return;
        const visiveis = itens.filter(visivel);
        if (visiveis.length < 2) return;
        const alt = visiveis[visiveis.length - 1].getBoundingClientRect().bottom - visiveis[0].getBoundingClientRect().top;
        if (alt > 120 && (!melhor || alt > melhor.alt)) melhor = { c, itens: visiveis, alt };
      });
      return melhor;
    }
    function paginarLista({ c, itens, alt }) {
      const cab = c.closest('section, details');
      const chaveP = (cab && titulo(cab) ? chaveTitulo(titulo(cab)) : '') + '|' + c.tagName + '.' + c.className;
      const inserir = p => (c.tagName === 'TBODY' ? c.closest('table').after(p) : /^(UL|OL)$/.test(c.tagName) ? c.after(p) : c.append(p));
      const marca = h('div', { class: 'paginador ui-auto' }, h('button', { type: 'button', class: 'bt leve fino' }, '1'));
      inserir(marca);
      const falta = sobra();
      marca.remove();
      const maior = Math.max(...itens.map(e => e.getBoundingClientRect().height));
      const altura = Math.max(maior, alt - falta - 2);
      const paginas = repartir(itens, altura);
      return aplicar(paginas, chaveP, itens.length, inserir);
    }
  }

  Object.assign(UI, { icone, gaveta, abasInternas, encaixar, largo });
})();
