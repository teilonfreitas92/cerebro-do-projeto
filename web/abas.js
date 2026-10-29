/* Cérebro do Projeto — abas A conferir, Ferramentas, Análise e Novidades (JS puro, sem build).
   Nada que vem de arquivos, conversas ou da internet entra na página como HTML: tudo é criado com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, num, tok, usd, haQuanto, dataCurta, modeloCurto, api, post, cada } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);
  const duracao = s => (s == null ? '' : s < 90 ? Math.round(s) + ' s' : Math.round(s / 60) + ' min');
  const futuro = t => {
    if (!t) return '';
    const d = t - Date.now() / 1000;
    if (d <= 0) return 'agora (na próxima rodada do servidor)';
    if (d < 3600) return 'em ' + Math.round(d / 60) + ' min';
    if (d < 86400) return 'em ' + Math.round(d / 3600) + ' h';
    return 'em ' + Math.round(d / 86400) + ' d';
  };
  const corResultado = r => (r === 'ok' || r === 'aprovado' ? 'ok' : r === 'falha' || r === 'recusado' || r === 'erro' || r === 'tempo' ? 'perigo' : r === 'rodando' || r === 'corrigido' ? 'warn' : '');
  const nomeResultado = { ok: 'passou', falha: 'falhou', tempo: 'passou do tempo', erro: 'não iniciou', rodando: 'rodando…' };

  /* ====================================================================================================== */
  /* A conferir                                                                                              */
  /* ====================================================================================================== */
  UI.telas.conferir = function abaConferir(slug, el) {
    const notas = {};            // o que a pessoa já digitou, para o recarregamento não apagar
    let confirmando = false;
    el.append(h('div', { class: 'vazio' }, 'Carregando a fila…'));
    async function marcar(id, resultado, aviso) {
      aviso.textContent = '';
      try { await post(base(slug) + '/conferir', { ref: id, resultado, nota: notas[id] || '' }); delete notas[id]; carregar(true); }
      catch (e) { aviso.className = 'msg-erro'; aviso.textContent = e.message; }
    }
    function linhaPendente(it) {
      const aviso = h('span', { class: 'muted' });
      const nota = h('input', { type: 'text', maxlength: 1000, value: notas[it.id] || '', placeholder: 'Nota (opcional): o que você conferiu ou corrigiu', 'aria-label': 'Nota da conferência',
        oninput: e => { notas[it.id] = e.target.value; } });
      const r = it.regra || {};
      return h('div', { class: 'item-conf' + (it.parado ? ' parado' : '') },
        h('div', { class: 'topo-conf' },
          h('b', { class: 'tit-conf', title: it.descricao }, it.descricao),
          it.modelo ? h('span', { class: 'chip' }, modeloCurto(it.modelo)) : null,
          it.parado ? h('span', { class: 'chip perigo', title: 'terminou há mais de 24 h e ainda não foi conferido' }, 'parado') : null,
          h('span', { class: 'muted' }, 'terminou ' + haQuanto(it.terminou_em)),
          it.tokens ? h('span', { class: 'chip' }, tok(it.tokens) + ' tokens') : null, it.custo != null && it.tokens ? h('span', { class: 'chip' }, usd(it.custo)) : null,
          h('a', { class: 'bt leve fino', href: '#/p/' + encodeURIComponent(slug) + '/agentes?a=' + encodeURIComponent(it.rel) }, 'Passo a passo')),
        r.regra ? h('div', { class: 'regra muted' }, 'Regra: ' + r.regra_nome + ' → previsto ' + r.modelo_previsto + (r.situacao === 'abaixo' ? ' · usou modelo MENOR: conferir com mais cuidado' : r.situacao === 'acima' ? ' · usou modelo MAIOR que o previsto' : '')
          + ' · revisor: ' + r.revisor) : null,
        h('div', { class: 'acoes-conf' }, nota,
          h('button', { type: 'button', class: 'bt pri fino', title: 'serviu como veio (conta como aprovado de primeira)', onclick: () => marcar(it.id, 'aprovado', aviso) }, 'Aprovado'),
          h('button', { type: 'button', class: 'bt leve fino', title: 'o gestor corrigiu ou refez parte', onclick: () => marcar(it.id, 'corrigido', aviso) }, 'Corrigido'),
          h('button', { type: 'button', class: 'bt perigo fino', title: 'não serviu', onclick: () => marcar(it.id, 'recusado', aviso) }, 'Recusado'), aviso));
    }
    async function carregar(forcar) {
      if (!forcar && (document.activeElement && el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT' || Object.values(notas).some(Boolean))) return;
      let d;
      try { d = await api(base(slug) + '/conferir'); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const c = d.contadores;
      const caixa = (v, r, cls) => h('div', { class: 'num ' + (cls || '') }, h('b', null, v), h('small', null, r));
      const maxTotal = Math.max(1, ...d.por_modelo.map(m => m.total));
      const dispensar = h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
        if (!confirmando) { confirmando = true; dispensar.textContent = 'Clique de novo para dispensar os ' + d.antigos; setTimeout(() => { confirmando = false; dispensar.textContent = 'Dispensar os ' + d.antigos + ' antigos'; }, 4000); return; }
        try { await post(base(slug) + '/conferir', { dispensar_antigos: true }); carregar(true); } catch (e) { dispensar.textContent = e.message; }
      } }, 'Dispensar os ' + d.antigos + ' antigos');
      trocar(el,
        !d.gestora ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '14px' } }, 'Este projeto não tem sessão gestora escolhida: sem ela não há como saber quais subagentes são "dela". ',
          h('a', { href: '#/p/' + encodeURIComponent(slug) + '/configuracoes' }, 'Escolher a gestora')) : null,
        h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'Todo subagente que terminou na sessão gestora espera aqui até o gestor conferir (diff, testes, fotos). Qualidade acima de economia: delegar não dispensa a verificação. O gestor também marca pela linha de comando: ',
          h('code', null, 'python cerebro_cli.py conferir <projeto> <id> --resultado aprovado')),
        h('div', { class: 'grade estreita', estilo: { marginBottom: '14px' } },
          caixa(num(c.a_conferir), 'a conferir', c.a_conferir ? 'destaque' : ''), caixa(num(c.parados), 'parados há mais de 24 h', c.parados ? 'destaque perigo' : ''),
          caixa(num(c.conferidos), 'conferidos'), caixa(num(c.aprovados), 'aprovados'), caixa(num(c.corrigidos), 'corrigidos'), caixa(num(c.recusados), 'recusados')),
        h('div', { class: 'duas' },
          h('section', { class: 'cartao' }, h('h3', null, 'Aprovado de primeira, por modelo'),
            d.por_modelo.length ? h('div', null, d.por_modelo.map(m => h('div', { class: 'linha-modelo' },
              h('div', { class: 'barra', estilo: { margin: 0, justifyContent: 'space-between' } }, h('b', null, m.modelo), h('span', { class: 'muted' }, m.aprovado + ' aprovados · ' + m.corrigido + ' corrigidos · ' + m.recusado + ' recusados (de ' + m.total + ')')),
              h('div', { class: 'barra-ctx' }, h('i', { estilo: { width: Math.max(2, m.pct_primeira) + '%' } })),
              h('small', { class: 'muted' }, m.pct_primeira + '% aprovado de primeira'))))
              : h('p', { class: 'muted' }, 'Ainda não há conferências. Depois de algumas, aparece aqui quanto do trabalho de cada modelo (Haiku, Sonnet, Opus) serve de primeira: é a base para escolher o modelo de cada tipo de tarefa.')),
          h('section', { class: 'cartao' }, h('h3', null, 'Janela da fila'),
            h('p', null, 'Entram na fila os subagentes que terminaram nos últimos ', h('b', null, d.janela_dias + ' dias'), ' (mude em Configurações).'),
            d.antigos ? h('div', null, h('p', { class: 'muted' }, d.antigos + ' terminados mais antigos ficam fora da fila (provavelmente já conferidos antes do Cérebro existir).'), dispensar) : h('p', { class: 'muted' }, 'Nenhum subagente antigo fora da fila.'))),
        h('section', { class: 'cartao', estilo: { margin: '14px 0' } }, h('h3', null, 'A conferir (' + c.a_conferir + ')'),
          d.pendentes.length ? d.pendentes.map(linhaPendente) : h('div', { class: 'vazio' }, d.gestora ? 'Tudo conferido. Nenhum subagente esperando o gestor.' : 'Escolha a gestora para ver a fila.')),
        h('section', { class: 'cartao' }, h('h3', null, 'Conferidos (últimos 30)'),
          d.conferidos.length ? h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Subagente', 'Modelo', 'Resultado', 'Nota', 'Quando', 'Por'].map(t => h('th', null, t)))),
            h('tbody', null, d.conferidos.slice(0, 30).map(x => h('tr', null, h('td', { class: 'tit', title: x.descricao }, x.descricao), h('td', null, modeloCurto(x.modelo) || '—'),
              h('td', null, h('span', { class: 'chip ' + corResultado(x.resultado) }, x.resultado)), h('td', { class: 'tit', title: x.nota }, x.nota || ''), h('td', null, haQuanto(x.conferido_em)), h('td', null, x.por || '')))))
            : h('p', { class: 'muted' }, 'Nenhuma conferência registrada.')));
    }
    carregar(true);
    cada(15000, () => carregar(false));
  };

  /* ====================================================================================================== */
  /* Ferramentas                                                                                             */
  /* ====================================================================================================== */
  /* Comandos sugeridos (detectados no projeto): NADA roda sozinho; só entra na lista fechada quando a pessoa aprova; rodar continua exigindo "Rodar". */
  UI.secaoSugestoes = function secaoSugestoes(slug, sugestoes, recarregar) {
    const msg = h('span', { class: 'msg-erro' });
    const agir = async (rota, corpo, b) => { b.disabled = true; msg.textContent = ''; try { await post(base(slug) + rota, corpo); recarregar(); } catch (e) { msg.textContent = e.message; b.disabled = false; } };
    const cartao = s => {
      const b = s.aprovada
        ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => agir('/comandos/remover', { id: s.id }, b) }, 'Tirar da lista')
        : h('button', { type: 'button', class: 'bt pri fino', title: 'Põe este comando na lista fechada do projeto. Rodar continua exigindo o botão Rodar.', onclick: () => agir('/comandos/aprovar', { id: s.id }, b) }, 'Aprovar e pôr na lista');
      return h('div', { class: 'prop' },
        h('div', { class: 'topo-conf' }, h('b', { class: 'tit-conf' }, s.nome), s.aprovada ? h('span', { class: 'chip ok' }, 'na lista') : h('span', { class: 'chip' }, 'só sugestão'), h('span', { class: 'chip', title: s.motivo }, s.motivo)),
        h('p', { class: 'motivo' }, s.descricao), h('code', null, s.comando),
        h('div', { class: 'acoes-conf' }, b, h('small', { class: 'muted' }, 'limite ' + duracao(s.timeout))));
    };
    return h('section', { class: 'cartao', estilo: { marginBottom: '14px' } }, h('h3', null, 'Comandos sugeridos para este projeto'),
      h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'Achados só LENDO os arquivos do projeto (package.json, pytest/unittest, cargo, ruff, ESLint). Nada disto roda sozinho: só entra na lista fechada se você aprovar aqui, e mesmo aprovado só roda quando você clicar em Rodar.'),
      msg, sugestoes.length ? sugestoes.map(cartao) : h('div', { class: 'vazio' }, 'Não achei comandos conhecidos neste projeto.'));
  };

  UI.telas.ferramentas = function abaFerramentas(slug, el) {
    let saidaAberta = null, textoSaida = '', mensagem = '';
    const pre = h('pre', { class: 'saida', tabindex: 0, 'aria-label': 'Saída do comando' });
    const tituloSaida = h('b');
    const cxSaida = h('section', { class: 'cartao', hidden: true }, h('div', { class: 'barra', estilo: { justifyContent: 'space-between' } }, tituloSaida, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { saidaAberta = null; cxSaida.hidden = true; } }, 'Fechar')), pre);
    el.append(h('div', { class: 'vazio' }, 'Procurando as ferramentas…'));
    async function verSaida(x) {
      saidaAberta = x.id; cxSaida.hidden = false; tituloSaida.textContent = x.nome + ' · ' + dataCurta(x.inicio) + ' · ' + (nomeResultado[x.resultado] || x.resultado);
      pre.textContent = 'Carregando…';
      try { textoSaida = (await api(base(slug) + '/ferramentas/saida?id=' + encodeURIComponent(x.id))).texto; } catch (e) { textoSaida = e.message; }
      pre.textContent = textoSaida || '(sem saída)'; pre.scrollTop = pre.scrollHeight;
    }
    async function rodar(c, botao) {
      botao.disabled = true; mensagem = '';
      try { await post(base(slug) + '/ferramentas/rodar', { id: c.id }); } catch (e) { mensagem = e.message; }
      carregar();
    }
    function cartaoComando(c, d) {
      const ult = d.historico.find(x => x.comando === c.id);
      const rodando = d.rodando && d.rodando.comando === c.id;
      const ocupado = !!d.rodando;
      const b = h('button', { type: 'button', class: 'bt pri fino', disabled: ocupado, title: ocupado ? 'já há um comando rodando neste projeto' : 'roda agora; só roda porque você clicou', onclick: () => rodar(c, b) }, rodando ? 'Rodando…' : 'Rodar');
      return h('section', { class: 'cartao ferr' },
        h('h3', null, c.nome, rodando ? h('span', { class: 'chip warn' }, 'rodando…') : ult ? h('span', { class: 'chip ' + corResultado(ult.resultado) }, nomeResultado[ult.resultado] || ult.resultado) : h('span', { class: 'chip' }, 'nunca rodou')),
        h('p', { class: 'muted' }, c.descricao),
        ult ? h('p', { class: 'nota' }, 'Última: ' + haQuanto(ult.inicio) + ' · ' + duracao(ult.duracao) + ' · ' + (ult.resumo || '')) : null,
        h('div', { class: 'barra', estilo: { margin: 0 } }, b, ult ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => verSaida(ult) }, 'Ver saída') : null,
          h('small', { class: 'muted' }, 'limite ' + duracao(c.timeout))));
    }
    function cartaoFerramenta(f, d) {
      return h('section', { class: 'cartao ferr' + (f.instalada ? '' : ' ausente') },
        h('h3', null, f.nome, f.instalada ? h('span', { class: 'chip ok' }, 'instalada') : h('span', { class: 'chip' }, 'não instalada'), f.relevante ? null : h('span', { class: 'chip', title: 'o projeto não parece usar isto' }, 'não se aplica')),
        h('p', { class: 'muted' }, f.o_que), f.grupo ? h('small', { class: 'muted' }, f.grupo) : null,
        f.instalada ? h('p', { class: 'nota' }, f.versao || 'versão não informada') : h('div', { class: 'instalar' }, h('small', { class: 'muted' }, 'Para instalar (precisa da sua aprovação):'), h('code', null, f.instalar)),
        f.ultima ? h('p', { class: 'nota' }, 'Última execução: ' + (nomeResultado[f.ultima.resultado] || f.ultima.resultado) + ' · ' + haQuanto(f.ultima.inicio)) : null,
        UI.extraFerramenta ? UI.extraFerramenta(slug, f, d.instalacao, carregar) : null);
    }
    async function carregar() {
      let d;
      try { d = await api(base(slug) + '/ferramentas'); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const g = d.graphify, b = d.baterias;
      const hist = d.historico;
      if (d.rodando && !UI.timerRodando) { UI.timerRodando = true; setTimeout(() => { UI.timerRodando = false; carregar(); }, 2500); }
      trocar(el,
        h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'Comandos só rodam quando você clica em Rodar, e só os da lista fechada deste projeto (os que você aprovou). Sem shell, com tempo limite, sem janela; a saída é guardada com os segredos mascarados. Instalar uma ferramenta só acontece pelo botão Instalar, depois de você conferir o comando.'),
        mensagem ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '12px' } }, mensagem) : null,
        h('div', { class: 'grade', estilo: { marginBottom: '14px' } },
          h('section', { class: 'cartao ferr' }, h('h3', null, 'Graphify (mapa)', g.instalado ? h('span', { class: 'chip ok' }, 'instalado') : h('span', { class: 'chip' }, 'não instalado')),
            h('p', { class: 'nota' }, (g.versao || 'versão desconhecida') + (g.mapa ? ' · mapa de ' + dataCurta(g.graph_em) : ' · este projeto ainda não tem mapa')),
            g.totais ? h('p', { class: 'muted' }, num(g.totais.arquivos) + ' arquivos · ' + num(g.totais.itens) + ' itens · ' + num(g.totais.grupos) + ' grupos · ' + num(g.totais.ligacoes) + ' ligações') : null,
            g.pagina_em ? h('p', { class: 'nota' }, 'Página do mapa atualizada ' + haQuanto(g.pagina_em)) : null),
          h('section', { class: 'cartao ferr' }, h('h3', null, 'Baterias de teste do projeto'),
            h('p', { class: 'muted' }, b.scripts ? num(b.scripts) + ' scripts em ' + b.pasta + '/' + (b.como_rodar ? ' · rodar: ' : '') : 'Nenhuma pasta de testes encontrada.'), b.como_rodar ? h('code', null, b.como_rodar) : null,
            ['testes', 'lint'].filter(k => b.resultados[k]).map(k => h('p', { class: 'nota' }, k + ': ' + (b.resultados[k].resumo || 'resultado encontrado') + ' (' + haQuanto(b.resultados[k].atualizado) + ')')),
            !Object.keys(b.resultados).length ? h('p', { class: 'nota' }, 'Sem arquivo de resultado conhecido (testes/resultado.json...). O Cérebro não roda a bateria completa sozinho: aprove um comando sugerido abaixo e rode quando quiser.') : null)),
        h('h3', { class: 'sub-titulo' }, 'Comandos permitidos neste projeto'),
        d.comandos.length ? h('div', { class: 'grade', estilo: { marginBottom: '14px' } }, d.comandos.map(c => cartaoComando(c, d)))
          : h('div', { class: 'vazio cartao', estilo: { marginBottom: '14px' } }, 'Nenhum comando liberado ainda. Aprove abaixo os comandos sugeridos que fizerem sentido para este projeto.'),
        UI.secaoSugestoes(slug, d.sugestoes || [], carregar),
        cxSaida,
        h('h3', { class: 'sub-titulo' }, 'Ferramentas no PC'),
        h('div', { class: 'grade', estilo: { marginBottom: '14px' } }, d.cartoes.map(f => cartaoFerramenta(f, d))),
        h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Histórico (últimas ' + hist.length + ' de 20 execuções)'),
          hist.length ? h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Comando', 'Quando', 'Duração', 'Resultado', 'Resumo', ''].map(t => h('th', null, t)))),
            h('tbody', null, hist.map(x => h('tr', null, h('td', null, x.nome), h('td', null, dataCurta(x.inicio)), h('td', null, duracao(x.duracao)),
              h('td', null, h('span', { class: 'chip ' + corResultado(x.resultado) }, nomeResultado[x.resultado] || x.resultado)), h('td', { class: 'tit', title: x.resumo }, x.resumo || ''),
              h('td', null, h('button', { type: 'button', class: 'bt leve fino', onclick: () => verSaida(x) }, 'Ver saída'))))))
            : h('p', { class: 'muted' }, 'Nenhuma execução ainda.')));
      if (saidaAberta) { cxSaida.hidden = false; }
    }
    carregar();
    cada(20000, carregar);
  };

  /* ====================================================================================================== */
  /* Propostas (usado por Análise e Novidades)                                                              */
  /* ====================================================================================================== */
  const corRisco = { baixo: 'ok', médio: 'warn', alto: 'perigo' };
  function listaPropostas(escopo, propostas, tarefas, recarregar, opcoes) {
    opcoes = opcoes || {};
    const novas = propostas.filter(p => p.estado === 'nova'), aprov = propostas.filter(p => p.estado === 'aprovada'), desc = propostas.filter(p => p.estado === 'descartada');
    const decidir = async (p, acao, nota) => { try { await post(base(escopo) + '/propostas/' + encodeURIComponent(p.id), { acao, nota: nota || '' }); recarregar(); } catch (e) { alert_(e.message); } };
    const alert_ = m => { const a = document.getElementById('aviso-propostas'); if (a) a.textContent = m; };
    const cartao = p => {
      const nota = h('input', { type: 'text', maxlength: 500, placeholder: 'Nota (opcional)', 'aria-label': 'Nota da decisão' });
      return h('div', { class: 'prop' },
        h('div', { class: 'topo-conf' }, h('b', { class: 'tit-conf' }, p.titulo),
          h('span', { class: 'chip', title: 'esforço: P pequeno, M médio, G grande' }, 'esforço ' + p.esforco), h('span', { class: 'chip ' + (corRisco[p.risco] || '') }, 'risco ' + p.risco),
          h('span', { class: 'chip accent' }, p.origem === 'novidade' ? 'novidade' : p.origem === 'cerebro' ? 'do Cérebro' : 'do projeto'), p.area ? h('span', { class: 'chip' }, p.area) : null),
        h('p', { class: 'motivo' }, p.motivo),
        p.estado === 'nova' ? h('div', { class: 'acoes-conf' }, nota, h('button', { type: 'button', class: 'bt pri fino', onclick: () => decidir(p, 'aprovar', nota.value) }, 'Aprovar (vira tarefa)'),
          h('button', { type: 'button', class: 'bt leve fino', onclick: () => decidir(p, 'descartar', nota.value) }, 'Descartar'))
          : p.estado === 'descartada' ? h('div', { class: 'acoes-conf' }, h('span', { class: 'muted' }, 'descartada ' + haQuanto(p.decidida_em) + (p.nota ? ' · ' + p.nota : '')), h('button', { type: 'button', class: 'bt leve fino', onclick: () => decidir(p, 'reabrir') }, 'Reabrir'))
            : h('div', { class: 'acoes-conf' }, h('span', { class: 'muted' }, 'aprovada ' + haQuanto(p.decidida_em) + (p.nota ? ' · ' + p.nota : ''))));
    };
    const tarefa = t => {
      const b = h('button', { type: 'button', class: 'bt leve fino', onclick: async () => { b.disabled = true; try { await post(base(escopo) + '/tarefas/' + encodeURIComponent(t.id), {}); recarregar(); } catch (e) { b.textContent = e.message; } } }, 'Marcar como feita');
      return h('div', { class: 'prop' + (t.estado === 'feita' ? ' feita' : '') }, h('div', { class: 'topo-conf' }, h('b', { class: 'tit-conf' }, t.titulo), h('span', { class: 'chip ' + (t.estado === 'aberta' ? 'violet' : t.estado === 'recusada' ? 'perigo' : 'ok') }, t.estado === 'aberta' ? 'para o gestor' : t.estado === 'recusada' ? 'recusada' : 'feita'),
        h('span', { class: 'chip' }, 'esforço ' + t.esforco), h('span', { class: 'chip ' + (corRisco[t.risco] || '') }, 'risco ' + t.risco)), h('p', { class: 'motivo' }, t.motivo),
        t.estado === 'aberta' ? h('div', { class: 'acoes-conf' }, b, h('small', { class: 'muted' }, 'O gestor também marca por: python cerebro_cli.py tarefa-feita <projeto> ' + t.id)) : null);
    };
    const abertas = tarefas.filter(t => t.estado === 'aberta');
    return h('div', null, h('span', { id: 'aviso-propostas', class: 'msg-erro' }),
      abertas.length ? h('section', { class: 'cartao destaque-violeta', estilo: { marginBottom: '14px' } }, h('h3', null, 'Tarefas para o gestor (' + abertas.length + ')'), abertas.map(tarefa)) : null,
      h('section', { class: 'cartao', estilo: { marginBottom: '14px' } }, h('h3', null, (opcoes.titulo || 'Propostas') + ' para decidir (' + novas.length + ')'),
        novas.length ? novas.map(cartao) : h('div', { class: 'vazio' }, opcoes.vazio || 'Nenhuma proposta nova. Rode a análise para gerar.')),
      aprov.length || desc.length ? h('details', { class: 'cartao' }, h('summary', null, 'Decididas (' + aprov.length + ' aprovadas, ' + desc.length + ' descartadas)'), aprov.concat(desc).map(cartao)) : null);
  }

  /* ====================================================================================================== */
  /* Análise                                                                                                 */
  /* ====================================================================================================== */
  UI.telas.analise = function abaAnalise(slug, el) {
    el.append(h('div', { class: 'vazio' }, 'Carregando…'));
    let rodando = false;
    async function rodarAgora(escopo, botao) {
      if (rodando) return;
      rodando = true; botao.disabled = true; botao.textContent = 'Analisando… (alguns segundos)';
      try { await post(base(escopo) + '/analise', {}); } catch (e) { botao.textContent = e.message; }
      rodando = false; carregar();
    }
    function tabela(cab, linhas) {
      return h('table', { class: 'tabela' }, h('thead', null, h('tr', null, cab.map((t, i) => h('th', { class: i ? 'n' : '' }, t)))), h('tbody', null, linhas.map(l => h('tr', null, l.map((v, i) => h('td', { class: i ? 'n' : 'tit', title: i ? '' : String(v) }, v))))));
    }
    function relatorio(r) {
      if (!r) return h('div', { class: 'vazio cartao' }, 'Ainda não há análise deste projeto. Clique em "Analisar agora".');
      const blocos = [];
      if (r.maiores && r.maiores.length) blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Maiores arquivos de código'), tabela(['Arquivo', 'Linhas', 'KB'], r.maiores.slice(0, 10).map(m => [m.caminho, num(m.linhas), Math.round(m.bytes / 1024)]))));
      if (r.cresceram && r.cresceram.length) blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Que mais cresceram em 30 dias'), tabela(['Arquivo', 'Saldo de linhas', 'Commits'], r.cresceram.slice(0, 8).map(m => [m.caminho, '+' + num(m.saldo), m.commits]))));
      if (r.mapa && r.mapa.disponivel) {
        const m = r.mapa;
        blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Mapa: grupos e centros'),
          tabela(['Maiores grupos', 'Itens', 'Departamento'], m.grupos.map(g => [g.nome, num(g.itens), g.depto])),
          h('div', { estilo: { height: '10px' } }), tabela(['Centros (mais ligações)', 'Ligações'], m.centros.map(g => [g.nome, num(g.ligacoes)]))));
        blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Mapa: mudanças recentes (linha do tempo)'),
          m.mudancas.length ? tabela(['Geração', 'Itens', 'Arquivos +/−', 'Itens +/−'], m.mudancas.map(x => [dataCurta(Date.parse(x.data) / 1000) + ' · ' + x.commit, num(x.itens), x.inicial ? 'inicial' : '+' + (x.arquivos_entraram || 0) + ' / −' + (x.arquivos_sairam || 0), x.inicial ? '—' : '+' + (x.itens_entraram || 0) + ' / −' + (x.itens_sairam || 0)])) : h('p', { class: 'muted' }, 'Sem histórico.')));
      }
      if (r.contexto_fixo) blocos.push(h('section', { class: 'cartao' }, h('h3', null, 'Contexto fixo por conversa'), h('p', null, h('b', null, '≈ ' + num(r.contexto_fixo.total_tokens) + ' tokens'), ' (MEMORY.md + CLAUDE.md + AGENTS.md)'),
        (r.contexto_fixo.arquivos || []).map(a => h('div', { class: 'barra', estilo: { margin: 0, justifyContent: 'space-between' } }, h('span', null, a.nome), h('span', { class: 'muted' }, '≈ ' + num(a.tokens)))), (r.avisos_memoria || []).map(a => h('p', { class: 'nota' }, a))));
      if (r.custos) {
        const c = r.custos;
        blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Custo e tendência'),
          h('p', null, h('b', null, usd(c.ultimos7.custo)), ' nos últimos 7 dias · ', usd(c.anteriores7.custo), ' nos 7 anteriores', c.tendencia_pct != null ? h('span', { class: 'chip ' + (c.tendencia_pct > 30 ? 'warn' : 'ok'), estilo: { marginLeft: '8px' } }, (c.tendencia_pct > 0 ? '+' : '') + c.tendencia_pct + '%') : null),
          tabela(['Modelo', 'Custo est.', '% do total'], c.por_modelo.map(m => [modeloCurto(m.modelo), usd(m.custo), m.parte != null ? m.parte + '%' : '—']))));
      }
      if (r.revisoes) {
        const rv = r.revisoes;
        blocos.push(h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Revisão do gestor'),
          h('p', null, rv.contadores.a_conferir + ' a conferir (' + rv.contadores.parados + ' parados) · ' + rv.contadores.conferidos + ' conferidos'),
          rv.por_modelo.length ? tabela(['Modelo', 'Conferidos', '% aprovado de primeira'], rv.por_modelo.map(m => [m.modelo, m.total, m.pct_primeira + '%'])) : h('p', { class: 'muted' }, 'Ainda sem conferências para comparar modelos.')));
      }
      if (r.ferramentas) {
        const f = r.ferramentas;
        blocos.push(h('section', { class: 'cartao' }, h('h3', null, 'Ferramentas'), h('p', null, 'Instaladas: ' + (f.instaladas.join(', ') || 'nenhuma')), h('p', null, 'Recomendadas ainda não instaladas: ' + (f.faltam.join(', ') || 'nenhuma')),
          f.execucoes.length ? f.execucoes.map(x => h('p', { class: 'nota' }, x.nome + ': ' + (nomeResultado[x.resultado] || x.resultado) + ' (' + haQuanto(x.inicio) + ') ' + (x.resumo || ''))) : h('p', { class: 'muted' }, 'Nenhuma execução registrada.')));
      }
      if (r.git) blocos.push(h('section', { class: 'cartao' }, h('h3', null, 'Atividade do código'), h('p', null, (r.git.commits_30d != null ? num(r.git.commits_30d) + ' commits nos últimos 30 dias' : 'commits: não consegui contar'))));
      return h('div', { class: 'grade relatorio' }, blocos);
    }
    function relatorioCerebro(r) {
      if (!r) return h('div', { class: 'vazio cartao' }, 'Ainda não há análise do Cérebro.');
      return h('div', { class: 'grade relatorio' }, h('section', { class: 'cartao rolagem-x' }, h('h3', null, 'Cérebro ' + (r.versao || '')),
        h('p', null, num(r.testes) + ' arquivos de teste · dados em ~/.cerebro: ' + tamanho_(r.dados_bytes)),
        tabela(['Maiores arquivos do Cérebro', 'Linhas'], (r.maiores || []).slice(0, 8).map(m => [m.caminho, num(m.linhas)]))));
    }
    const tamanho_ = n => (n >= 1e6 ? (n / 1e6).toFixed(1).replace('.', ',') + ' MB' : Math.max(1, Math.round((n || 0) / 1e3)) + ' KB');
    async function carregar() {
      let d, dc;
      try { [d, dc] = await Promise.all([api(base(slug) + '/analise'), api(base('_cerebro') + '/analise')]); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const b1 = h('button', { type: 'button', class: 'bt pri', onclick: () => rodarAgora(slug, b1) }, 'Analisar agora');
      const b2 = h('button', { type: 'button', class: 'bt leve', onclick: () => rodarAgora('_cerebro', b2) }, 'Analisar o próprio Cérebro');
      trocar(el,
        h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'Análise SEM IA (barata): números do git, do mapa, das ferramentas, dos custos, da memória e da fila a conferir viram propostas com motivo, esforço (P/M/G) e risco. Nada é aplicado sozinho: você aprova ou descarta; aprovada vira "tarefa para o gestor".'),
        h('div', { class: 'barra' }, b1, h('span', { class: 'muted' }, d.ultima_em ? 'Última análise ' + haQuanto(d.ultima_em) + ' · ' + (d.automatica ? 'próxima ' + futuro(d.proxima_em) + ' (roda sozinha se o servidor estiver aberto)' : 'automática desligada') : 'Nunca rodou' + (d.automatica ? ' · roda sozinha com o servidor aberto' : ''))),
        listaPropostas(slug, d.propostas, d.tarefas, carregar, { titulo: 'Propostas do projeto' }),
        h('h3', { class: 'sub-titulo' }, 'Relatório mais recente'), relatorio(d.relatorio),
        d.historico.length ? h('section', { class: 'cartao rolagem-x', estilo: { marginTop: '14px' } }, h('h3', null, 'Histórico de análises'),
          tabela(['Quando', 'Duração', 'Propostas', 'Novas'], d.historico.slice(0, 10).map(x => [dataCurta(x.em), x.duracao + ' s', x.propostas, x.novas]))) : null,
        h('h3', { class: 'sub-titulo' }, 'O próprio Cérebro (vale para todos os projetos)'),
        h('div', { class: 'barra' }, b2, h('span', { class: 'muted' }, dc.ultima_em ? 'Última análise ' + haQuanto(dc.ultima_em) + ' · próxima ' + futuro(dc.proxima_em) : 'Nunca rodou')),
        listaPropostas('_cerebro', dc.propostas.filter(p => p.origem !== 'novidade'), dc.tarefas, carregar, { titulo: 'Propostas do Cérebro', vazio: 'Nenhuma proposta nova para o Cérebro.' }),
        relatorioCerebro(dc.relatorio));
    }
    carregar();
  };

  /* ====================================================================================================== */
  /* Novidades                                                                                               */
  /* ====================================================================================================== */
  UI.telas.novidades = function abaNovidades(slug, el) {
    el.append(h('div', { class: 'vazio' }, 'Carregando…'));
    let buscando = false, aviso = '';
    async function procurar(botao) {
      if (buscando) return;
      buscando = true; botao.disabled = true; botao.textContent = 'Consultando…'; aviso = '';
      try { const r = await post('/api/novidades/procurar', {}); if (r.ok === false) aviso = r.erro; else if (r.sem_rede) aviso = 'Sem rede ou sem resposta das páginas públicas agora. Tente de novo mais tarde.'; else if (r.erros && r.erros.length) aviso = r.erros.length + ' fonte(s) sem resposta: ' + r.erros.slice(0, 3).join('; '); }
      catch (e) { aviso = e.message; }
      buscando = false; carregar();
    }
    async function carregar() {
      let n, dc;
      try { [n, dc] = await Promise.all([api('/api/novidades'), api(base('_cerebro') + '/analise')]); } catch (e) { el.replaceChildren(h('div', { class: 'vazio' }, e.message)); return; }
      const b = h('button', { type: 'button', class: 'bt pri', onclick: () => procurar(b) }, 'Procurar novidades');
      const visto = async id => { try { await post('/api/novidades/visto', { id }); } catch (e) { /* segue */ } carregar(); };
      trocar(el,
        h('p', { class: 'muted', estilo: { marginTop: 0 } }, 'O vigia consulta SÓ páginas públicas de releases (API pública do GitHub, GET, sem login). Nada do seu projeto é enviado: a única coisa que sai do PC é "qual é a última versão de cada ferramenta". Versão nova de ferramenta instalada vira PROPOSTA; nada é instalado sozinho.'),
        h('div', { class: 'barra' }, b, h('button', { type: 'button', class: 'bt leve', onclick: () => visto(null) }, 'Marcar tudo como visto'),
          h('span', { class: 'muted' }, n.ultima_busca ? 'Última busca ' + haQuanto(n.ultima_busca) + (n.automatica ? ' · próxima ' + futuro(n.proxima_em) + ' (sozinha, com o servidor aberto)' : ' · só roda quando você clica (a busca automática está desligada em Configurações)') : 'Nunca procurou')),
        aviso || n.sem_rede || n.erro ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '14px' } }, aviso || (n.sem_rede ? 'Sem rede na última busca.' : 'Algumas fontes não responderam: ' + n.erro)) : null,
        h('section', { class: 'cartao rolagem-x', estilo: { marginBottom: '14px' } }, h('h3', null, 'Fontes acompanhadas'),
          h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Fonte', 'Última versão', 'Publicada', 'No seu PC', 'Situação', ''].map(t => h('th', null, t)))),
            h('tbody', null, n.fontes.map(f => h('tr', null,
              h('td', { class: 'tit', title: f.o_que }, h('b', null, f.nome), h('div', { class: 'muted', estilo: { fontSize: '11.5px' } }, f.o_que)),
              h('td', null, f.ultima ? h('a', { href: /^https:\/\//.test(f.ultima.url || '') ? f.ultima.url : '#', target: '_blank', rel: 'noopener noreferrer', title: f.ultima.resumo || '' }, f.ultima.tag) : '—'),
              h('td', null, f.ultima && f.ultima.publicado ? f.ultima.publicado.slice(0, 10) : '—'), h('td', null, f.instalada || (f.tipo === 'ferramenta' ? (f.id === 'eslint' ? 'por projeto (node_modules)' : 'não instalada') : '—')),
              h('td', null, f.novo ? h('span', { class: 'chip violet' }, 'novo desde a última vez') : f.situacao === 'desatualizada' ? h('span', { class: 'chip warn' }, 'desatualizada') : f.situacao === 'atualizada' ? h('span', { class: 'chip ok' }, 'em dia') : f.ultima ? h('span', { class: 'chip' }, 'visto') : h('span', { class: 'chip' }, 'sem consulta')),
              h('td', null, f.novo ? h('button', { type: 'button', class: 'bt leve fino', onclick: () => visto(f.id) }, 'Marcar visto') : null)))))),
        listaPropostas('_cerebro', dc.propostas.filter(p => p.origem === 'novidade'), [], carregar, { titulo: 'Propostas vindas das novidades', vazio: 'Nenhuma proposta de novidade. Elas aparecem quando uma ferramenta instalada tem versão nova ou o Claude Code lança algo.' }));
    }
    carregar();
  };
})();
