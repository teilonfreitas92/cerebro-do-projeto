/* Cérebro do Projeto — aba Inventário e seções extras de Configurações (agentes por tipo de tarefa, departamentos do mapa).
   Nada que vem de arquivos ou conversas entra na página como HTML: tudo é criado com h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, haQuanto, api, post } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);

  /* ====================================================================================================== */
  /* Inventário e plano de encaixe (aplicar: encaixe.js)                                                        */
  /* ====================================================================================================== */
  UI.telas.inventario = function abaInventario(slug, el) {
    el.append(h('div', { class: 'vazio' }, 'Lendo o projeto…'));
    const ESTADO = { ja_existe: ['ok', 'já existe · será respeitado'], acrescentar: ['accent', 'o Cérebro acrescentaria'], opcional: ['', 'opcional'] };
    api(base(slug) + '/inventario').then(d => {
      const grupos = {};
      d.itens.forEach(i => { (grupos[i.grupo] = grupos[i.grupo] || []).push(i); });
      trocar(el,
        h('div', { class: 'aviso-caixa info', estilo: { marginBottom: '14px' } }, 'O Cérebro LÊ o projeto e mostra o que já existe e como se encaixaria. Nada muda sozinho: cada item mostra antes os arquivos e a diferença, e só é aplicado quando você confere e clica em Aplicar. O Cérebro só cria arquivos novos ou acrescenta um bloco marcado, guarda cópia de tudo que toca e permite desfazer.'),
        h('div', { class: 'duas' },
          h('section', { class: 'cartao' }, h('h3', null, 'O que o projeto já tem'),
            Object.entries(grupos).map(([g, itens]) => h('div', { class: 'grupo-inv' }, h('small', { class: 'muted' }, g),
              itens.map(i => h('div', { class: 'item-inv', title: i.caminho || '' }, h('span', { class: 'chip ' + (i.existe ? 'ok' : '') }, i.existe ? 'tem' : 'não tem'), h('b', null, i.nome), h('span', { class: 'muted' }, i.detalhe)))))),
          h('section', { class: 'cartao' }, h('h3', null, 'Plano de encaixe sugerido'),
            d.plano.map(p => h('div', { class: 'plano' },
              h('div', { class: 'topo-conf' }, h('b', { class: 'tit-conf' }, p.titulo), h('span', { class: 'chip ' + (ESTADO[p.estado] || ['', ''])[0] }, (ESTADO[p.estado] || ['', p.estado])[1])),
              h('p', { class: 'motivo' }, p.o_que), h('p', { class: 'nota' }, p.porque),
              p.texto ? h('pre', { class: 'saida pequeno' }, p.texto) : null,
              UI.botaoEncaixe ? UI.botaoEncaixe(slug, p, () => UI.telas.inventario(slug, el)) : null)))),
        UI.rodapeEncaixe ? UI.rodapeEncaixe(slug, () => UI.telas.inventario(slug, el)) : null);
    }).catch(e => el.replaceChildren(h('div', { class: 'vazio' }, e.message)));
  };

  /* ====================================================================================================== */
  /* Configurações: agentes por tipo de tarefa                                                               */
  /* ====================================================================================================== */
  UI.secoesConfig.push(({ slug, c, dizer, montar }) => {
    const regras = (c.agentes_regras || []).map(r => ({ ...r, palavras: (r.palavras || []).join(', ') }));
    const corpo = h('tbody');
    const secao = h('section', { class: 'cartao secao rolagem-x' });
    const previa = h('div');
    const desenhar = () => {
      corpo.replaceChildren(...regras.map(r => h('tr', null,
        h('td', null, h('input', { type: 'text', value: r.id, 'aria-label': 'Identificador', class: 'modelo-in', oninput: e => { r.id = e.target.value.trim().toLowerCase(); } })),
        h('td', null, h('input', { type: 'text', value: r.nome, 'aria-label': 'Tipo de tarefa', class: 'largo', oninput: e => { r.nome = e.target.value; } })),
        h('td', null, h('select', { 'aria-label': 'Modelo', onchange: e => { r.modelo = e.target.value; } }, ['haiku', 'sonnet', 'opus'].map(m => h('option', { value: m, selected: m === r.modelo }, m)))),
        h('td', null, h('input', { type: 'text', value: r.revisor, 'aria-label': 'Quem revisa', class: 'largo', oninput: e => { r.revisor = e.target.value; } })),
        h('td', null, h('textarea', { rows: 3, 'aria-label': 'Palavras-chave', class: 'palavras', oninput: e => { r.palavras = e.target.value; } }, r.palavras)),
        h('td', null, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { regras.splice(regras.indexOf(r), 1); desenhar(); } }, 'Remover')))));
    };
    desenhar();
    const mostrarPrevia = p => {
      previa.replaceChildren(...(p ? [h('div', null, h('p', { class: 'nota' }, 'Prévia gravada em ', h('code', null, p.pasta), '. Nada foi copiado para o projeto: ' + (p.como_aplicar || 'copiar para .claude/agents precisa da sua aprovação.')),
        p.arquivos.map(a => h('details', { class: 'cartao' }, h('summary', null, a.arquivo), h('pre', { class: 'saida pequeno' }, a.texto))))] : []));
    };
    if (slug) api(base(slug) + '/agentes/previa').then(r => mostrarPrevia(r.previa)).catch(() => {});
    secao.append(h('h3', null, 'Agentes por tipo de tarefa'),
      h('p', { class: 'nota' }, 'Tipo de tarefa → modelo → quem revisa. O Cérebro compara a descrição que o gestor deu a cada subagente com as palavras-chave (a primeira linha que casar vale, então deixe o mais arriscado em cima) e mostra a regra aplicada em Agentes ao vivo. TODO resultado passa pelo gestor, qualquer que seja o tipo: a regra só escolhe o modelo certo para cada tarefa.'),
      h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Id', 'Tipo de tarefa', 'Modelo', 'Quem revisa', 'Palavras-chave (vírgula)', ''].map(t => h('th', null, t)))), corpo),
      h('div', { class: 'linha-cfg' },
        h('button', { type: 'button', class: 'bt leve fino', onclick: () => { regras.push({ id: 'novo-tipo', nome: 'Novo tipo de tarefa', modelo: 'sonnet', revisor: 'Gestor confere o resultado', palavras: '' }); desenhar(); } }, 'Adicionar tipo'),
        h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          try { await post('/api/config', { agentes_regras: regras }); dizer('Tabela de agentes salva.'); } catch (e) { dizer(e.message, false); }
        } }, 'Salvar tabela'),
        slug ? h('button', { type: 'button', class: 'bt leve fino', title: 'Gera os arquivos .claude/agents/*.md sugeridos numa pasta de prévia do Cérebro (não dentro do projeto)', onclick: async () => {
          try { await post('/api/config', { agentes_regras: regras }); const r = await post(base(slug) + '/agentes/previa', {}); mostrarPrevia(r.previa); dizer('Prévia gerada.'); } catch (e) { dizer(e.message, false); }
        } }, 'Gerar prévia dos arquivos de agentes') : null),
      previa);
    return secao;
  });

  /* ====================================================================================================== */
  /* Configurações: departamentos do mapa                                                                    */
  /* ====================================================================================================== */
  UI.secoesConfig.push(({ slug, dizer }) => {
    if (!slug) return null;
    const secao = h('section', { class: 'cartao secao rolagem-x' }, h('h3', null, 'Departamentos do mapa (cores e grupos)'), h('div', { class: 'vazio' }, 'Carregando…'));
    api(base(slug) + '/departamentos').then(d => {
      const atual = d.atual || { modo: 'pastas' };
      let modo = atual.modo;
      const deptos = (atual.deptos || []).map(x => ({ nome: x.nome, cor: x.cor, caminhos: (x.caminhos || []).join(', '), ancora: x.ancora }));
      if (!deptos.length) deptos.push({ nome: 'Departamento 1', cor: d.cores[0], caminhos: '' });
      const padrao = h('input', { type: 'text', value: atual.padrao || 'Outros', 'aria-label': 'Departamento dos arquivos sem regra' });
      const corpo = h('tbody');
      const desenharRegras = () => {
        corpo.replaceChildren(...deptos.map(x => h('tr', null,
          h('td', null, h('input', { type: 'text', value: x.nome, 'aria-label': 'Nome do departamento', oninput: e => { x.nome = e.target.value; } })),
          h('td', null, h('input', { type: 'color', value: x.cor, 'aria-label': 'Cor', oninput: e => { x.cor = e.target.value; } })),
          h('td', null, h('input', { type: 'text', value: x.caminhos, class: 'largo', 'aria-label': 'Caminhos', placeholder: 'src/, *.test.js, docs', oninput: e => { x.caminhos = e.target.value; } })),
          h('td', null, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { deptos.splice(deptos.indexOf(x), 1); desenharRegras(); } }, 'Remover')))));
      };
      desenharRegras();
      const bloco = h('div');
      const radio = (valor, rotulo, desabilitado) => h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'modo-depto', checked: modo === valor, disabled: !!desabilitado, onchange: () => { modo = valor; bloco.hidden = modo !== 'regras'; } }), rotulo);
      bloco.append(h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Departamento', 'Cor', 'Caminhos (o primeiro que casar vale)', ''].map(t => h('th', null, t)))), corpo),
        h('div', { class: 'linha-cfg' }, h('button', { type: 'button', class: 'bt leve fino', onclick: () => { deptos.push({ nome: 'Departamento ' + (deptos.length + 1), cor: d.cores[deptos.length % d.cores.length], caminhos: '' }); desenharRegras(); } }, 'Adicionar departamento'),
          h('label', null, 'Arquivos sem regra vão para ', padrao)));
      bloco.hidden = modo !== 'regras';
      secao.replaceChildren(h('h3', null, 'Departamentos do mapa (cores e grupos)'),
        h('p', { class: 'nota' }, 'Define como os arquivos do projeto são divididos e coloridos no mapa. Caminho: "programa/" (começa por), "*.test.js" (curinga) ou "chat" (contém). Para quem precisa de mais controle: "re:^src/.*\\.ts$" (expressão regular).'),
        h('div', { class: 'linha-cfg' }, radio('pastas', 'Automático, pelas pastas de primeiro nível'), radio('regras', 'Minhas regras')),
        bloco, h('div', { class: 'linha-cfg' }, h('button', { type: 'button', class: 'bt pri fino', onclick: async () => {
          try {
            const conf = modo === 'regras' ? { modo, padrao: padrao.value, deptos: deptos.map(x => ({ nome: x.nome, cor: x.cor, caminhos: x.caminhos, ancora: x.ancora })) } : { modo };
            await post(base(slug) + '/departamentos', { conf });
            dizer('Departamentos salvos. A página do mapa está sendo refeita.');
          } catch (e) { dizer(e.message, false); }
        } }, 'Salvar e refazer o mapa')));
    }).catch(e => secao.replaceChildren(h('h3', null, 'Departamentos do mapa'), h('div', { class: 'vazio' }, e.message)));
    return secao;
  });
})();
