/* Cérebro do Projeto — aba Tarefas (o dono cria, o gestor recebe e entrega), barra de orçamento na aba Custos e
   Configurações › Orçamento. Nada que vem de arquivos ou conversas entra na página como HTML: tudo é criado com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, haQuanto, dataCurta, api, post, cada, tok, usd, lembrar, guardar } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);
  const COR_ESTADO = { nova: 'violet', recebida: 'accent', andamento: 'warn', conferir: 'warn', feita: 'ok', recusada: 'perigo' };
  const ROTULO_ESTADO = { nova: 'nova', recebida: 'recebida pelo gestor', andamento: 'em andamento', conferir: 'a conferir', feita: 'feita', recusada: 'recusada' };
  const COR_PRIO = { baixa: '', normal: '', alta: 'warn', urgente: 'perigo' };
  const ABERTAS = ['nova', 'recebida', 'andamento', 'conferir'];

  function pontoTexto(p) {
    const onde = p.arquivo ? ' · ' + p.arquivo + (p.linha ? ':' + p.linha : '') : '';
    return p.tipo + ' ' + p.nome + onde;
  }

  /* ====================================================================================================== */
  /* Formulário de tarefa (criar e editar)                                                                    */
  /* ====================================================================================================== */
  function formulario(slug, opcoes, inicial, textoBotao, enviar, cancelar) {
    const ini = inicial || {};
    let pontos = (ini.pontos || []).map(p => ({ ...p }));
    const titulo = h('input', { type: 'text', maxlength: 160, value: ini.titulo || '', 'aria-label': 'Título da tarefa', placeholder: 'O que precisa ser feito, numa frase' });
    const descricao = h('textarea', { maxlength: 4000, 'aria-label': 'Descrição', placeholder: 'Explique o que você quer, o que já tentou e como saber que ficou pronto.' }, ini.descricao || '');
    const prioridade = h('select', { 'aria-label': 'Prioridade' }, opcoes.prioridades.map(p => h('option', { value: p, selected: p === (ini.prioridade || 'normal') }, p)));
    const agente = h('select', { 'aria-label': 'Tipo de agente' },
      h('option', { value: '' }, 'Deixar o Cérebro sugerir (pelas palavras do pedido)'),
      opcoes.agentes.map(a => h('option', { value: a.id, selected: a.id === ini.agente_tipo && !ini.agente_sugerido }, a.nome + ' — ' + a.modelo)));
    const infoAgente = h('div', { class: 'tf-agente' });
    const mostrarAgente = () => {
      const a = opcoes.agentes.find(x => x.id === agente.value);
      infoAgente.textContent = a ? 'Modelo: ' + a.modelo + ' · Quem revisa: ' + a.revisor
        : 'Sem escolher, o Cérebro compara o título e a descrição com as palavras-chave da tabela de agentes (Configurações) e mostra o modelo e quem revisa depois de criar.';
    };
    agente.addEventListener('change', mostrarAgente);
    mostrarAgente();

    const chips = h('div', { class: 'tf-pontos' });
    const desenharChips = () => chips.replaceChildren(...pontos.map(p => h('span', { class: 'tf-ponto', title: pontoTexto(p) },
      pontoTexto(p), h('button', { type: 'button', 'aria-label': 'Tirar este ponto', onclick: () => { pontos = pontos.filter(x => x !== p); desenharChips(); } }, '×'))));
    desenharChips();
    const busca = h('input', { type: 'search', placeholder: 'Buscar no mapa: grupo, arquivo ou função', 'aria-label': 'Buscar pontos do mapa', class: 'campo-busca' });
    const achados = h('div', { class: 'tf-achados', hidden: true });
    const aviso = h('div', { class: 'nota' });
    let timer = null, seq = 0;
    async function procurar() {
      const minha = ++seq;
      try {
        const d = await api(base(slug) + '/tarefas-gestor/pontos?q=' + encodeURIComponent(busca.value.trim()));
        if (minha !== seq) return;
        if (!d.mapa) { aviso.textContent = 'Este projeto ainda não tem o mapa gerado. Descreva o lugar no texto da tarefa.'; achados.hidden = true; return; }
        aviso.textContent = busca.value.trim() ? '' : 'Grupos maiores do mapa. Digite para achar arquivos e funções.';
        achados.replaceChildren(...(d.pontos.length ? d.pontos.map(p => h('button', { type: 'button', onclick: () => {
          if (!pontos.some(x => x.tipo === p.tipo && x.nome === p.nome && x.arquivo === p.arquivo)) { pontos.push(p); desenharChips(); }
        } }, h('span', { class: 'chip' }, p.tipo), p.nome, p.arquivo ? h('small', null, p.arquivo + (p.linha ? ':' + p.linha : '')) : null))
          : [h('small', { class: 'muted', estilo: { padding: '6px 10px' } }, 'Nada encontrado.')]));
        achados.hidden = false;
      } catch (e) { aviso.textContent = e.message; }
    }
    busca.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(procurar, 250); });
    busca.addEventListener('focus', () => { if (achados.hidden) procurar(); });
    const msg = h('span', { class: 'msg-erro' });
    const botao = h('button', { type: 'button', class: 'bt pri', onclick: async () => {
      msg.textContent = '';
      if (!titulo.value.trim()) { msg.textContent = 'Escreva o título da tarefa.'; titulo.focus(); return; }
      botao.disabled = true;
      try { await enviar({ titulo: titulo.value, descricao: descricao.value, prioridade: prioridade.value, agente_tipo: agente.value, pontos }); }
      catch (e) { msg.textContent = e.message; botao.disabled = false; }
    } }, textoBotao);
    return h('section', { class: 'cartao tf-form' },
      h('label', null, 'Título', titulo),
      h('label', null, 'Descrição', descricao),
      h('div', { class: 'tf-linha' }, h('label', null, 'Prioridade', prioridade), h('label', null, 'Tipo de agente', agente)),
      infoAgente,
      h('div', null, h('b', null, 'Onde mexer (pontos do mapa)'), h('p', { class: 'nota' }, 'Opcional. Escolha grupos, arquivos ou funções do mapa; o gestor recebe a lista pronta. No mapa, o botão "Criar tarefa aqui" já preenche isto.')),
      chips, busca, achados, aviso,
      h('div', { class: 'acoes-conf' }, botao, cancelar ? h('button', { type: 'button', class: 'bt leve', onclick: cancelar }, 'Cancelar') : null, msg));
  }

  /* ====================================================================================================== */
  /* Aba Tarefas                                                                                             */
  /* ====================================================================================================== */
  UI.telas.tarefas = function abaTarefas(slug, el, info, params) {
    const nomeProjeto = (info && info.nome) || slug;
    let dados = null, filtro = lembrar('tarefas.filtro') || 'abertas', prioFiltro = '', texto = '', editando = null, criando = false, inicialNova = null;
    const topo = h('div'), formCaixa = h('div'), lista = h('div');
    el.replaceChildren(topo, formCaixa, lista);
    const aviso = h('span', { class: 'msg-erro' });

    if (params && params.get('nova')) {
      criando = true;
      try { const p = JSON.parse(params.get('ponto') || 'null'); inicialNova = p ? { pontos: [p] } : null; } catch (e) { inicialNova = null; }
    }

    const passa = t => (filtro === 'todas' || (filtro === 'abertas' ? ABERTAS.includes(t.estado) : t.estado === filtro)) && (!prioFiltro || t.prioridade === prioFiltro)
      && (!texto || (t.titulo + ' ' + t.descricao + ' ' + t.id + ' ' + t.pontos.map(p => p.nome + ' ' + p.arquivo).join(' ')).toLowerCase().includes(texto));

    function desenharTopo() {
      const c = (dados && dados.contagem) || {};
      const chipF = (id, rotulo, n) => h('button', { type: 'button', class: 'chip filtro' + (filtro === id ? ' ativo' : ''),
        onclick: () => { filtro = id; guardar('tarefas.filtro', id); desenharTopo(); desenharLista(); } }, rotulo + (n != null ? ' (' + n + ')' : ''));
      const q = h('input', { type: 'search', class: 'campo-busca', placeholder: 'Buscar tarefa', 'aria-label': 'Buscar tarefa', value: texto, oninput: e => { texto = e.target.value.trim().toLowerCase(); desenharLista(); } });
      const pf = h('select', { 'aria-label': 'Filtrar por prioridade', onchange: e => { prioFiltro = e.target.value; desenharLista(); } },
        h('option', { value: '' }, 'todas as prioridades'), ['urgente', 'alta', 'normal', 'baixa'].map(p => h('option', { value: p, selected: p === prioFiltro }, p)));
      trocar(topo,
        h('div', { class: 'aviso-caixa info', estilo: { marginBottom: '12px' } }, 'Você cria a tarefa aqui (ou no botão "Criar tarefa aqui" do mapa). O gestor recebe as novas no começo da conversa do projeto, ou pelo comando ',
          h('code', null, 'python cerebro_cli.py tarefas "' + nomeProjeto + '" --novas'), '. Ele avisa quando pega, quando está fazendo e quando termina; aí você confere. Nada é escrito dentro do projeto.'),
        h('div', { class: 'tf-barra' },
          h('button', { type: 'button', class: 'bt pri', onclick: () => { criando = !criando; inicialNova = null; desenharForm(); } }, criando ? 'Fechar o formulário' : 'Nova tarefa'),
          h('div', { class: 'tf-filtros' }, chipF('abertas', 'abertas', c.abertas), chipF('nova', 'novas', c.nova), chipF('andamento', 'em andamento', c.andamento),
            chipF('conferir', 'a conferir', c.conferir), chipF('feita', 'feitas', c.feita), chipF('recusada', 'recusadas', c.recusada), chipF('todas', 'todas')),
          pf, q, aviso));
    }

    function desenharForm() {
      formCaixa.replaceChildren();
      desenharTopo();
      if (!criando || !dados) return;
      formCaixa.append(formulario(slug, dados.opcoes, inicialNova, 'Criar tarefa', async corpo => {
        await post(base(slug) + '/tarefas-gestor', corpo);
        criando = false; inicialNova = null;
        filtro = 'abertas';
        desenharForm(); await carregar();
      }, () => { criando = false; desenharForm(); }));
    }

    async function mudar(t, corpo) {
      aviso.textContent = '';
      try { await post(base(slug) + '/tarefas-gestor/' + encodeURIComponent(t.id), corpo); await carregar(); }
      catch (e) { aviso.textContent = e.message; }
    }

    function cartao(t) {
      const nota = h('input', { type: 'text', maxlength: 500, placeholder: 'Nota (opcional)', 'aria-label': 'Nota da mudança' });
      const bt = (rotulo, estado, cls) => h('button', { type: 'button', class: 'bt fino ' + (cls || 'leve'), onclick: () => mudar(t, { acao: 'estado', estado, nota: nota.value }) }, rotulo);
      let acoes;
      if (t.estado === 'conferir') acoes = [bt('Conferido: feita', 'feita', 'pri'), bt('Devolver ao gestor', 'nova'), bt('Recusar', 'recusada')];
      else if (ABERTAS.includes(t.estado)) acoes = [h('button', { type: 'button', class: 'bt leve fino', onclick: () => { editando = t.id; desenharLista(); } }, 'Editar'),
        bt('Marcar como feita', 'feita'), bt('Recusar', 'recusada')];
      else acoes = [bt('Reabrir', 'nova')];
      const ag = t.agente;
      return h('article', { class: 'tf-card' + (t.prioridade === 'urgente' && ABERTAS.includes(t.estado) ? ' urgente' : '') + (ABERTAS.includes(t.estado) ? '' : ' final') },
        h('div', { class: 'topo-conf' }, h('b', { class: 'tit-conf' }, t.titulo),
          h('span', { class: 'chip ' + (COR_ESTADO[t.estado] || '') }, ROTULO_ESTADO[t.estado] || t.estado),
          t.prioridade !== 'normal' ? h('span', { class: 'chip ' + (COR_PRIO[t.prioridade] || '') }, 'prioridade ' + t.prioridade) : null,
          t.da_proposta ? h('span', { class: 'chip', title: 'nasceu de uma proposta que você aprovou na aba Análise' }, 'veio de proposta') : null,
          h('span', { class: 'muted' }, t.id)),
        t.descricao ? h('p', { class: 'tf-desc' }, t.descricao) : null,
        t.pontos.length ? h('div', { class: 'tf-pontos', estilo: { marginTop: '8px' } }, t.pontos.map(p => h('span', { class: 'tf-ponto', title: (p.arquivos || []).join('\n') || pontoTexto(p) }, pontoTexto(p)))) : null,
        h('div', { class: 'linha', estilo: { marginTop: '8px' } },
          ag ? h('span', { class: 'chip accent', title: 'Quem revisa: ' + ag.revisor }, ag.nome.split(/[:,]/)[0].trim() + ' → ' + ag.modelo) : h('span', { class: 'chip' }, 'sem tipo de agente'),
          ag ? h('span', { class: 'muted' }, 'revisa: ' + ag.revisor + ' ·') : null,
          t.agente_atual ? h('span', { class: 'chip ok', title: 'agente ou sessão que está com a tarefa' }, 'com: ' + t.agente_atual) : null,
          h('span', { class: 'muted' }, 'criada ' + haQuanto(t.criada_em) + ' · mexida ' + haQuanto(t.atualizada_em))),
        h('div', { class: 'acoes-conf' }, nota, acoes),
        h('details', null, h('summary', null, 'Histórico (' + t.historico.length + ')'),
          h('ul', { class: 'tf-hist' }, t.historico.slice().reverse().map(x => h('li', null, dataCurta(x.em) + ' · ', h('b', null, x.por || '?'), ' · ' + (x.de && x.de !== x.para ? (ROTULO_ESTADO[x.de] || x.de) + ' → ' : '') + (ROTULO_ESTADO[x.para] || x.para)
            + (x.agente ? ' · agente ' + x.agente : '') + (x.nota ? ' · ' + x.nota : ''))))));
    }

    function desenharLista() {
      if (!dados) { lista.replaceChildren(h('div', { class: 'vazio' }, 'Carregando…')); return; }
      const itens = dados.itens.filter(passa);
      lista.replaceChildren(...(itens.length ? itens.map(t => editando === t.id ? h('div', null, formulario(slug, dados.opcoes, t, 'Salvar', async corpo => {
        await post(base(slug) + '/tarefas-gestor/' + encodeURIComponent(t.id), { acao: 'editar', ...corpo });
        editando = null; await carregar();
      }, () => { editando = null; desenharLista(); })) : cartao(t))
        : [h('div', { class: 'vazio cartao' }, dados.itens.length ? 'Nenhuma tarefa neste filtro.' : 'Nenhuma tarefa ainda. Clique em "Nova tarefa".')]));
    }

    async function carregar() {
      try { dados = await api(base(slug) + '/tarefas-gestor'); aviso.textContent = ''; }
      catch (e) { lista.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      desenharTopo();
      desenharLista();
    }
    desenharTopo();
    desenharLista();
    carregar().then(() => { if (criando) desenharForm(); });
    cada(10000, () => { if (!editando && !criando) carregar(); });
  };

  /* ====================================================================================================== */
  /* Orçamento: barra de uso na aba Custos                                                                   */
  /* ====================================================================================================== */
  const NIVEL_ROTULO = { ok: 'dentro do limite', atencao: 'perto do limite', estourou: 'estourou', sem_limite: 'sem limite' };
  const NIVEL_COR = { ok: 'ok', atencao: 'warn', estourou: 'perigo', sem_limite: '' };
  const PERIODO_ROTULO = { dia: 'Hoje', semana: 'Esta semana', mes: 'Este mês' };

  function blocoOrcamento(titulo, b) {
    const linhas = ['dia', 'semana', 'mes'].map(p => {
      const d = b.periodos[p];
      const uso = usd(d.gasto) + (d.sem_preco ? '*' : '') + ' · ' + tok(d.tokens) + ' tokens';
      if (!d.limite) return h('div', { class: 'orc-linha' }, h('span', null, PERIODO_ROTULO[p]), h('span', { class: 'txt' }, uso + ' · sem limite'));
      return h('div', { class: 'orc-linha' }, h('span', null, PERIODO_ROTULO[p]),
        h('div', null, h('div', { class: 'prog', role: 'progressbar', 'aria-valuenow': Math.round(d.pct), 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': PERIODO_ROTULO[p] + ': ' + Math.round(d.pct) + '% do limite' },
          h('i', { class: d.nivel, estilo: { width: Math.min(100, d.pct) + '%' } })),
          h('span', { class: 'txt' }, uso + ' de ' + usd(d.limite) + ' (' + Math.round(d.pct) + '%) · ' + (d.nivel === 'estourou' ? 'passou do limite' : 'faltam ' + usd(d.falta)))));
    });
    const pj = b.projecao_mes;
    return h('div', { class: 'orc-bloco' },
      h('h4', null, titulo + ' ', b.tem_limite ? h('span', { class: 'chip ' + NIVEL_COR[b.nivel] }, NIVEL_ROTULO[b.nivel] + (b.nivel === 'atencao' ? ' (aviso a partir de ' + b.aviso_pct + '%)' : '')) : h('span', { class: 'chip' }, 'sem limite')),
      linhas,
      h('p', { class: 'nota' }, 'Pelo ritmo atual (' + pj.dias_decorridos + ' de ' + pj.dias_no_mes + ' dias do mês), o mês fecha em ' + usd(pj.valor)
        + (b.limites.mes ? ' · limite do mês ' + usd(b.limites.mes) + (pj.vai_passar ? ' — VAI PASSAR do limite se o ritmo continuar' : '') : '') + '.'));
  }

  UI.cartaoOrcamento = function cartaoOrcamento(slug) {
    const caixa = h('section', { class: 'cartao', estilo: { marginBottom: '14px' } }, h('h3', null, 'Orçamento'), h('div', { class: 'vazio' }, 'Calculando…'));
    api(base(slug) + '/orcamento').then(d => {
      const p = d.projeto, g = d.geral;
      const semNada = !(p && p.tem_limite) && !g.tem_limite;
      trocar(caixa, h('div', { class: 'barra', estilo: { justifyContent: 'space-between', marginBottom: '0' } }, h('h3', null, 'Orçamento'),
        h('a', { class: 'bt leve fino', href: '#/p/' + encodeURIComponent(slug) + '/configuracoes' }, semNada ? 'Definir orçamento' : 'Mudar limites')),
        semNada ? h('p', { class: 'muted' }, 'Nenhum limite definido. Defina quanto quer gastar por dia, semana ou mês e o Cérebro avisa em "Precisa de você" quando chegar perto. Uso do período: '
          + (p ? usd(p.periodos.dia.gasto) + ' hoje · ' + usd(p.periodos.semana.gasto) + ' na semana · ' + usd(p.periodos.mes.gasto) + ' no mês' : '—') + '.') : null,
        p && p.tem_limite ? blocoOrcamento('Este projeto', p) : null,
        g.tem_limite ? blocoOrcamento('Todos os projetos', g) : null,
        h('p', { class: 'nota' }, d.estimativa + ' * = parte do uso é de modelo sem preço na tabela, então o valor real pode ser maior.'));
    }).catch(e => trocar(caixa, h('h3', null, 'Orçamento'), h('div', { class: 'vazio' }, e.message)));
    return caixa;
  };

  /* ====================================================================================================== */
  /* Configurações › Orçamento                                                                               */
  /* ====================================================================================================== */
  UI.secoesConfig.push(({ slug, dizer }) => {
    const secao = h('section', { class: 'cartao secao rolagem-x' }, h('h3', null, 'Orçamento de gasto'), h('div', { class: 'vazio' }, 'Carregando…'));
    const numero = v => {
      const t = String(v).trim();
      if (!t) return null;
      const n = Number(t.replace(',', '.'));
      if (!isFinite(n) || n < 0) throw new Error('Número inválido: ' + t);
      return n;
    };
    function linha(rotulo, escopo, b) {
      const campo = (periodo, rot) => h('input', { type: 'text', inputmode: 'decimal', value: b.limites[periodo] == null ? '' : String(b.limites[periodo]).replace('.', ','),
        placeholder: 'sem limite', 'aria-label': rotulo + ': limite ' + rot + ' em dólares' });
      const dia = campo('dia', 'por dia'), semana = campo('semana', 'por semana'), mes = campo('mes', 'por mês');
      const aviso = h('input', { type: 'text', inputmode: 'numeric', class: 'aviso', value: String(b.aviso_pct), 'aria-label': rotulo + ': percentual de aviso' });
      const m = b.periodos.mes;
      return h('tr', null, h('td', { class: 'tit', title: rotulo }, rotulo), h('td', null, dia), h('td', null, semana), h('td', null, mes), h('td', null, aviso),
        h('td', { class: 'n' }, usd(m.gasto) + ' ', b.tem_limite ? h('span', { class: 'chip ' + NIVEL_COR[b.nivel] }, NIVEL_ROTULO[b.nivel]) : null),
        h('td', null, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          try {
            const pct = parseInt(aviso.value, 10);
            await post('/api/orcamento', { escopo, dia: numero(dia.value), semana: numero(semana.value), mes: numero(mes.value), aviso_pct: Number.isFinite(pct) ? pct : 80 });
            dizer('Orçamento salvo.'); carregar();
          } catch (e) { dizer(e.message, false); }
        } }, 'Salvar')));
    }
    function carregar() {
      api('/api/orcamento').then(d => {
        const projs = d.projetos.filter(p => (slug ? p.slug === slug : !p.oculto));
        trocar(secao, h('h3', null, 'Orçamento de gasto'),
          h('div', { class: 'aviso-caixa info' }, 'É uma ESTIMATIVA pelo preço de lista. Quem usa plano por assinatura não paga por token: use o valor em dólar como régua de uso (os tokens aparecem na aba Custos). Deixe em branco para não ter limite.'),
          h('table', { class: 'tabela orc-tabela' }, h('thead', null, h('tr', null, ['Onde vale', 'Por dia (US$)', 'Por semana (US$)', 'Por mês (US$)', 'Avisar em (%)', 'Uso no mês', ''].map((t, i) => h('th', { class: i === 5 ? 'n' : '' }, t)))),
            h('tbody', null, linha('Todos os projetos', 'geral', d.geral), projs.map(p => linha(p.nome, p.slug, p)))),
          h('p', { class: 'nota' }, 'Dia e mês seguem o calendário do seu PC; a semana começa na segunda. O aviso começa em ' + d.aviso_padrao + '% do limite (padrão) e vira "estourou" em 100%. Os avisos aparecem em "Precisa de você" na tela inicial e na aba Custos do projeto. O Cérebro só avisa: nada é bloqueado.'));
      }).catch(e => trocar(secao, h('h3', null, 'Orçamento de gasto'), h('div', { class: 'vazio' }, e.message)));
    }
    carregar();
    return secao;
  });
})();
