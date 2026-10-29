/* Cérebro do Projeto — Configurações › Backup (cópia de segurança e restauração) e Configurações › Rotinas no Windows.
   Nada que vem de arquivos entra na página como HTML: tudo com h() / textContent. Restaurar pede dois cliques; ligar uma rotina
   no Windows é o próprio clique da pessoa (o servidor só cria tarefas na pasta CerebroDoProjeto do Agendador). */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, haQuanto, dataCurta, api, post } = UI;
  const mb = n => UI.tamanho(n || 0);           /* KB abaixo de 1 MB */
  const NOMES = { backup: 'Backup diário', analise: 'Análise sem IA dos projetos', novidades: 'Procurar novidades (internet)', mapa: 'Refazer a página do mapa' };

  /* botão que pede um segundo clique para confirmar (como "Encerrar o servidor") */
  function botaoConfirmar(rotulo, rotuloConfirmar, classe, acao) {
    let armado = false;
    const b = h('button', { type: 'button', class: 'bt fino ' + classe, onclick: async () => {
      if (!armado) { armado = true; b.textContent = rotuloConfirmar; setTimeout(() => { armado = false; b.textContent = rotulo; }, 5000); return; }
      armado = false; b.textContent = rotulo; await acao(b);
    } }, rotulo);
    return b;
  }

  /* ====================================================================================================== */
  /* Backup                                                                                                  */
  /* ====================================================================================================== */
  UI.secoesConfig.push(({ dizer }) => {
    const secao = h('section', { class: 'cartao secao rolagem-x' }, h('h3', null, 'Backup das conversas e da memória'), h('div', { class: 'vazio' }, 'Carregando…'));
    const painelRestaurar = h('div');

    async function abrirRestaurar(s) {
      const projeto = h('select', { 'aria-label': 'Projeto a restaurar' }, h('option', { value: '' }, 'todos os projetos'), s.projetos.map(p => h('option', { value: p }, p)),
        h('option', { value: '_cerebro' }, 'só os dados do Cérebro (.cerebro)'));
      const soMem = h('input', { type: 'checkbox' });
      const resultado = h('div');
      async function verPlano(botao) {
        botao.disabled = true;
        trocar(resultado, h('div', { class: 'vazio' }, 'Comparando o backup com o que existe hoje…'));
        try {
          const pl = await post('/api/backup/plano', { snapshot: s.nome, projeto: projeto.value, so_memoria: soMem.checked });
          desenharPlano(pl);
        } catch (e) { trocar(resultado, h('div', { class: 'vazio' }, e.message)); }
        botao.disabled = false;
      }
      function desenharPlano(pl) {
        const marcados = new Set();
        const t = pl.totais;
        const grupos = pl.grupos.filter(g => g.faltam.length || g.diferentes.length || g.cresceram.length);
        const linhaItem = (it, marcavel) => h('div', { class: 'linha-cfg' },
          marcavel ? h('label', { class: 'chk' }, h('input', { type: 'checkbox', onchange: e => { if (e.target.checked) marcados.add(it.arq); else marcados.delete(it.arq); } }), 'trocar') : h('span', { class: 'chip ok' }, 'volta'),
          h('span', { class: 'mono' }, it.mostrar), h('span', { class: 'muted' }, mb(it.tam_backup) + (it.tam_hoje != null ? ' no backup · hoje ' + mb(it.tam_hoje) : ' · falta hoje')));
        const bRestaurar = botaoConfirmar('Restaurar', 'Clique de novo para restaurar', 'pri', async b => {
          b.disabled = true;
          try {
            const r = await post('/api/backup/restaurar', { snapshot: s.nome, projeto: projeto.value, so_memoria: soMem.checked, trocar: [...marcados], confirmar: true });
            dizer('Restaurado: ' + r.copiados + ' arquivo(s) de volta, ' + r.trocados + ' trocado(s).' + (r.copias ? ' A versão de hoje dos trocados ficou em ' + r.copias + '.' : '') + (r.erros.length ? ' Erros: ' + r.erros.join('; ') : ''), !r.erros.length);
            await verPlano(b);
          } catch (e) { dizer(e.message, false); }
          b.disabled = false;
        });
        trocar(resultado,
          h('p', null, 'Faltam hoje: ' + t.faltam + ' · diferentes: ' + t.diferentes + ' · cresceram depois do backup: ' + t.cresceram + ' (ficam como estão) · iguais: ' + t.iguais),
          grupos.length ? grupos.map(g => h('details', { class: 'cartao', open: grupos.length < 4 },
            h('summary', null, (g.grupo === '_cerebro' ? 'Dados do Cérebro' : g.grupo) + ': faltam ' + g.faltam.length + ', diferentes ' + g.diferentes.length + ', cresceram ' + g.cresceram.length),
            g.faltam.slice(0, 300).map(it => linhaItem(it, false)),
            g.diferentes.slice(0, 300).map(it => linhaItem(it, true)),
            g.faltam.length > 300 || g.diferentes.length > 300 ? h('p', { class: 'nota' }, 'Lista encurtada na tela; a restauração cobre todos os que faltam.') : null))
            : h('div', { class: 'vazio' }, 'Nada a restaurar: o que existe hoje já tem tudo deste backup.'),
          t.faltam || t.diferentes ? h('div', { class: 'linha-cfg' }, bRestaurar, h('span', { class: 'muted' }, 'Copia de volta o que falta. Os diferentes só são trocados se você marcar; a versão de hoje é guardada antes. Nada é apagado.')) : null);
      }
      const bVer = h('button', { type: 'button', class: 'bt leve fino', onclick: e => verPlano(e.currentTarget) }, 'Ver o que mudaria');
      trocar(painelRestaurar, h('div', { class: 'cartao', estilo: { marginTop: '10px' } },
        h('h4', null, 'Restaurar o backup de ' + s.data + ' (' + s.nome + ')'),
        h('div', { class: 'linha-cfg' }, projeto, h('label', { class: 'chk' }, soMem, 'só a memória'), bVer,
          h('button', { type: 'button', class: 'bt leve fino', onclick: () => painelRestaurar.replaceChildren() }, 'Fechar')),
        resultado));
    }

    async function carregar() {
      let r;
      try { r = await api('/api/backup'); } catch (e) { trocar(secao, h('h3', null, 'Backup das conversas e da memória'), h('div', { class: 'vazio' }, e.message)); return; }
      const u = r.ultimo;
      const bAgora = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
        bAgora.disabled = true; bAgora.textContent = 'Fazendo o backup…';
        try {
          const x = await post('/api/backup/agora', {});
          dizer('Backup feito: ' + x.nome + ' · ' + x.arquivos + ' arquivos · ' + mb(x.bytes_zip) + ' no zip' + (x.falhas.length ? ' · ' + x.falhas.length + ' arquivo(s) aberto(s) não lido(s)' : '') + (x.encolheu ? ' · ATENÇÃO: bem menor que o anterior' : ''), !x.encolheu);
        } catch (e) { dizer(e.message, false); }
        carregar();
      } }, 'Fazer backup agora');
      const origem = r.origem_hoje ? Object.values(r.origem_hoje).reduce((a, o) => a + o.bytes, 0) : null;
      trocar(secao, h('h3', null, 'Backup das conversas e da memória'),
        r.erro ? h('div', { class: 'aviso-caixa' }, r.erro) : null,
        h('p', { class: 'nota' }, 'Uma cópia por dia das conversas e da memória do Claude Code (.claude/projects) e dos dados do Cérebro, guardada FORA dessas pastas: se alguém apagar uma delas, o backup sobrevive. Guarda os últimos ' + (r.manter_dias || 7) + ' dias.'),
        h('div', { class: 'linha-cfg' }, h('span', null, 'Pasta: '), h('span', { class: 'mono muted' }, r.pasta || '—')),
        h('div', { class: 'linha-cfg' }, h('span', null, 'Último backup: '),
          u ? (u.ok ? h('span', { class: 'chip ok' }, haQuanto(u.em) + ' · ' + u.arquivos + ' arquivos · ' + mb(u.bytes_zip)) : h('span', { class: 'chip perigo' }, 'falhou ' + haQuanto(u.em) + ': ' + (u.erro || ''))) : h('span', { class: 'chip warn' }, 'nenhum ainda'),
          origem != null ? h('span', { class: 'muted' }, 'Hoje as pastas somam ' + mb(origem) + ' (o zip fica bem menor).') : null),
        r.protegidos && r.protegidos.length ? h('div', { class: 'aviso-caixa' }, 'O último backup ficou bem menor que o anterior. O de antes (' + r.protegidos.join(', ') + ') está guardado e não sai na rotação. Confira se nada foi apagado; se foi de propósito, ',
          botaoConfirmar('está tudo certo, liberar', 'Clique de novo: o backup de antes volta a sair na rotação', 'leve', async () => { try { await post('/api/backup/liberar', { confirmar: true }); dizer('Liberado.'); carregar(); } catch (e) { dizer(e.message, false); } })) : null,
        h('div', { class: 'linha-cfg' }, bAgora),
        r.snapshots.length ? h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Dia', 'Feito', 'No zip', 'Arquivos', 'Projetos', ''].map(t => h('th', null, t)))),
          h('tbody', null, r.snapshots.map(s => h('tr', null, h('td', null, s.data, (r.protegidos || []).includes(s.nome) ? h('span', { class: 'chip warn' }, 'protegido') : null),
            h('td', null, dataCurta(s.criado_em)), h('td', null, mb(s.bytes_zip)), h('td', null, String(s.arquivos) + (s.falhas ? ' (' + s.falhas + ' não lido)' : '')), h('td', null, String(s.projetos.length)),
            h('td', null, h('button', { type: 'button', class: 'bt leve fino', onclick: async e => {
              const b = e.currentTarget; b.disabled = true;
              try { const c = await post('/api/backup/conferir', { snapshot: s.nome }); dizer(c.ok ? s.nome + ' confere (' + c.conferidos + ' arquivos).' : s.nome + ' NÃO confere: ' + c.problemas.slice(0, 3).join('; '), c.ok); } catch (er) { dizer(er.message, false); }
              b.disabled = false;
            } }, 'Conferir'), h('button', { type: 'button', class: 'bt leve fino', onclick: () => abrirRestaurar(s) }, 'Restaurar…')))))) : null,
        r.incompletos.length ? h('p', { class: 'nota' }, 'Não contam como backup (incompletos): ' + r.incompletos.map(x => x.nome).join(', ')) : null,
        painelRestaurar);
    }
    carregar();
    return secao;
  });

  /* ====================================================================================================== */
  /* Rotinas no Windows (Agendador de Tarefas)                                                               */
  /* ====================================================================================================== */
  UI.secoesConfig.push(({ dizer }) => {
    const secao = h('section', { class: 'cartao secao rolagem-x' }, h('h3', null, 'Rotinas no Windows (rodam sozinhas, mesmo com o painel fechado)'), h('div', { class: 'vazio' }, 'Carregando…'));
    function desenhar(d) {
      const linhas = d.rotinas.map(r => {
        const p = r.parametros, a = r.agendador || {}, u = r.ultima_execucao;
        const hora = h('input', { type: 'time', value: p.hora, 'aria-label': 'Horário' });
        const dias = 'dias' in p ? h('input', { type: 'number', min: 1, max: 365, value: p.dias, 'aria-label': 'Intervalo em dias' }) : null;
        const horas = 'horas' in p ? h('input', { type: 'number', min: 1, max: 23, value: p.horas, 'aria-label': 'Intervalo em horas' }) : null;
        const mudar = async (acao, b) => {
          b.disabled = true;
          const corpo = { rotina: r.rotina, acao, hora: hora.value };
          if (dias) corpo.dias = parseInt(dias.value, 10);
          if (horas) corpo.horas = parseInt(horas.value, 10);
          try { desenhar(await post('/api/rotinas/windows', corpo)); dizer(acao === 'ligar' ? NOMES[r.rotina] + ': ligada no Windows.' : NOMES[r.rotina] + ': desligada.'); }
          catch (e) { dizer(e.message, false); b.disabled = false; }
        };
        return h('tr', null,
          h('td', null, h('b', null, NOMES[r.rotina] || r.rotina), h('div', { class: 'muted' }, r.descricao)),
          h('td', null, h('label', null, r.rotina === 'backup' ? 'todo dia às ' : r.rotina === 'mapa' ? 'a partir de ' : 'às ', hora),
            dias ? h('label', null, ' a cada ', dias, ' dias') : null, horas ? h('label', null, ' a cada ', horas, ' h') : null,
            r.rotina === 'backup' ? h('div', { class: 'muted' }, 'e ao entrar no Windows, se o PC estava desligado no horário') : null),
          h('td', null, a.ligada ? h('span', { class: 'chip ok' }, 'ligada') : h('span', { class: 'chip' }, 'desligada'),
            a.ligada && a.proxima ? h('div', { class: 'muted' }, 'próxima: ' + a.proxima) : null, a.erro ? h('div', { class: 'msg-erro' }, a.erro) : null),
          h('td', null, u ? h('span', { class: 'chip ' + (u.ok ? 'ok' : 'perigo') }, (u.ok ? 'ok ' : 'erro ') + haQuanto(u.em)) : h('span', { class: 'muted' }, 'nunca rodou'),
            u ? h('div', { class: 'muted', title: u.texto }, u.texto.slice(0, 140)) : null),
          h('td', null, d.disponivel ? h('button', { type: 'button', class: 'bt fino ' + (a.ligada ? 'leve' : 'pri'), onclick: e => mudar('ligar', e.currentTarget) }, a.ligada ? 'Atualizar' : 'Ligar no Windows') : null,
            d.disponivel && a.ligada ? h('button', { type: 'button', class: 'bt leve fino', onclick: e => mudar('desligar', e.currentTarget) }, 'Desligar') : null));
      });
      trocar(secao, h('h3', null, 'Rotinas no Windows (rodam sozinhas, mesmo com o painel fechado)'),
        d.disponivel ? null : h('div', { class: 'aviso-caixa info' }, 'O agendamento só existe no Windows. Aqui as rotinas rodam só com o servidor aberto (seção acima).'),
        h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Rotina', 'Quando', 'No Windows', 'Última execução', ''].map(t => h('th', null, t)))), h('tbody', null, linhas)),
        h('p', { class: 'nota' }, 'Ligar cria uma tarefa no Agendador de Tarefas do Windows, na pasta "CerebroDoProjeto", com o seu usuário, sem senha e sem permissão de administrador, rodando sem janela. Desligar remove só essa tarefa. O registro de cada execução fica em .cerebro/rotinas. O mapa só é refeito a partir do que o Graphify já gerou (sem IA).'));
    }
    api('/api/rotinas/windows').then(desenhar).catch(e => trocar(secao, h('h3', null, 'Rotinas no Windows'), h('div', { class: 'vazio' }, e.message)));
    return secao;
  });
})();
