/* Cérebro do Projeto — sessão gestora (mesma sessão + limpeza): corrente de transcrições, linha do tempo dos capítulos, autorização
   da limpeza das transcrições antigas, faixa "Cérebro atualizado" e "Manual do gestor neste projeto" (Configurações).
   Nada que vem de conversa ou arquivo entra como HTML: tudo com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, num, dataCurta, api, post } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);
  const ESTADO = { atual: 'atual', anterior: 'anterior', arquivada: 'arquivada', apagada: 'apagada' };

  function janela(titulo, ...filhos) {
    const fechar = () => cob.remove();
    const cob = h('div', { class: 'cobertura', role: 'dialog', 'aria-label': titulo, onclick: ev => { if (ev.target === cob) fechar(); } },
      h('div', { class: 'cartao', estilo: { maxWidth: '920px', width: 'calc(100% - 32px)', textAlign: 'left', maxHeight: '90vh', overflow: 'auto' } },
        h('div', { class: 'barra', estilo: { justifyContent: 'space-between', margin: '0 0 8px' } }, h('h3', { estilo: { margin: 0 } }, titulo),
          h('button', { type: 'button', class: 'bt leve fino', onclick: () => fechar() }, 'Fechar')), ...filhos));
    document.body.append(cob);
    UI.limpezas.push(fechar);
    return { fechar, corpo: cob.firstChild };
  }
  function caixaTexto(texto, linhas) {
    const t = h('textarea', { rows: linhas || 18, readonly: true, 'aria-label': 'Texto', estilo: { width: '100%', fontFamily: 'var(--font-mono)', fontSize: '12.5px' } });
    t.value = texto;
    const ok = h('span', { class: 'msg-ok' });
    return h('div', null, t, h('div', { class: 'barra', estilo: { marginTop: '8px' } }, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
      try { await navigator.clipboard.writeText(texto); ok.textContent = 'Copiado.'; } catch (e) { t.select(); ok.textContent = 'Selecionado: use Ctrl+C.'; }
    } }, 'Copiar'), ok));
  }
  async function abrirArquivo(slug, rota, nome, titulo) {
    const j = janela(titulo, h('p', { class: 'muted' }, 'Carregando…'));
    try {
      const r = await api(base(slug) + rota + '?nome=' + encodeURIComponent(nome));
      trocar(j.corpo, j.corpo.firstChild, h('p', { class: 'nota mono' }, r.nome), caixaTexto(r.texto, 24));
    } catch (e) { trocar(j.corpo, j.corpo.firstChild, h('p', { class: 'msg-erro' }, e.message)); }
  }

  /* botão que pede um segundo clique para confirmar */
  function botaoConfirmar(rotulo, rotuloConfirmar, classe, acao) {
    let armado = false;
    const b = h('button', { type: 'button', class: 'bt fino ' + classe, onclick: async () => {
      if (!armado) { armado = true; b.textContent = rotuloConfirmar; setTimeout(() => { armado = false; b.textContent = rotulo; }, 5000); return; }
      armado = false; b.textContent = rotulo; await acao(b);
    } }, rotulo);
    return b;
  }

  /* ---------- Aba Sessões: corrente da gestora e capítulos ---------- */
  UI.sessoesTopo = function (slug) {
    const caixa = h('section', { class: 'cartao', estilo: { marginBottom: '12px' } }, h('div', { class: 'vazio' }, 'Carregando a corrente da gestora…'));
    const msg = h('span', { class: 'muted' });
    async function autorizar(ligar) {
      try { await post(base(slug) + '/gestora/autorizar', { ligar, confirmar: true }); carregar(); } catch (e) { msg.className = 'msg-erro'; msg.textContent = e.message; }
    }
    async function carregar() {
      let d;
      try { d = await api(base(slug) + '/gestora/corrente'); } catch (e) { trocar(caixa, h('div', { class: 'vazio' }, e.message)); return; }
      const v = d.vigia;
      const elos = d.elos.map((e, i) => h('li', null,
        h('span', { class: 'chip ' + (e.estado === 'atual' ? 'violet' : e.estado === 'apagada' ? 'perigo' : '') }, ESTADO[e.estado] || e.estado), ' ',
        h('span', { class: 'muted' }, dataCurta(e.inicio) + ' → ' + (e.fim ? dataCurta(e.fim) : 'agora')), ' ',
        e.como ? h('span', { class: 'muted' }, '· ' + e.como) : null,
        h('div', { class: 'muted mono', estilo: { fontSize: '11px' } }, e.conversa),
        e.capitulo ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => abrirArquivo(slug, '/gestora/capitulo', e.capitulo, 'Capítulo da gestora') }, 'Abrir o capítulo desta troca') : null,
        e.bastao ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => abrirArquivo(slug, '/gestora/bastao', e.bastao, 'Passa-bastão') }, 'Abrir o passa-bastão') : null,
        i < d.elos.length - 1 ? h('div', { class: 'muted' }, '↓') : null));
      const caps = (d.capitulos || []).map(c => h('li', null, h('b', null, dataCurta(c.em)), ' ', h('span', null, c.resumo || '(sem resumo)'), ' ',
        h('button', { type: 'button', class: 'bt leve fino', onclick: () => abrirArquivo(slug, '/gestora/capitulo', c.nome, 'Capítulo da gestora') }, 'Abrir')));
      const n = d.candidatos.length;
      trocar(caixa,
        h('h3', { estilo: { margin: '0 0 6px' } }, 'Corrente da gestora'),
        v.conversa ? h('p', { class: v.longa ? 'msg-erro' : 'muted' }, 'Contexto da gestora: ≈ ' + num(Math.round(v.contexto / 1000)) + ' mil tokens (' + String(v.pct).replace('.', ',') + '% da janela)'
          + (v.longa ? ' — passou de ' + v.limite_pct + '%: ' + (v.ativo ? 'no próximo pedido ela recebe o recado de gravar o capítulo e limpar a conversa (na mesma sessão).'
          : 'quando encher, o Claude Code compacta sozinho e o Cérebro grava o capítulo antes.') : '.'))
          : h('p', { class: 'muted' }, 'Este projeto ainda não tem sessão gestora: use "Definir gestora" numa sessão abaixo.'),
        h('p', { class: 'nota' }, 'A gestora nunca é trocada. Quando a conversa enche, o Claude Code compacta sozinho: o Cérebro grava um capítulo antes e devolve o resumo depois, sem você fazer nada. A limpeza na mesma sessão é opcional (Configurações); cada limpeza abre um elo novo aqui.'),
        d.elos.length ? h('ol', null, elos) : null,
        h('div', { class: 'linha-cfg' },
          h('span', null, n ? n + ' transcrição(ões) antiga(s) fora de uso há mais de ' + d.dias_limpeza + ' dias.' : 'Nenhuma transcrição antiga para tirar.'),
          d.autorizado ? h('span', { class: 'chip ok' }, 'limpeza automática autorizada')
            : botaoConfirmar('Autorizar a limpeza automática', 'Clique de novo para autorizar', 'leve', () => autorizar(true)),
          d.autorizado ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => autorizar(false) }, 'Desligar') : null, msg),
        h('p', { class: 'nota' }, 'Só saem transcrições "anterior" deste projeto, com mais de ' + d.dias_limpeza + ' dias, que estão no backup mais novo, conferido e idêntico (mesmo sha256). Capítulos e decisões ficam para sempre.'),
        h('details', { open: caps.length > 0 && caps.length < 6 }, h('summary', null, 'Linha do tempo dos capítulos: ' + caps.length),
          caps.length ? h('ol', null, caps) : h('p', { class: 'muted' }, 'Nenhum capítulo ainda. Eles aparecem sozinhos com os ganchos ligados (compactação e limpeza).')));
    }
    carregar();
    return caixa;
  };

  /* ---------- Painel geral: faixa "Cérebro atualizado" (fecha com um clique) ---------- */
  UI.faixaHub = function () {
    const caixa = h('div');
    api('/api/gestor/manual').then(m => {
      if (!m.mostrar_faixa) return;
      // uma linha só (recolhida): os cartões dos projetos ficam à vista; "Ver o que mudou" abre a lista
      const fechar = h('button', { type: 'button', class: 'bt leve fino', onclick: async ev => { ev.preventDefault(); try { await post('/api/gestor/manual/visto', {}); } catch (e) { /* some de qualquer jeito */ } caixa.replaceChildren(); } }, 'Fechar');
      trocar(caixa, h('details', { class: 'cartao fila faixa-aviso', estilo: { marginBottom: '12px' } },
        h('summary', null, h('b', null, 'Cérebro atualizado para ' + m.atualizado_para + ': o que mudou para o gestor'),
          h('span', { class: 'muted' }, ' · ' + (m.mudancas.length || 1) + ' item(ns) · Ver o que mudou'), h('span', { class: 'espaco' }), fechar),
        m.mudancas.length ? h('ul', null, m.mudancas.map(x => h('li', null, x))) : h('div', { class: 'muted' }, 'O manual do gestor foi refeito: ' + m.arquivo),
        h('div', { class: 'muted' }, 'As sessões gestoras recebem o aviso sozinhas na próxima mensagem.')));
    }).catch(() => {});
    return caixa;
  };

  /* ---------- Primeiro uso (#/bem-vindo): ligar os ganchos (recomendado), só com o sim da pessoa ---------- */
  UI.passoGanchos = async function (palco, navegacao) {
    trocar(palco, h('div', { class: 'vazio' }, 'Conferindo os ganchos do Claude Code…'));
    let e;
    try { e = await api('/api/ganchos/estado'); } catch (er) { trocar(palco, h('div', { class: 'vazio' }, er.message), navegacao('Concluir →')); return; }
    const ligado = (e.eventos || []).length > 0;
    const diff = h('pre', { class: 'saida', hidden: true, estilo: { maxHeight: '320px' } });
    const msg = h('p', { class: 'muted' });
    const opcoes = { hooks: true, modo: 'comando', statusline: null };
    const bLigar = botaoConfirmar('Ligar os ganchos (recomendado)', 'Clique de novo para gravar no settings.json', 'pri', async b => {
      b.disabled = true;
      try {
        const r = await post('/api/ganchos/instalar', { ...opcoes, confirmar: true });
        msg.className = 'msg-ok'; msg.textContent = r.mudou ? 'Ligado. Cópia de segurança do settings.json: ' + (r.copia || '(o arquivo não existia)') : 'Já estava ligado.';
      } catch (er) { msg.className = 'msg-erro'; msg.textContent = er.message; b.disabled = false; }
    });
    trocar(palco, h('section', { class: 'cartao guia' }, h('h3', null, 'Ganchos do Claude Code ' + (ligado ? '(já ligados)' : '(recomendado)')),
      h('p', null, 'Os ganchos fazem o Claude Code avisar o Cérebro na hora: agentes ao vivo, tarefas novas chegando à gestora, capítulos da conversa gestora (gravados antes de cada compactação, com o resumo devolvido depois) e a limpeza opcional na mesma sessão.'),
      h('ul', null,
        h('li', null, 'O que muda: o Cérebro acrescenta as entradas dele em "hooks" no seu ', h('code', null, e.arquivo || '~/.claude/settings.json'), '. Nada do que já existe é apagado.'),
        h('li', null, 'Antes de gravar, uma cópia de segurança do arquivo vai para ~/.cerebro/copias.'),
        h('li', null, 'Para desligar: Configurações › Agentes ao vivo instantâneo › Desligar (tira só o que é do Cérebro).')),
      h('div', { class: 'barra' }, h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
        try { const p = await post('/api/ganchos/previa', opcoes); diff.textContent = p.diferenca || 'Nada muda: já está assim.'; diff.hidden = false; } catch (er) { msg.textContent = er.message; }
      } }, 'Ver o que muda'), ligado ? null : bLigar), diff, msg), navegacao('Concluir →'));
  };

  /* ---------- Configurações do projeto: Manual do gestor neste projeto ---------- */
  UI.secoesConfig.push(({ slug, dizer }) => {
    if (!slug) return null;
    const secao = h('section', { class: 'cartao secao' }, h('h3', null, 'Manual do gestor neste projeto'), h('div', { class: 'vazio' }, 'Carregando…'));
    async function carregar() {
      let pv;
      try { pv = await api(base(slug) + '/manual'); } catch (e) { trocar(secao, h('h3', null, 'Manual do gestor neste projeto'), h('div', { class: 'vazio' }, e.message)); return; }
      const ligado = pv.instalado;
      trocar(secao, h('h3', null, 'Manual do gestor neste projeto: ' + (ligado ? 'ligado' : 'desligado')),
        h('p', { class: 'nota' }, 'Liga = um bloco marcado no CLAUDE.local.md do projeto (arquivo local, fora do git) que faz o Claude Code ler o ~/.cerebro/GESTOR.md. Desligar tira só o bloco. Sempre com prévia e cópia de segurança antes.'),
        pv.motivo ? h('p', { class: 'msg-erro' }, pv.motivo) : null,
        h('div', { class: 'linha-cfg' }, h('button', { type: 'button', class: 'bt ' + (ligado ? 'leve' : 'pri') + ' fino', disabled: !pv.aplicavel, onclick: () => confirmar(pv) }, ligado ? 'Desligar…' : 'Ligar…')));
    }
    function confirmar(pv) {
      const status = h('span', { class: 'muted' });
      const j = janela(pv.titulo,
        pv.git && pv.git.repo && !pv.git.ignorado && pv.acao === 'instalar' ? h('div', { class: 'aviso-caixa info' }, 'O git deste projeto ainda não ignora o CLAUDE.local.md: a mesma ação acrescenta a linha no .git/info/exclude (lista de ignorados só deste PC; não vai para o repositório).') : null,
        pv.arquivos.map(a => h('div', null, h('p', null, h('b', null, a.rel), ' — ', a.nota), a.diff ? h('pre', { class: 'saida', estilo: { maxHeight: '300px' } }, a.diff) : null)),
        h('div', { class: 'barra', estilo: { marginTop: '10px' } }, h('button', { type: 'button', class: 'bt pri fino', onclick: async ev => {
          ev.target.disabled = true; status.textContent = 'Gravando…';
          try {
            const r = await post(base(slug) + '/manual', { acao: pv.acao, assinatura: pv.assinatura, confirmar: true });
            j.fechar(); dizer(r.nada_a_fazer ? 'Nada a fazer.' : 'Feito. Cópia de segurança em: ' + r.copia); carregar();
          } catch (e) { status.className = 'msg-erro'; status.textContent = e.message; ev.target.disabled = false; }
        } }, 'Confirmar'), status));
      return j;
    }
    carregar();
    return secao;
  });
})();
