/* Cérebro do Projeto — aba Janelas: mosaico de janelas de prompt lado a lado (ideia do MAESTRI), com dois tipos de janela:
     * terminal de verdade: o claude roda num pseudo-terminal do Cérebro e você digita aqui (xterm.js por WebSocket);
     * janela de leitura: o passo a passo ao vivo de uma sessão ou subagente (inclusive das outras IAs), sem controle.
   Nada que vem de transcrição entra como HTML: o xterm desenha texto e as janelas de leitura usam h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, api, post, haQuanto, modeloCurto, lembrar, guardar, limpezas, aoVivo, linhaPasso } = UI;
  const MAX_LEITURA = 8;
  const TEMA = { background: '#0c0c0c', foreground: '#e4e4e4', cursor: '#e4e4e4', selectionBackground: '#3a3d41',
    black: '#0c0c0c', red: '#ff6b6b', green: '#4ec96b', yellow: '#e5c07b', blue: '#61afef', magenta: '#c678dd', cyan: '#56b6c2', white: '#e4e4e4',
    brightBlack: '#6a6a6a', brightRed: '#ff8787', brightGreen: '#6fdc8c', brightYellow: '#f0d58c', brightBlue: '#82c0ff', brightMagenta: '#d7a1ea',
    brightCyan: '#7fd0da', brightWhite: '#ffffff' };

  UI.telas.janelas = function abaJanelas(slug, el, info, params) {
    const base = '/api/p/' + encodeURIComponent(slug);
    const chave = 'janelas.' + slug;
    let fixas = [];
    try { fixas = JSON.parse(lembrar(chave + '.fixas') || '[]').filter(x => typeof x === 'string'); } catch (e) { fixas = []; }
    let acompanhar = lembrar(chave + '.auto') !== '0';
    let colunas = lembrar('janelas.colunas') || 'auto';
    let dados = null, terms = [], disponivel = true, maxi = null, vivo = true;
    const abertas = new Map();                         // chave da janela -> { el, fechar() }
    const grade = h('div', { class: 'mosaico' });
    const msg = h('span', { class: 'muted msg-janelas', role: 'status' });
    const dizer = (t, ok) => { msg.textContent = t || ''; msg.className = 'msg-janelas ' + (ok === false ? 'erro' : 'muted'); };
    limpezas.push(() => { vivo = false; abertas.forEach(j => j.fechar()); abertas.clear(); });

    /* ---------- de onde vêm as janelas ---------- */
    function todosAgentes() {
      const lista = [];
      (dados ? dados.sessoes : []).forEach(n => { lista.push(n); n.subagentes.forEach(a => lista.push(a)); });
      return lista;
    }
    const acharRel = rel => todosAgentes().find(n => n.rel === rel) || null;
    function desejadas() {
      const quer = terms.map(t => ({ chave: 'pty:' + t.id, tipo: 'pty', t }));
      const noTerminal = new Set(terms.filter(t => t.vivo && t.sessao).map(t => t.sessao));
      const leitura = [];
      fixas.forEach(rel => leitura.push(rel));
      if (acompanhar) todosAgentes().filter(n => n.estado === 'trabalhando').forEach(n => leitura.push(n.rel));
      const vistos = new Set();
      leitura.forEach(rel => {
        const n = acharRel(rel);
        if (vistos.has(rel) || vistos.size >= MAX_LEITURA) return;
        if (n && n.tipo === 'sessao' && noTerminal.has(n.id)) return;           // já está num terminal de verdade
        vistos.add(rel);
        quer.push({ chave: 'ler:' + rel, tipo: 'ler', rel, n });
      });
      return quer;
    }
    function reconciliar() {
      if (!vivo) return;
      const quer = desejadas(), chaves = new Set(quer.map(q => q.chave));
      abertas.forEach((j, k) => { if (!chaves.has(k)) { j.fechar(); j.el.remove(); abertas.delete(k); } });
      quer.forEach((q, i) => {
        let j = abertas.get(q.chave);
        if (!j) { j = q.tipo === 'pty' ? janelaTerminal(q.t) : janelaLeitura(q.rel); abertas.set(q.chave, j); }
        j.atualizar(q.tipo === 'pty' ? q.t : acharRel(q.rel));
        if (grade.children[i] !== j.el) grade.insertBefore(j.el, grade.children[i] || null);
      });
      if (maxi && !abertas.has(maxi)) maxi = null;
      grade.classList.toggle('com-maxi', !!maxi);
      abertas.forEach((j, k) => j.el.classList.toggle('maxi', k === maxi));
      grade.dataset.colunas = colunas;
      vazio.hidden = abertas.size > 0;
      desenharEscolhas();
    }

    /* ---------- janela: cabeçalho comum ---------- */
    function moldura(chaveJ, classe) {
      const titulo = h('b', { class: 'tit' }), chips = h('span', { class: 'chips' }), acoes = h('span', { class: 'acoes' });
      const bMaxi = h('button', { type: 'button', class: 'bt leve fino so', title: 'Ampliar / voltar ao mosaico', 'aria-label': 'Ampliar janela',
        onclick: () => { maxi = maxi === chaveJ ? null : chaveJ; reconciliar(); setTimeout(() => window.dispatchEvent(new Event('resize')), 30); } }, '⤢');
      const corpo = h('div', { class: 'corpo-janela' });
      const el = h('section', { class: 'janela terminal ' + classe }, h('header', null, titulo, chips, h('span', { class: 'espaco' }), acoes, bMaxi), corpo);
      return { el, titulo, chips, acoes, corpo };
    }
    function chipEstado(est) { return h('span', { class: 'chip ' + (est === 'trabalhando' ? 'ok' : est === 'parado' ? 'warn' : '') }, h('span', { class: 'ponto ' + est }), est); }

    /* ---------- terminal de verdade ---------- */
    function janelaTerminal(t) {
      const m = moldura('pty:' + t.id, 'pty');
      const term = new window.Terminal({ fontFamily: '"JetBrains Mono", Consolas, ui-monospace, monospace', fontSize: 13, lineHeight: 1.15,
        cursorBlink: true, scrollback: 5000, theme: TEMA, allowProposedApi: false });
      const fit = new window.FitAddon.FitAddon();
      term.loadAddon(fit);
      term.open(m.corpo);
      let ws = null, terminou = false, quadro = 0, ultimoTam = '', tentativas = 0, fechado = false, confirmando = false;
      const enviar = o => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };
      function ajustar() {
        cancelAnimationFrame(quadro);
        quadro = requestAnimationFrame(() => {
          if (!m.el.isConnected || !m.corpo.clientWidth) return;
          try { fit.fit(); } catch (e) { return; }
          const tam = term.cols + 'x' + term.rows;
          if (tam !== ultimoTam) { ultimoTam = tam; enviar({ t: 'r', c: term.cols, l: term.rows }); }
        });
      }
      const obs = new ResizeObserver(ajustar);
      obs.observe(m.corpo);
      function conectar() {
        if (fechado) return;
        ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/terminais/' + encodeURIComponent(t.id) + '/ws');
        ws.onopen = () => { tentativas = 0; term.reset(); ultimoTam = ''; ajustar(); };
        ws.onmessage = ev => {
          let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
          if (d.t === 'd') term.write(d.d);
          else if (d.t === 'fim') { terminou = true; term.write('\r\n\x1b[90m[o claude terminou — feche a janela ou abra outra sessão]\x1b[0m\r\n'); desenharCab(); }
        };
        ws.onclose = () => { if (!fechado && !terminou && tentativas++ < 5) setTimeout(conectar, 800 * tentativas); };
      }
      term.onData(d => { if (!terminou) enviar({ t: 'e', d }); });
      conectar();
      const bFechar = h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
        if (!terminou && !confirmando) {
          confirmando = true; bFechar.textContent = 'Clique de novo: encerra o claude';
          setTimeout(() => { confirmando = false; bFechar.textContent = 'Fechar'; }, 4000); return;
        }
        try { await post('/api/terminais/' + encodeURIComponent(t.id) + '/fechar'); } catch (e) { dizer(e.message, false); }
        carregarTerminais();
      } }, 'Fechar');
      m.acoes.append(bFechar);
      function desenharCab() {
        m.titulo.textContent = t.titulo;
        m.titulo.title = t.sessao ? 'sessão ' + t.sessao : 'sessão nova do Claude Code';
        m.chips.replaceChildren(h('span', { class: 'chip accent', title: 'Você controla: digite, aprove, Esc para interromper' }, 'terminal'),
          terminou || !t.vivo ? h('span', { class: 'chip' }, 'terminou') : h('span', { class: 'chip ok' }, h('span', { class: 'ponto trabalhando' }), 'ao vivo'));
      }
      m.el.addEventListener('mousedown', () => setTimeout(() => term.focus(), 0));
      return {
        el: m.el,
        atualizar(novo) { t = novo; if (!t.vivo) terminou = true; desenharCab(); ajustar(); },
        fechar() { fechado = true; obs.disconnect(); cancelAnimationFrame(quadro); if (ws) ws.close(); term.dispose(); },
      };
    }

    /* ---------- janela de leitura (passo a passo ao vivo) ---------- */
    function janelaLeitura(rel) {
      const m = moldura('ler:' + rel, 'leitura');
      const lista = h('div', { class: 'passos' }), rodape = h('footer');
      m.corpo.append(lista, rodape);
      let n = null;
      const es = new EventSource(base + '/passos?arquivo=' + encodeURIComponent(rel));
      es.onmessage = ev => {
        let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
        const noFim = lista.scrollHeight - lista.scrollTop - lista.clientHeight < 80;
        if (d.tipo === 'inicio') {
          lista.replaceChildren();
          if (!d.passos.length) lista.append(h('div', { class: 'passo sistema' }, 'Nada ainda. Os passos aparecem aqui assim que o agente escrever.'));
        }
        d.passos.forEach(p => lista.append(linhaPasso(p, n && n.tipo === 'subagente')));
        while (lista.children.length > 300) lista.firstChild.remove();
        if (noFim || d.tipo === 'inicio') lista.scrollTop = lista.scrollHeight;
      };
      const fixa = () => fixas.includes(rel);
      const bFixar = h('button', { type: 'button', class: 'bt leve fino', onclick: () => {
        fixas = fixa() ? fixas.filter(r => r !== rel) : fixas.concat(rel);
        guardar(chave + '.fixas', JSON.stringify(fixas)); reconciliar();
      } });
      const bControlar = h('button', { type: 'button', class: 'bt pri fino', title: 'Abre esta sessão num terminal de verdade aqui', onclick: () => n && abrirTerminal(n.id, n.titulo) }, 'Controlar');
      m.acoes.append(bControlar, bFixar);
      return {
        el: m.el,
        atualizar(novo) {
          n = novo || n;
          m.titulo.textContent = n ? (n.descricao || n.titulo) : rel;
          m.titulo.title = m.titulo.textContent;
          m.chips.replaceChildren(n ? chipEstado(n.estado) : null,
            n && n.tipo === 'subagente' ? h('span', { class: 'chip' }, n.tipo_agente || 'subagente') : h('span', { class: 'chip' }, 'sessão'),
            n && n.modelo ? h('span', { class: 'chip' }, modeloCurto(n.modelo)) : null,
            h('span', { class: 'chip', title: 'Só mostra; para digitar, use Controlar (sessões)' }, 'só leitura'));
          bControlar.hidden = !n || n.tipo !== 'sessao';
          bFixar.textContent = fixa() ? 'Soltar' : 'Fixar';
          bFixar.title = fixa() ? 'Some quando parar de trabalhar' : 'Fica no mosaico mesmo parada';
          rodape.replaceChildren(n && n.estado === 'trabalhando' ? h('span', { class: 'trabalhando' }, '✻ Trabalhando…') : h('span', { class: 'muted' }, n ? 'atualizado ' + haQuanto(n.mtime) : ''));
        },
        fechar() { es.close(); },
      };
    }

    /* ---------- abrir terminal (sessão nova ou retomando) ---------- */
    async function abrirTerminal(sessao, titulo, forcar) {
      dizer('Abrindo o terminal…');
      try {
        const t = await post(base + '/terminais', { sessao: sessao || null, titulo: titulo || '', cols: 120, rows: 32, forcar: !!forcar });
        dizer('');
        maxi = null;
        await carregarTerminais();
        const j = abertas.get('pty:' + t.id);
        if (j) j.el.scrollIntoView({ block: 'nearest' });
      } catch (e) {
        if (/brigam/.test(e.message)) {
          msg.replaceChildren(h('span', { class: 'erro' }, e.message + ' '),
            h('button', { type: 'button', class: 'bt perigo fino', onclick: () => abrirTerminal(sessao, titulo, true) }, 'Abrir mesmo assim'));
          msg.className = 'msg-janelas';
        } else dizer(e.message, false);
      }
    }
    async function carregarTerminais() {
      try {
        const d = await api(base + '/terminais');
        terms = d.terminais; disponivel = d.disponivel;
      } catch (e) { /* segue com o que tinha */ }
      bNova.disabled = !disponivel; selRetomar.disabled = !disponivel;
      avisoPty.hidden = disponivel;
      reconciliar();
    }

    /* ---------- barra ---------- */
    const bNova = h('button', { type: 'button', class: 'bt pri fino', onclick: () => abrirTerminal(null, 'sessão nova') }, '+ Nova sessão do Claude');
    const selRetomar = h('select', { 'aria-label': 'Retomar uma sessão num terminal', onchange: e => {
      const n = acharRel(e.target.value); e.target.value = '';
      if (n) abrirTerminal(n.id, n.titulo);
    } });
    const selFixar = h('select', { 'aria-label': 'Fixar uma janela de leitura', onchange: e => {
      const rel = e.target.value; e.target.value = '';
      if (rel && !fixas.includes(rel)) { fixas = fixas.concat(rel); guardar(chave + '.fixas', JSON.stringify(fixas)); reconciliar(); }
    } });
    function desenharEscolhas() {
      const sess = dados ? dados.sessoes : [];
      selRetomar.replaceChildren(h('option', { value: '' }, 'Controlar uma sessão…'),
        sess.map(n => h('option', { value: n.rel }, (n.gestora ? '[gestor] ' : '') + n.titulo.slice(0, 70) + ' · ' + haQuanto(n.mtime))));
      selFixar.replaceChildren(h('option', { value: '' }, 'Mostrar a janela de…'),
        todosAgentes().filter(n => !fixas.includes(n.rel)).map(n => h('option', { value: n.rel },
          (n.tipo === 'subagente' ? '   ↳ ' + (n.descricao || '').slice(0, 60) : n.titulo.slice(0, 70)) + ' · ' + n.estado)));
    }
    const selColunas = h('select', { 'aria-label': 'Colunas do mosaico', onchange: e => { colunas = e.target.value; guardar('janelas.colunas', colunas); reconciliar(); } },
      [['auto', 'Colunas: automático'], ['1', '1 coluna'], ['2', '2 colunas'], ['3', '3 colunas'], ['4', '4 colunas']].map(([v, r]) => h('option', { value: v, selected: v === colunas }, r)));
    const chkAuto = h('input', { type: 'checkbox', checked: acompanhar, onchange: e => { acompanhar = e.target.checked; guardar(chave + '.auto', acompanhar ? '1' : '0'); reconciliar(); } });
    const avisoPty = h('div', { class: 'aviso-caixa', hidden: true }, 'Terminal de verdade indisponível: falta o pywinpty neste Python. Rode o instalar.py de novo (ou: pip install pywinpty) e reinicie o Cérebro. As janelas de leitura funcionam.');
    const vazio = h('div', { class: 'vazio cartao' }, 'Nenhuma janela. Abra uma sessão nova do Claude, controle uma sessão existente ou escolha uma janela para acompanhar. ',
      'Com "acompanhar quem está trabalhando", cada agente que começar a escrever ganha uma janela sozinho.');
    el.append(
      h('div', { class: 'barra barra-janelas' }, bNova, selRetomar, selFixar, h('label', { class: 'chk muted' }, chkAuto, 'acompanhar quem está trabalhando'),
        h('span', { class: 'espaco' }), selColunas),
      h('div', { class: 'linha-msg' }, msg),
      avisoPty,
      h('p', { class: 'nota' }, 'Terminal: o claude roda aqui, na pasta do projeto, e você digita como no cmd (aprovações, Esc, /comandos). ',
        'Janela de leitura: mostra ao vivo, sem controle. Uma sessão aberta no app do Claude e aqui ao mesmo tempo briga: feche lá antes de controlar aqui.'),
      vazio, grade);

    aoVivo(base + '/agentes/stream', d => { dados = d; reconciliar(); });
    carregarTerminais();
    UI.cada(4000, carregarTerminais);
    if (params.get('ver') && !fixas.includes(params.get('ver'))) { fixas = fixas.concat(params.get('ver')); guardar(chave + '.fixas', JSON.stringify(fixas)); }
    if (params.get('retomar')) {
      const sessao = params.get('retomar');
      history.replaceState(null, '', '#/p/' + encodeURIComponent(slug) + '/janelas');     // recarregar a página não reabre
      abrirTerminal(sessao, '');
    }
  };
})();
