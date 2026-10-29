/* Cérebro do Projeto — Configurações › "Agentes ao vivo instantâneo" (ganchos do Claude Code + statusLine) e "Avisos no Windows".
   Nada é gravado no settings.json do Claude Code sem: 1) ver o que muda; 2) clicar em Ligar/Desligar e confirmar.
   Tudo na tela é criado com h()/textContent (nunca HTML com dado). */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, api, post, haQuanto } = UI;

  /* ---------- Agentes ao vivo instantâneo ---------- */
  UI.secoesConfig.push(({ dizer }) => {
    const titulo = () => h('h3', null, 'Agentes ao vivo instantâneo (ganchos do Claude Code) e anéis de limite');
    const secao = h('section', { class: 'cartao secao' }, titulo(), h('div', { class: 'vazio' }, 'Carregando…'));
    const diff = h('pre', { class: 'saida pequeno', hidden: true });
    let modo = 'comando', st = '', confirmando = null;

    async function desenhar() {
      let e;
      try { e = await api('/api/ganchos/estado'); } catch (er) { secao.replaceChildren(titulo(), h('div', { class: 'vazio' }, er.message)); return; }
      const ligado = e.eventos.length > 0;
      const rec = e.eventos_recebidos || {};
      const estado = h('div', { class: 'linha-cfg' },
        h('span', { class: 'chip ' + (ligado ? 'ok' : '') }, ligado ? 'ganchos ligados' : 'ganchos desligados'),
        ligado && e.modo ? h('span', { class: 'chip' }, 'modo ' + e.modo) : null,
        h('span', { class: 'chip ' + (e.statusline === 'cerebro' ? 'ok' : '') }, e.statusline === 'cerebro' ? ('statusLine do Cérebro' + (e.statusline_encadeada ? ' (encadeada com a sua)' : ''))
          : e.statusline === 'outra' ? 'você tem outra statusLine' : 'sem statusLine'),
        h('span', { class: 'muted' }, rec.ultimo_evento ? 'último evento recebido ' + haQuanto(rec.ultimo_evento) : 'nenhum evento recebido desde que o Cérebro abriu'));
      const avisos = [];
      if (!e.valido) avisos.push(h('p', { class: 'msg-erro' }, e.erro));
      if (e.precisa_reinstalar) avisos.push(h('p', { class: 'msg-erro' }, 'Os ganchos apontam para a porta ' + e.porta_instalada + ', mas a porta configurada é ' + e.porta_config + '. Desligue e ligue de novo.'));
      if (e.incompleto && e.incompleto.length) avisos.push(h('p', { class: 'nota' }, 'Faltam ganchos para: ' + e.incompleto.join(', ') + '. Ligar de novo completa.'));
      const selModo = h('select', { 'aria-label': 'Modo dos ganchos', onchange: ev => { modo = ev.target.value; diff.hidden = true; } },
        h('option', { value: 'comando', selected: modo === 'comando' }, 'Seguro: nunca atrasa o Claude Code (recomendado)'),
        h('option', { value: 'http', selected: modo === 'http' }, 'Direto (http): mais leve, mas atrasa ~2 s por evento com o Cérebro fechado'));
      const selSt = h('select', { 'aria-label': 'statusLine', onchange: ev => { st = ev.target.value; diff.hidden = true; } },
        h('option', { value: '' }, 'Não mexer na statusLine'),
        e.statusline === 'outra' ? null : h('option', { value: 'instalar', selected: st === 'instalar' }, 'Instalar a statusLine do Cérebro (anéis 5 h / semana)'),
        e.statusline === 'outra' ? h('option', { value: 'encadear', selected: st === 'encadear' }, 'Encadear: o Cérebro chama a sua statusLine e mostra a saída dela') : null,
        e.statusline === 'outra' ? h('option', { value: 'substituir', selected: st === 'substituir' }, 'Substituir a sua pela do Cérebro (dá para desfazer)') : null);
      const opcoes = () => ({ hooks: true, modo, statusline: st || null });
      const bVer = h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
        try {
          const p = await post('/api/ganchos/previa', opcoes());
          diff.textContent = (p.precisa_decidir ? 'Você já tem uma statusLine: escolha encadear ou substituir.\n\n' : '') + (p.diferenca || 'Nada muda: já está assim.');
          diff.hidden = false;
        } catch (er) { dizer(er.message, false); }
      } }, 'Ver o que muda');
      const bLigar = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
        if (confirmando !== 'ligar') { confirmando = 'ligar'; bLigar.textContent = 'Clique de novo para gravar no settings.json'; setTimeout(() => { confirmando = null; bLigar.textContent = 'Ligar'; }, 5000); return; }
        try {
          const r = await post('/api/ganchos/instalar', { ...opcoes(), confirmar: true });
          dizer(r.mudou ? 'Ligado. Cópia de segurança: ' + (r.copia || '(o arquivo não existia)') : 'Já estava ligado assim.');
          desenhar();
        } catch (er) { dizer(er.message, false); confirmando = null; bLigar.textContent = 'Ligar'; }
      } }, 'Ligar');
      const bDesligar = h('button', { type: 'button', class: 'bt perigo fino', onclick: async () => {
        if (confirmando !== 'desligar') { confirmando = 'desligar'; bDesligar.textContent = 'Clique de novo para desligar'; setTimeout(() => { confirmando = null; bDesligar.textContent = 'Desligar'; }, 5000); return; }
        try {
          const r = await post('/api/ganchos/remover', { confirmar: true, hooks: true, statusline: true });
          dizer(r.mudou ? 'Desligado (só o que era do Cérebro saiu). Cópia de segurança: ' + r.copia : 'Nada do Cérebro estava instalado.');
          desenhar();
        } catch (er) { dizer(er.message, false); }
      } }, 'Desligar');
      secao.replaceChildren(titulo(),
        h('p', { class: 'nota' }, 'Sem isto, a aba "Agentes ao vivo" descobre o que está acontecendo lendo os arquivos das conversas (alguns segundos de atraso). '
          + 'Ligando, o próprio Claude Code avisa o Cérebro na hora: subagente começou ou terminou, ferramenta em uso, sessão parou, pedido de permissão. '
          + 'A statusLine grava os seus limites de 5 horas e da semana para os anéis do topo.'),
        estado, avisos,
        h('div', { class: 'linha-cfg' }, h('label', null, 'Jeito: '), selModo),
        h('div', { class: 'linha-cfg' }, h('label', null, 'statusLine: '), selSt),
        h('div', { class: 'linha-cfg' }, bVer, bLigar, ligado || e.statusline === 'cerebro' ? bDesligar : null),
        diff,
        h('p', { class: 'nota' }, 'Grava em ' + e.arquivo + ' só quando você confirma: guarda uma cópia antes, mantém tudo o que já existe (outros ganchos, permissões, env) e só acrescenta as linhas do Cérebro. '
          + 'Desligar tira só essas linhas. Com o Cérebro fechado, os ganchos não fazem nada e o Claude Code segue normal.'));
    }
    desenhar();
    return secao;
  });

  /* ---------- Avisos no Windows ---------- */
  UI.secoesConfig.push(({ dizer }) => {
    const titulo = () => h('h3', null, 'Avisos no Windows');
    const secao = h('section', { class: 'cartao secao' }, titulo(), h('div', { class: 'vazio' }, 'Carregando…'));
    async function desenhar() {
      let d;
      try { d = await api('/api/avisos'); } catch (er) { secao.replaceChildren(titulo(), h('div', { class: 'vazio' }, er.message)); return; }
      const p = d.preferencias;
      const geral = h('input', { type: 'checkbox', checked: p.ligado });
      const tipos = Object.entries(d.tipos).map(([k, rotulo]) => { const i = h('input', { type: 'checkbox', checked: p.tipos[k] !== false }); i.dataset.tipo = k; return h('label', { class: 'chk' }, i, rotulo); });
      const repetir = h('input', { type: 'number', min: 1, max: 1440, value: p.repetir_minutos, 'aria-label': 'Minutos sem repetir' });
      const parou = h('input', { type: 'number', min: 1, max: 600, value: p.parou_apos_minutos, 'aria-label': 'Minutos de trabalho' });
      const npLigado = h('input', { type: 'checkbox', checked: p.nao_perturbe.ligado });
      const npIni = h('input', { type: 'time', value: p.nao_perturbe.inicio, 'aria-label': 'Início do não perturbe' });
      const npFim = h('input', { type: 'time', value: p.nao_perturbe.fim, 'aria-label': 'Fim do não perturbe' });
      const hist = h('div', null, (d.historico || []).slice(0, 6).map(a => h('div', { class: 'muted' }, haQuanto(a.em) + ' · ' + a.titulo + ' · ' + a.resultado)));
      secao.replaceChildren(titulo(),
        h('p', { class: 'nota' }, 'Uma notificação do Windows quando um subagente da gestora termina, quando o Claude Code precisa de você e quando uma sessão para depois de trabalhar um tempo. '
          + 'Precisa dos ganchos ligados (seção acima). ' + (d.windows ? '' : 'Este computador não é Windows: os avisos só ficam registrados.')),
        h('div', { class: 'linha-cfg' }, h('label', { class: 'chk' }, geral, 'Avisos ligados')),
        h('div', { class: 'linha-cfg' }, tipos),
        h('div', { class: 'linha-cfg' }, h('label', null, 'Não repetir o mesmo aviso por ', repetir, ' min'), h('label', null, 'Avisar que a sessão parou se ela trabalhou mais de ', parou, ' min')),
        h('div', { class: 'linha-cfg' }, h('label', { class: 'chk' }, npLigado, 'Não perturbe das'), npIni, h('span', null, 'às'), npFim),
        h('div', { class: 'linha-cfg' },
          h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
            try {
              const t = {}; tipos.forEach(l => { const i = l.querySelector('input'); t[i.dataset.tipo] = i.checked; });
              await post('/api/avisos', { ligado: geral.checked, tipos: t, repetir_minutos: parseInt(repetir.value, 10), parou_apos_minutos: parseInt(parou.value, 10),
                nao_perturbe: { ligado: npLigado.checked, inicio: npIni.value, fim: npFim.value } });
              dizer('Avisos salvos.');
            } catch (er) { dizer(er.message, false); }
          } }, 'Salvar'),
          h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
            try {
              const r = await post('/api/avisos/testar');
              const txt = { mostrado: 'Aviso de teste enviado: deve aparecer no canto da tela.', desligado: 'Os avisos (ou os avisos gerais) estão desligados.', nao_perturbe: 'Agora é horário de não perturbe: o aviso só foi registrado.', sem_windows: 'Fora do Windows: só registrado.' };
              dizer(txt[r.resultado] || ('Resultado: ' + r.resultado), r.resultado === 'mostrado'); desenhar();
            } catch (er) { dizer(er.message, false); }
          } }, 'Testar aviso')),
        hist.childNodes.length ? h('div', null, h('p', { class: 'nota' }, 'Últimos avisos:'), hist) : null);
    }
    desenhar();
    return secao;
  });
})();
