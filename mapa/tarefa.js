/* Cérebro do Projeto — mapa: botão "Criar tarefa aqui". Abre uma janelinha para criar uma tarefa para o gestor já com o ponto
   do mapa preenchido (grupo, arquivo ou função). Só funciona servido pelo Cérebro (mesmo endereço e mesma chave de acesso do painel);
   aberto direto do disco (file://) o botão nem aparece. Nada que vem do mapa entra como HTML: tudo é criado com textContent. */
(() => {
  'use strict';
  const m = location.pathname.match(/^\/mapa\/([^/]+)\//);
  if (!m || location.protocol === 'file:') return;
  const slug = decodeURIComponent(m[1]);
  const api = '/api/p/' + encodeURIComponent(slug) + '/tarefas-gestor';

  function el(tag, attrs, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const f of filhos.flat(Infinity)) { if (f != null && f !== false) e.append(f.nodeType ? f : document.createTextNode(String(f))); }
    return e;
  }
  async function chamar(caminho, corpo) {
    const r = await fetch(caminho, corpo ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) } : undefined);
    let d = null;
    try { d = await r.json(); } catch (e) { /* sem corpo */ }
    if (!r.ok) throw new Error((d && d.erro) || ('erro ' + r.status));
    return d;
  }
  const textoPonto = p => p.tipo + ' ' + p.nome + (p.arquivo ? ' · ' + p.arquivo + (p.linha ? ':' + p.linha : '') : '');

  const css = el('style', null, `
    .tf-fundo { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 16px; background: color-mix(in srgb, var(--bg) 70%, transparent); backdrop-filter: blur(3px); }
    .tf-caixa { width: min(560px, 100%); max-height: 100%; overflow: auto; background: var(--surface); border: 1px solid var(--border-2); border-radius: var(--r-cartao, 14px);
      box-shadow: var(--shadow); padding: 16px 18px; display: grid; gap: 10px; }
    .tf-caixa h2 { margin: 0; font: 700 17px/1.3 var(--font-display); }
    .tf-caixa label { display: grid; gap: 4px; font-size: 12.5px; color: var(--text-soft); }
    .tf-caixa input, .tf-caixa textarea, .tf-caixa select { width: 100%; font: 13px var(--font); color: var(--text); background: var(--surface-2); border: 1px solid var(--border-2);
      border-radius: var(--r-btn); padding: 6px 9px; }
    .tf-caixa textarea { min-height: 78px; resize: vertical; }
    .tf-caixa input:focus-visible, .tf-caixa textarea:focus-visible, .tf-caixa select:focus-visible { outline: 2px solid var(--accent); }
    .tf-pontos { display: flex; flex-wrap: wrap; gap: 6px; }
    .tf-ponto { display: inline-flex; align-items: center; gap: 4px; padding: 3px 4px 3px 10px; border-radius: 99px; background: var(--accent-soft); color: var(--accent-text); font-size: 12px; overflow-wrap: anywhere; }
    .tf-ponto button { border: 0; background: transparent; color: inherit; cursor: pointer; font-size: 14px; padding: 0 6px; }
    .tf-agente { font-size: 12.5px; color: var(--text-soft); background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--r-btn); padding: 6px 10px; }
    .tf-acoes { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .tf-erro { color: var(--danger-text); font-size: 13px; }
    .tf-ok { color: var(--ok-text); font-size: 13.5px; }
  `);
  document.head.append(css);

  let aberto = null;
  function fechar() { if (aberto) { aberto.remove(); aberto = null; } }

  async function abrir(ponto) {
    fechar();
    let opcoes;
    try { opcoes = (await chamar(api)).opcoes; } catch (e) { alert('Não consegui falar com o Cérebro: ' + e.message); return; }
    const pontos = [ponto];
    const titulo = el('input', { type: 'text', maxlength: 160, 'aria-label': 'Título da tarefa', placeholder: 'O que precisa ser feito, numa frase' });
    const descricao = el('textarea', { maxlength: 4000, 'aria-label': 'Descrição', placeholder: 'Explique o que você quer e como saber que ficou pronto.' });
    const prioridade = el('select', { 'aria-label': 'Prioridade' }, opcoes.prioridades.map(p => el('option', Object.assign({ value: p }, p === 'normal' ? { selected: true } : {}), p)));
    const agente = el('select', { 'aria-label': 'Tipo de agente' }, el('option', { value: '' }, 'Deixar o Cérebro sugerir (pelas palavras do pedido)'),
      opcoes.agentes.map(a => el('option', { value: a.id }, a.nome + ' — ' + a.modelo)));
    const infoAgente = el('div', { class: 'tf-agente' });
    const mostrarAgente = () => {
      const a = opcoes.agentes.find(x => x.id === agente.value);
      infoAgente.textContent = a ? 'Modelo: ' + a.modelo + ' · Quem revisa: ' + a.revisor : 'O Cérebro escolhe o tipo pelas palavras do título e da descrição e mostra o modelo e quem revisa na aba Tarefas.';
    };
    agente.addEventListener('change', mostrarAgente);
    mostrarAgente();
    const chips = el('div', { class: 'tf-pontos' });
    const desenharChips = () => { chips.replaceChildren(...pontos.map(p => el('span', { class: 'tf-ponto', title: textoPonto(p) }, textoPonto(p),
      el('button', { type: 'button', 'aria-label': 'Tirar este ponto', onclick: () => { pontos.splice(pontos.indexOf(p), 1); desenharChips(); } }, '×')))); };
    desenharChips();
    const msg = el('span', { class: 'tf-erro' });
    const criar = el('button', { type: 'button', class: 'bt pri', onclick: async () => {
      msg.className = 'tf-erro'; msg.textContent = '';
      if (!titulo.value.trim()) { msg.textContent = 'Escreva o título da tarefa.'; titulo.focus(); return; }
      criar.disabled = true;
      try {
        const r = await chamar(api, { titulo: titulo.value, descricao: descricao.value, prioridade: prioridade.value, agente_tipo: agente.value, pontos });
        const it = r.item;
        caixa.replaceChildren(el('h2', null, 'Tarefa criada'),
          el('p', { class: 'tf-ok' }, it.id + ' · ' + it.titulo), el('p', null, it.agente ? 'Tipo de agente: ' + it.agente.nome + ' (modelo ' + it.agente.modelo + '). Quem revisa: ' + it.agente.revisor + '.' : 'Sem tipo de agente: o gestor decide.'),
          el('p', null, 'O gestor recebe as tarefas novas no começo da conversa do projeto.'),
          el('div', { class: 'tf-acoes' }, el('a', { class: 'bt leve', href: '/#/p/' + encodeURIComponent(slug) + '/tarefas', target: '_top' }, 'Ver na aba Tarefas'),
            el('button', { type: 'button', class: 'bt pri', onclick: fechar }, 'Fechar')));
      } catch (e) { msg.textContent = e.message; criar.disabled = false; }
    } }, 'Criar tarefa');
    const caixa = el('div', { class: 'tf-caixa', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Nova tarefa para o gestor' },
      el('h2', null, 'Nova tarefa para o gestor'),
      el('label', null, 'Título', titulo), el('label', null, 'Descrição', descricao),
      el('div', null, el('b', { style: 'font-size:12.5px' }, 'Onde mexer (ponto do mapa)'), chips),
      el('label', null, 'Prioridade', prioridade), el('label', null, 'Tipo de agente', agente), infoAgente,
      el('div', { class: 'tf-acoes' }, criar, el('button', { type: 'button', class: 'bt leve', onclick: fechar }, 'Cancelar'), msg));
    const fundo = el('div', { class: 'tf-fundo', onmousedown: ev => { if (ev.target === fundo) fechar(); } }, caixa);
    // as teclas do mapa (/, 0, Esc) não podem disparar enquanto a pessoa escreve aqui
    fundo.addEventListener('keydown', ev => { ev.stopPropagation(); if (ev.key === 'Escape') fechar(); });
    document.body.append(fundo);
    aberto = fundo;
    titulo.focus();
  }

  window.CerebroTarefa = { abrir };
})();
