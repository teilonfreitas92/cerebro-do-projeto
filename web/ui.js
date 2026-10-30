/* Cérebro do Projeto — utilitários da página (JS puro, sem build). Carregado ANTES das abas.
   Regra de segurança: NADA que vem de transcrição, memória ou configuração entra na página como HTML. Tudo é criado com
   h() / textContent, então um texto malicioso num transcrito não executa nada. */
(() => {
  'use strict';
  const raiz = document.getElementById('raiz');
  const limpezas = [];                       // funções a chamar ao sair da tela (timers, EventSource)
  const limpar = () => { while (limpezas.length) { try { limpezas.pop()(); } catch (e) { /* já fechado */ } } };

  /* ---------- utilitários de DOM e formatação ---------- */
  /* Element.replaceChildren(null) / append(false) escrevem a palavra "null" / "false" na tela: ignora esses valores em TODA a página */
  ['replaceChildren', 'append', 'prepend'].forEach(nome => {
    const original = Element.prototype[nome];
    Element.prototype[nome] = function (...nos) { return original.apply(this, nos.flat(Infinity).filter(n => n != null && n !== false && n !== true)); };
  });
  function juntar(e, filhos) {
    for (const f of filhos.flat(Infinity)) { if (f == null || f === false) continue; e.append(f.nodeType ? f : document.createTextNode(String(f))); }
  }
  function h(tag, attrs, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'estilo') Object.assign(e.style, v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    juntar(e, filhos);
    return e;
  }
  const svgNS = 'http://www.w3.org/2000/svg';
  function s(tag, attrs, ...filhos) {
    const e = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    juntar(e, filhos);
    return e;
  }
  /* troca o conteúdo de um elemento ignorando null/false (replaceChildren(null) escreveria a palavra "null") */
  function trocar(e, ...filhos) { e.replaceChildren(); juntar(e, filhos); }
  const num = n => (n == null ? '—' : Number(n).toLocaleString('pt-BR'));
  function tok(n) {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(2).replace('.', ',') + ' bi';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', ',') + ' mi';
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace('.', ',') + ' mil';
    return String(n);
  }
  function usd(n, semPreco) {
    if (n == null || (semPreco && !n)) return 'a conferir';
    return 'US$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: n < 100 ? 2 : 0, maximumFractionDigits: n < 100 ? 2 : 0 }) + (semPreco ? '*' : '');
  }
  function haQuanto(t) {
    if (!t) return '—';
    const d = Date.now() / 1000 - t;
    if (d < 45) return 'agora';
    if (d < 3600) return 'há ' + Math.round(d / 60) + ' min';
    if (d < 86400) return 'há ' + Math.round(d / 3600) + ' h';
    return 'há ' + Math.round(d / 86400) + ' d';
  }
  const dataCurta = t => (t ? new Date(t * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—');
  const hora = t => (t ? new Date(t * 1000).toLocaleTimeString('pt-BR') : '');
  const modeloCurto = m => (m || '').replace(/^claude-/, '').replace(/-\d{8}$/, '');
  const tamanho = n => (n >= 1e6 ? (n / 1e6).toFixed(1).replace('.', ',') + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB');
  const guardar = (k, v) => { try { localStorage.setItem('cerebro.' + k, v); } catch (e) { /* sem armazenamento */ } };
  const lembrar = k => { try { return localStorage.getItem('cerebro.' + k); } catch (e) { return null; } };

  /* ---------- API ---------- */
  function expirada() {
    if (document.getElementById('cobertura')) return;
    document.body.append(h('div', { class: 'cobertura', id: 'cobertura' }, h('div', { class: 'cartao' },
      h('h2', null, 'Sessão expirada'), h('p', { class: 'muted' }, 'O Cérebro foi reiniciado ou a chave mudou. Abra de novo pelo atalho (abrir_cerebro.py).'))));
  }
  async function api(caminho, opcoes) {
    const r = await fetch(caminho, opcoes);
    if (r.status === 401) { expirada(); throw new Error('não autorizado'); }
    let d = null;
    try { d = await r.json(); } catch (e) { /* sem corpo */ }
    if (!r.ok) throw new Error((d && d.erro) || ('erro ' + r.status));
    return d;
  }
  const post = (caminho, corpo) => api(caminho, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo || {}) });
  function cada(ms, fn) { const id = setInterval(fn, ms); limpezas.push(() => clearInterval(id)); return id; }
  function aoVivo(url, aoReceber) {
    const es = new EventSource(url);
    es.onmessage = ev => { try { aoReceber(JSON.parse(ev.data)); } catch (e) { /* mensagem quebrada */ } };
    limpezas.push(() => es.close());
    return es;
  }

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

  window.CerebroUI = { raiz, limpezas, limpar, juntar, h, s, trocar, num, tok, usd, haQuanto, dataCurta, hora, modeloCurto, tamanho, guardar, lembrar,
    api, post, cada, aoVivo, expirada, linhaPasso, telas: {}, secoesConfig: [] };
})();
