/* Cérebro do Projeto — cartão "Explicar pontos do mapa com IA" (fica na aba Mapa, acima do desenho).
   Nada roda sozinho: o cartão só mostra a ESTIMATIVA; gastar tokens exige o clique em "Explicar". Tudo é criado com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, num, tok, api, post, cada } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug) + '/explicar';

  function cartao(slug, aoTerminar) {
    const detalhes = h('details', { class: 'cartao', estilo: { marginBottom: '10px' } },
      h('summary', null, 'Explicar pontos do mapa com IA (opcional, gasta tokens só quando você clica)'));
    const corpo = h('div', { estilo: { marginTop: '10px' } }, h('div', { class: 'vazio' }, 'Abra para ver a estimativa.'));
    detalhes.append(corpo);
    let limite = Number(UI.lembrar('explicar.limite')) || 200;
    let via = 'claude';
    let timer = null, carregou = false, estavaRodando = false;

    function parou() { if (timer) { clearInterval(timer); timer = null; } }
    function vigiar() { if (!timer) timer = cada(1000, atualizarRodada); }

    async function atualizarRodada() {
      try {
        const d = await api(base(slug) + '/estado');
        desenharRodada(d.rodada);
        if (!d.rodada.rodando) {
          parou();
          if (estavaRodando) { estavaRodando = false; if (aoTerminar) setTimeout(aoTerminar, 600); }
        }
      } catch (e) { /* sessão expirada já avisa */ }
    }

    const areaRodada = h('div');

    function desenharRodada(r) {
      const res = r && r.resumo;
      if (!r || (!r.rodando && !res)) { areaRodada.replaceChildren(); return; }
      const total = res ? res.pedidos : r.limite;
      const feitos = res ? res.explicados + res.sem_resposta : 0;
      const pct = total ? Math.min(100, Math.round(100 * feitos / total)) : 0;
      const linhas = [];
      if (r.rodando) linhas.push(h('b', null, r.parando ? 'Parando depois do lote atual…' : 'Explicando… ' + feitos + ' de ' + total + ' pontos'));
      else if (res) linhas.push(h('b', null, res.parado ? 'Parou: ' : 'Terminou: '), res.explicados + ' pontos explicados' + (res.sem_resposta ? ', ' + res.sem_resposta + ' sem resposta (tente de novo depois)' : '') + '.');
      if (res && res.erro) linhas.push(h('div', { class: 'aviso-caixa', estilo: { marginTop: '6px' } }, res.erro));
      if (res && (res.tokens_entrada || res.tokens_saida)) linhas.push(h('p', { class: 'nota' }, 'Gasto medido: ' + tok(res.tokens_entrada) + ' tokens de entrada e ' + tok(res.tokens_saida) + ' de saída.'));
      areaRodada.replaceChildren(
        h('div', { class: 'barra-ctx', role: 'progressbar', 'aria-valuenow': String(pct), 'aria-valuemin': '0', 'aria-valuemax': '100' }, h('i', { estilo: { width: pct + '%' } })),
        linhas);
      if (r.rodando) estavaRodando = true;
    }

    async function carregar() {
      let d;
      try { d = await api(base(slug) + '?limite=' + encodeURIComponent(limite) + '&via=' + via); } catch (e) { corpo.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const e = d.estimativa, rodando = d.rodada && d.rodada.rodando;
      const campo = h('input', { type: 'number', min: 1, max: 5000, value: String(limite), 'aria-label': 'Quantos pontos explicar nesta rodada', estilo: { width: '90px' },
        onchange: () => { limite = Math.max(1, Math.min(5000, parseInt(campo.value, 10) || 200)); UI.guardar('explicar.limite', String(limite)); carregar(); } });
      const escolha = h('select', { 'aria-label': 'De onde vêm os tokens', onchange: () => { via = escolha.value; carregar(); } },
        h('option', { value: 'claude' }, 'Pelo meu plano do Claude (assinatura)'),
        h('option', { value: 'api', disabled: !e.tem_chave_api }, e.tem_chave_api ? 'Pela API (chave encontrada; cobrado por uso)' : 'Pela API (sem ANTHROPIC_API_KEY neste PC)'));
      escolha.value = via;
      const botao = h('button', { type: 'button', class: 'bt pri fino', disabled: rodando || !e.nesta_rodada || (via === 'claude' && !e.claude_encontrado), onclick: async () => {
        botao.disabled = true;
        try { const r = await post(base(slug) + '/rodar', { limite, via }); desenharRodada(r.rodada); vigiar(); } catch (er) { areaRodada.replaceChildren(h('div', { class: 'aviso-caixa' }, er.message)); botao.disabled = false; }
      } }, 'Explicar ' + num(e.nesta_rodada) + (e.nesta_rodada === 1 ? ' ponto' : ' pontos'));
      const parar = h('button', { type: 'button', class: 'bt leve fino', disabled: !rodando, onclick: async () => { parar.disabled = true; try { await post(base(slug) + '/parar'); } catch (er) { /* já terminou */ } } }, 'Parar');
      corpo.replaceChildren(
        h('p', { class: 'nota' }, 'Um modelo barato (Haiku) escreve UMA frase simples para cada ponto do mapa que não tem texto no código. Só vão para a IA o nome, o arquivo, os vizinhos e as primeiras linhas do ponto (segredos mascarados; arquivos como .env e chaves nunca vão). Tudo aparece no painel do mapa marcado como "' + e.rotulo + '". Nada roda sozinho.'),
        h('ul', { class: 'lista-simples' },
          h('li', null, num(e.sem_texto) + ' pontos sem texto no código · ' + num(e.ja_explicados) + ' já explicados · ' + num(e.desatualizados) + ' desatualizados (o código mudou) · ' + num(e.pulados_sensiveis) + ' pulados por segurança.'),
          h('li', null, 'Esta rodada: ' + num(e.nesta_rodada) + ' pontos em ' + num(e.lotes) + ' chamadas de até ' + e.pontos_por_lote + ', cerca de ' + tok(e.tokens_total) + ' tokens (' + tok(e.tokens_entrada) + ' de entrada + ' + tok(e.tokens_saida) + ' de saída). Faltam ' + num(e.faltam) + ' no total.')),
        h('p', { class: 'nota' }, e.aviso + (via === 'claude' && !e.claude_encontrado ? ' (O programa claude não foi encontrado neste PC.)' : '')),
        h('div', { class: 'barra' }, h('label', null, 'Até ', campo, ' pontos por clique '), escolha, h('span', { class: 'espaco' }), parar, botao),
        areaRodada);
      desenharRodada(d.rodada);
      if (rodando) vigiar();
    }

    detalhes.addEventListener('toggle', () => { if (detalhes.open && !carregou) { carregou = true; carregar(); } });
    api(base(slug) + '/estado').then(d => { if (d.rodada && d.rodada.rodando) { detalhes.open = true; } }).catch(() => {});
    return detalhes;
  }

  window.CerebroExplicar = { cartao };
})();
