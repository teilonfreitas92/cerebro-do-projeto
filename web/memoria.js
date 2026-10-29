/* Cérebro do Projeto — memória mais forte: editar, criar e arquivar memórias, compactar o MEMORY.md, avisos de memória
   velha/contraditória, editar/arquivar decisões e o passa-bastão de conversa longa.
   Toda gravação: mostra a diferença ANTES, a pessoa confirma, o servidor faz cópia de segurança e recusa se o arquivo mudou.
   Nada que vem de memória ou conversa entra como HTML: tudo é criado com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, num, dataCurta, api, post } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);
  const TIPOS = [['user', 'Sobre você (user)'], ['feedback', 'Como trabalhar (feedback)'], ['project', 'Projeto (project)'], ['reference', 'Referência (reference)']];
  const NOME_AVISO = { caminho: 'cita o que não existe', link: 'link quebrado', velha: 'velha', contradicao: 'contraditória?' };

  /* ---------- peças comuns ---------- */
  function diffEl(texto) {
    if (!texto) return h('p', { class: 'nota' }, 'Nenhuma diferença.');
    return h('pre', { class: 'saida', estilo: { maxHeight: '420px' } }, texto.split('\n').map(l => h('span', {
      estilo: { display: 'block', color: l.startsWith('+') && !l.startsWith('+++') ? 'var(--ok-text)' : l.startsWith('-') && !l.startsWith('---') ? 'var(--danger-text)' : '' },
    }, l || ' ')));
  }
  function janela(titulo, ...filhos) {
    const fechar = () => cob.remove();
    const cob = h('div', { class: 'cobertura', role: 'dialog', 'aria-label': titulo, onclick: ev => { if (ev.target === cob) fechar(); } },
      h('div', { class: 'cartao', estilo: { maxWidth: '920px', width: 'calc(100% - 32px)', textAlign: 'left', maxHeight: '90vh', overflow: 'auto' } },
        h('div', { class: 'barra', estilo: { justifyContent: 'space-between', margin: '0 0 8px' } }, h('h3', { estilo: { margin: 0 } }, titulo),
          h('button', { type: 'button', class: 'bt leve fino', onclick: fechar }, 'Fechar')), ...filhos));
    document.body.append(cob);
    UI.limpezas.push(fechar);                      // trocou de tela: a janela fecha junto
    return { cob, fechar, corpo: cob.firstChild };
  }
  /* Pede a prévia (confirmar: false), mostra a diferença e só grava no clique de "Gravar". 'pedir(confirmar)' chama a rota. */
  async function previaEConfirmar(titulo, pedir, aoGravar, nota) {
    const msg = h('div');
    const j = janela(titulo, msg);
    msg.append(h('p', { class: 'muted' }, 'Calculando a diferença…'));
    let p;
    try { p = await pedir(false); } catch (e) { trocar(msg, h('p', { class: 'msg-erro' }, e.message)); return; }
    if (p.mudou === false) { trocar(msg, h('p', { class: 'nota' }, 'Nada mudou: não há o que gravar.')); return; }
    const status = h('span', { class: 'muted' });
    const gravar = h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
      gravar.disabled = true; status.className = 'muted'; status.textContent = 'Gravando…';
      try {
        const r = await pedir(true, p);
        trocar(msg, h('p', { class: 'msg-ok' }, 'Gravado.' + (r.copia ? ' Cópia de segurança em: ' + r.copia : '')));
        if (aoGravar) aoGravar(r);
      } catch (e) {
        status.className = 'msg-erro';
        status.textContent = e.message;
        if (/mudou desde/.test(e.message)) gravar.replaceWith(h('button', { type: 'button', class: 'bt leve fino', onclick: () => { j.fechar(); if (aoGravar) aoGravar(null); } }, 'Recarregar'));
        else gravar.disabled = false;
      }
    } }, 'Gravar (com cópia de segurança antes)');
    trocar(msg, nota ? h('p', { class: 'nota' }, nota) : null, h('b', null, 'Confira a diferença (− sai, + entra):'), diffEl(p.diff || ''),
      h('div', { class: 'barra', estilo: { marginTop: '10px' } }, gravar, h('button', { type: 'button', class: 'bt leve fino', onclick: j.fechar }, 'Cancelar'), status));
  }

  /* ====================================================================================================== */
  /* Botões no leitor de uma memória: Editar / Arquivar                                                      */
  /* ====================================================================================================== */
  UI.memoriaAoAbrir = function (slug, id, leitor, ctx) {
    if (!id || !id.startsWith('mem/')) return;
    const nome = id.slice(4);
    const barra = h('div', { class: 'barra', estilo: { margin: '0 0 10px', fontFamily: 'var(--font-body, system-ui)' } },
      h('button', { type: 'button', class: 'bt leve fino', onclick: () => editar(slug, nome, ctx) }, 'Editar'),
      nome === 'MEMORY.md' ? null : h('button', { type: 'button', class: 'bt leve fino', onclick: () => arquivar(slug, nome, ctx) }, 'Arquivar'));
    leitor.prepend(barra);
  };

  async function editar(slug, nome, ctx) {
    let d;
    try { d = await api(base(slug) + '/memoria/editar?nome=' + encodeURIComponent(nome)); } catch (e) { janela('Editar ' + nome, h('p', { class: 'msg-erro' }, e.message)); return; }
    const desc = d.indice || !d.cabecalho ? null : h('input', { type: 'text', value: d.descricao, maxlength: 400, 'aria-label': 'Descrição', estilo: { width: '100%' } });
    const corpo = h('textarea', { rows: 16, 'aria-label': 'Texto', estilo: { width: '100%', fontFamily: 'var(--font-mono)', fontSize: '12.5px' } });
    corpo.value = d.corpo;
    if (d.tem_segredo) corpo.disabled = true;
    const j = janela('Editar ' + (d.indice ? 'o índice (MEMORY.md)' : d.titulo),
      h('p', { class: 'nota' }, 'Arquivo: ' + nome + (d.tipo ? ' · tipo ' + d.tipo : '') + '. Nada é gravado sem você ver a diferença e confirmar.'),
      d.tem_segredo ? h('div', { class: 'aviso-caixa', estilo: { marginBottom: '8px' } }, 'Este arquivo tem uma senha ou chave (aparece como [segredo oculto]). Por segurança o texto não é editado aqui; só a descrição. Para o resto, use um editor de texto.') : null,
      desc ? h('label', null, h('b', null, 'Descrição (o que aparece no índice e decide quando a memória é lembrada)'), desc) : null,
      h('label', null, h('b', null, d.indice ? 'Texto do índice' : 'Texto'), corpo),
      h('div', { class: 'barra', estilo: { marginTop: '10px' } }, h('button', { type: 'button', class: 'bt pri fino', onclick: () => {
        j.fechar();
        const envio = { nome, versao: d.versao };
        if (desc) envio.descricao = desc.value;
        if (!d.tem_segredo) envio.corpo = corpo.value;
        previaEConfirmar('Gravar ' + nome, confirmar => post(base(slug) + '/memoria/editar', { ...envio, confirmar }), () => ctx.recarregar(nome));
      } }, 'Ver diferença'), h('button', { type: 'button', class: 'bt leve fino', onclick: () => j.fechar() }, 'Cancelar')));
  }

  async function arquivar(slug, nome, ctx) {
    let d;
    try { d = await api(base(slug) + '/memoria/editar?nome=' + encodeURIComponent(nome)); } catch (e) { janela('Arquivar', h('p', { class: 'msg-erro' }, e.message)); return; }
    previaEConfirmar('Arquivar ' + nome, (confirmar, p) => post(base(slug) + '/memoria/arquivar',
      { nome, versao: d.versao, versao_indice: p ? p.versao_indice : null, confirmar }), () => ctx.recarregar(null),
    'Arquivar NÃO apaga: o arquivo vai para a pasta memory/_arquivo e a linha dele sai do MEMORY.md (deixa de ser lembrado nas conversas).');
  }

  /* ====================================================================================================== */
  /* Caixa "Cuidar da memória": nova memória, compactar o índice, avisos                                     */
  /* ====================================================================================================== */
  UI.memoriaExtras = function (slug, el, ctx) {
    const area = h('div');
    const nAvisos = h('span', { class: 'n' });
    el.append(h('section', { class: 'cartao', estilo: { marginBottom: '14px' } },
      h('h3', null, 'Cuidar da memória'),
      h('p', { class: 'nota', estilo: { marginTop: 0 } }, 'Criar, editar e arquivar memórias e enxugar o índice. Toda gravação mostra a diferença antes, guarda uma cópia de segurança e recusa se o Claude Code mexeu no arquivo enquanto isso.'),
      h('div', { class: 'barra' },
        h('button', { type: 'button', class: 'bt leve fino', onclick: () => novaMemoria(slug, ctx) }, '+ Nova memória'),
        h('button', { type: 'button', class: 'bt leve fino', onclick: () => compactar(slug, area, ctx) }, 'Propor compactação do índice'),
        h('button', { type: 'button', class: 'bt leve fino', onclick: () => avisos(slug, area, ctx, true) }, 'Memória a conferir ', nAvisos)),
      area));
    api(base(slug) + '/memoria/avisos').then(d => {
      nAvisos.textContent = d.total ? '(' + d.total + ')' : '(0)';
      if (d.total) avisos(slug, area, ctx, false, d);
    }).catch(() => { nAvisos.textContent = ''; });
  };

  function novaMemoria(slug, ctx) {
    const titulo = h('input', { type: 'text', maxlength: 120, placeholder: 'Ex.: Botões com 28 px', 'aria-label': 'Título', estilo: { width: '100%' } });
    const tipo = h('select', { 'aria-label': 'Tipo' }, TIPOS.map(([v, n]) => h('option', { value: v }, n)));
    const desc = h('input', { type: 'text', maxlength: 300, placeholder: 'Uma frase: quando esta memória importa', 'aria-label': 'Descrição', estilo: { width: '100%' } });
    const gancho = h('input', { type: 'text', maxlength: 160, placeholder: '(opcional) texto curto da linha no índice; vazio = a descrição', 'aria-label': 'Gancho', estilo: { width: '100%' } });
    const corpo = h('textarea', { rows: 6, 'aria-label': 'Texto', placeholder: 'O fato, a regra ou a preferência', estilo: { width: '100%' } });
    const porque = h('input', { type: 'text', maxlength: 1000, placeholder: 'Por quê (vira a linha **Why:**)', 'aria-label': 'Por quê', estilo: { width: '100%' } });
    const como = h('input', { type: 'text', maxlength: 1000, placeholder: 'Como aplicar (vira a linha **How to apply:**)', 'aria-label': 'Como aplicar', estilo: { width: '100%' } });
    const extra = h('div', null, porque, h('div', { estilo: { height: '6px' } }), como);
    const mostrarExtra = () => { extra.style.display = ['feedback', 'project'].includes(tipo.value) ? '' : 'none'; };
    tipo.addEventListener('change', mostrarExtra);
    tipo.value = 'feedback';
    mostrarExtra();
    const j = janela('Nova memória',
      h('p', { class: 'nota' }, 'Cria um arquivo na pasta de memória do projeto e acrescenta uma linha no MEMORY.md (o índice que toda conversa lê). Não guarde senhas nem chaves aqui.'),
      h('label', null, h('b', null, 'Título'), titulo), h('label', null, h('b', null, 'Tipo '), tipo),
      h('label', null, h('b', null, 'Descrição'), desc), h('label', null, h('b', null, 'Texto'), corpo), extra,
      h('label', null, h('b', null, 'Linha no índice'), gancho),
      h('div', { class: 'barra', estilo: { marginTop: '10px' } }, h('button', { type: 'button', class: 'bt pri fino', onclick: () => {
        const envio = { titulo: titulo.value, tipo: tipo.value, descricao: desc.value, corpo: corpo.value, porque: porque.value, como_aplicar: como.value, gancho: gancho.value };
        j.fechar();
        previaEConfirmar('Criar memória', (confirmar, p) => post(base(slug) + '/memoria/criar', { ...envio, versao_indice: p ? p.versao_indice : null, confirmar }),
          r => ctx.recarregar(r && r.nome));
      } }, 'Ver diferença'), h('button', { type: 'button', class: 'bt leve fino', onclick: () => j.fechar() }, 'Cancelar')));
  }

  async function compactar(slug, area, ctx) {
    trocar(area, h('p', { class: 'muted' }, 'Montando a proposta (sem IA, por regras)…'));
    let p;
    try { p = await api(base(slug) + '/memoria/compactar'); } catch (e) { trocar(area, h('p', { class: 'msg-erro' }, e.message)); return; }
    const v = p.verificacao;
    const NOMES = { encurtado: 'ganchos encurtados', duplicada: 'linhas duplicadas juntadas' };
    const pode = v.ok && !p.igual && p.economia > 0;
    const gravar = h('button', { type: 'button', class: 'bt pri fino', disabled: !pode, onclick: () => previaEConfirmar('Aplicar a compactação',
      confirmar => post(base(slug) + '/memoria/compactar', { versao: p.versao, confirmar }), () => { ctx.recarregar('MEMORY.md'); trocar(area); }) }, 'Aplicar…');
    trocar(area, h('div', { class: 'cartao', estilo: { marginTop: '10px', background: 'var(--bg-2)' } },
      h('div', { class: 'barra', estilo: { justifyContent: 'space-between' } },
        h('b', { estilo: { fontSize: '16px' } }, '≈ ' + num(p.tokens_antes) + ' → ≈ ' + num(p.tokens_depois) + ' tokens por conversa'),
        h('span', { class: 'chip ' + (p.economia > 0 ? 'ok' : '') }, p.economia > 0 ? 'economia ≈ ' + num(p.economia) + ' (' + String(p.pct).replace('.', ',') + '%)' : 'nada a ganhar')),
      h('p', { class: 'nota' }, Object.entries(p.contagem).map(([k, n]) => n + ' ' + (NOMES[k] || k)).join(' · ') || 'Nenhuma mudança proposta.'),
      h('b', null, 'Verificador das garantias'),
      h('ul', { class: 'lista linha-tempo' }, v.checagens.map(c => h('li', null, h('span', { class: 'chip ' + (c.ok ? 'ok' : 'perigo') }, c.ok ? 'ok' : 'falhou'), ' ', h('b', null, c.nome), ' — ', h('span', { class: 'muted' }, c.detalhe)))),
      h('details', null, h('summary', null, 'Palavras que protegem a linha inteira (' + p.palavras_regra.length + ')'), h('p', { class: 'nota' }, p.palavras_regra.join(', '))),
      p.apontamentos.sem_arquivo.length || p.apontamentos.sem_linha.length ? h('div', { class: 'aviso-caixa', estilo: { margin: '8px 0' } },
        h('b', null, 'A conferir (a proposta não mexe nisso): '),
        p.apontamentos.sem_arquivo.map(x => h('div', null, 'linha ' + x.linha + ' aponta para ' + x.alvo + ', que não existe')),
        p.apontamentos.sem_linha.map(n => h('div', null, n + ' não tem linha no índice (não é lembrado nas conversas)'))) : null,
      h('div', { class: 'duas', estilo: { marginTop: '8px' } },
        h('div', null, h('b', null, 'Antes'), h('pre', { class: 'saida' }, p.antes)),
        h('div', null, h('b', null, 'Depois'), h('pre', { class: 'saida' }, p.depois))),
      h('div', { class: 'barra', estilo: { marginTop: '10px' } }, gravar, h('button', { type: 'button', class: 'bt leve fino', onclick: () => trocar(area) }, 'Fechar'),
        v.ok ? null : h('span', { class: 'msg-erro' }, 'O verificador falhou: a proposta não pode ser aplicada.'))));
  }

  async function avisos(slug, area, ctx, forcar, pronto) {
    let d = pronto;
    if (!d) {
      trocar(area, h('p', { class: 'muted' }, 'Conferindo a memória…'));
      try { d = await api(base(slug) + '/memoria/avisos' + (forcar ? '?forcar=1' : '')); } catch (e) { trocar(area, h('p', { class: 'msg-erro' }, e.message)); return; }
    }
    trocar(area, h('div', { estilo: { marginTop: '10px' } },
      h('p', { class: 'nota' }, d.nota + ' Memória "velha" = fala de estado e não muda há ' + d.dias_velha + ' dias.'),
      d.avisos.length ? h('ul', { class: 'lista linha-tempo' }, d.avisos.map(a => h('li', { class: a.arquivos[0].startsWith('mem/') ? 'clicavel' : '', onclick: a.arquivos[0].startsWith('mem/') ? () => ctx.abrir(a.arquivos[0], a.titulo) : null },
        h('span', { class: 'chip warn' }, 'a conferir'), ' ', h('span', { class: 'chip' }, NOME_AVISO[a.tipo] || a.tipo), ' ', h('b', null, a.titulo),
        h('div', { class: 'muted', estilo: { fontSize: '12.5px', flexBasis: '100%' } }, a.motivo), a.trecho ? h('div', { class: 'mono muted', estilo: { fontSize: '11.5px', flexBasis: '100%', overflowWrap: 'anywhere' } }, a.trecho) : null)))
        : h('div', { class: 'vazio' }, 'Nenhum aviso: nada parece velho ou contraditório.'),
      d.total > d.avisos.length ? h('p', { class: 'nota' }, '+ ' + (d.total - d.avisos.length) + ' outros avisos não mostrados.') : null));
  }

  /* ====================================================================================================== */
  /* Decisões registradas: editar (vira uma nova, a antiga fica como substituída) e arquivar                 */
  /* ====================================================================================================== */
  UI.decisaoAcoes = function (slug, x, recarregar) {
    if (x.estado && x.estado !== 'ativa') return h('span', { class: 'chip', title: x.mudou_em ? 'em ' + dataCurta(x.mudou_em) : '' }, x.estado === 'arquivada' ? 'arquivada' : 'substituída');
    const mudar = (acao, extra, titulo, nota) => previaEConfirmar(titulo, async confirmar => {
      const r = await post(base(slug) + '/decisoes/' + encodeURIComponent(x.did), { acao, confirmar, ...extra });
      return { ...r, diff: '- ' + r.antes + '\n+ ' + r.depois };
    }, () => recarregar(), nota);
    return h('span', { class: 'barra', estilo: { margin: 0, flexWrap: 'nowrap' }, onclick: ev => ev.stopPropagation() },
      h('button', { type: 'button', class: 'bt leve fino', title: 'Editar: grava a versão nova e marca esta como substituída (nada é apagado)', onclick: () => {
        const campo = h('input', { type: 'text', value: x.texto, maxlength: 2000, 'aria-label': 'Novo texto', estilo: { width: '100%' } });
        const j = janela('Editar decisão', campo, h('div', { class: 'barra', estilo: { marginTop: '10px' } },
          h('button', { type: 'button', class: 'bt pri fino', onclick: () => { j.fechar(); mudar('editar', { texto: campo.value }, 'Editar decisão', 'A decisão antiga continua guardada, marcada como substituída.'); } }, 'Ver diferença'),
          h('button', { type: 'button', class: 'bt leve fino', onclick: () => j.fechar() }, 'Cancelar')));
      } }, 'Editar'),
      h('button', { type: 'button', class: 'bt leve fino', onclick: () => mudar('arquivar', {}, 'Arquivar decisão', 'Arquivar não apaga: a linha continua no arquivo, só sai da linha do tempo ativa.') }, 'Arquivar'));
  };

  /* ====================================================================================================== */
  /* Sessões: aviso de conversa longa + resumo de passa-bastão                                               */
  /* ====================================================================================================== */
  UI.sessaoBastao = function (slug, s) {
    const b = s.bastao;
    if (!b || !b.longa) return null;
    return h('div', { estilo: { marginTop: '4px' } },
      h('span', { class: 'chip warn', title: '≈ ' + num(b.contexto) + ' tokens de contexto no último turno (' + String(b.pct).replace('.', ',') + '% da janela)' }, 'Conversa longa — passar o bastão'), ' ',
      h('button', { type: 'button', class: 'bt leve fino', onclick: () => gerarBastao(slug, s.id) }, 'Gerar resumo'));
  };

  async function gerarBastao(slug, sessao) {
    const j = janela('Passa-bastão', h('p', { class: 'muted' }, 'Montando o resumo (sem IA)…'));
    let r;
    try { r = await post(base(slug) + '/bastao', { sessao }); } catch (e) { trocar(j.corpo, h('p', { class: 'msg-erro' }, e.message)); return; }
    const texto = h('textarea', { rows: 20, readonly: true, 'aria-label': 'Resumo', estilo: { width: '100%', fontFamily: 'var(--font-mono)', fontSize: '12.5px' } });
    texto.value = r.texto;
    const ok = h('span', { class: 'msg-ok' });
    trocar(j.corpo, h('div', { class: 'barra', estilo: { justifyContent: 'space-between', margin: '0 0 8px' } }, h('h3', { estilo: { margin: 0 } }, 'Passa-bastão'),
      h('button', { type: 'button', class: 'bt leve fino', onclick: j.fechar }, 'Fechar')),
      h('p', { class: 'nota' }, 'Copie e cole no começo de uma conversa nova. Senhas e chaves já saem escondidas. Guardado também em: ' + r.arquivo),
      texto, h('div', { class: 'barra', estilo: { marginTop: '8px' } }, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
        try { await navigator.clipboard.writeText(r.texto); ok.textContent = 'Copiado.'; } catch (e) { texto.select(); ok.textContent = 'Selecionado: use Ctrl+C.'; }
      } }, 'Copiar'), ok));
  }
})();
