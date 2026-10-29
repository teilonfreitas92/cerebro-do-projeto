/* Cérebro do Projeto — telas de confirmação do que ESCREVE num projeto ou instala programas:
   aplicar o plano de encaixe (aba Inventário), copiar os agentes para .claude/agents, ligar o gitleaks no pre-commit e
   instalar ferramentas (aba Ferramentas). Nada roda sozinho: cada ação mostra antes o que vai acontecer e só segue depois que
   a pessoa marca "conferi" e clica. Tudo que vem do servidor entra na página só por h() / textContent. */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, trocar, api, post, dataCurta } = UI;
  const base = slug => '/api/p/' + encodeURIComponent(slug);
  const TIPO = { criar: ['ok', 'arquivo novo'], alterar: ['warn', 'acrescenta'], retirar: ['warn', 'vai para a pasta de cópias'], pular: ['', 'não mexe'] };
  const ACAO_DO_PLANO = { instrucoes: 'instrucoes', agentes: 'agentes', segredos: 'segredos', qualidade: 'qualidade', dependencias: 'dependencias' };

  function caixaConfirmar(rotulo, aoMudar) {
    return h('label', { class: 'chk' }, h('input', { type: 'checkbox', onchange: e => aoMudar(e.target.checked) }), rotulo);
  }

  /* ------------------------------------------------------------------------------------------------------ */
  /* Plano de encaixe: um painel por item, com prévia, opções e Aplicar                                     */
  /* ------------------------------------------------------------------------------------------------------ */
  function painelAcao(slug, acao, aoTerminar) {
    const caixa = h('div', { class: 'cartao', estilo: { marginTop: '8px' } }, h('div', { class: 'vazio' }, 'Montando a prévia…'));
    const opcoes = {};
    async function carregar() {
      const q = new URLSearchParams({ acao });
      Object.entries(opcoes).forEach(([k, v]) => q.set(k, v));
      let pv;
      try { pv = await api(base(slug) + '/encaixe/previa?' + q.toString()); } catch (e) { trocar(caixa, h('p', { class: 'msg-erro' }, e.message)); return; }
      let conferiu = false;
      const msg = h('p', { class: 'nota' });
      const bAplicar = h('button', { type: 'button', class: 'bt pri fino', disabled: true, onclick: async () => {
        bAplicar.disabled = true; msg.textContent = 'Aplicando…';
        try {
          const r = await post(base(slug) + '/encaixe/aplicar', { acao, assinatura: pv.assinatura, confirmar: true, opcoes });
          msg.className = 'msg-ok';
          msg.textContent = r.nada_a_fazer ? 'Nada a fazer: já estava aplicado.' : 'Aplicado. Cópias de segurança em ' + r.copia + '. Dá para desfazer logo abaixo.';
          if (aoTerminar) setTimeout(aoTerminar, 1500);
        } catch (e) { msg.className = 'msg-erro'; msg.textContent = e.message; }
      } }, 'Aplicar');
      const extras = [];
      if (acao === 'agentes') {
        extras.push(h('div', { class: 'linha-cfg' }, h('small', { class: 'muted' }, 'Se já existir um agente com o mesmo nome e conteúdo diferente: '),
          ['pular', 'cerebro_md'].map(v => h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'conflito-' + slug, checked: (opcoes.conflito || 'pular') === v,
            onchange: () => { opcoes.conflito = v; carregar(); } }), v === 'pular' ? 'pular (não mexe no seu)' : 'gravar a versão do Cérebro ao lado (.cerebro.md)'))));
      }
      const modos = (pv.modos || []).filter(m => m !== 'tirar');
      if (acao === 'segredos' && modos.length > 1) {
        extras.push(h('div', { class: 'linha-cfg' }, h('small', { class: 'muted' }, 'Como ligar: '),
          modos.map(m => h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'modo-' + slug, checked: (opcoes.modo || modos[0]) === m,
            onchange: () => { opcoes.modo = m; carregar(); } }), { config: 'acrescentar ao .pre-commit-config.yaml', encadear: 'encadear com o gancho que já existe', novo: 'gancho novo' }[m] || m))));
      }
      trocar(caixa,
        h('b', null, pv.titulo), h('p', { class: 'nota' }, pv.resumo || ''),
        extras,
        pv.arquivos.map(a => h('div', { class: 'plano' },
          h('div', { class: 'topo-conf' }, h('span', { class: 'chip ' + (TIPO[a.tipo] || ['', ''])[0] }, (TIPO[a.tipo] || ['', a.tipo])[1]), h('code', null, a.rel)),
          h('p', { class: 'nota' }, a.nota),
          a.diff ? h('details', { open: a.tipo !== 'pular' }, h('summary', null, a.tipo === 'pular' ? 'ver a diferença' : 'o que muda (diferença)'), h('pre', { class: 'saida pequeno', estilo: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' } }, a.diff)) : null)),
        pv.aplicavel
          ? h('div', null,
            h('p', { class: 'muted' }, 'Antes de mexer, o Cérebro guarda uma cópia de cada arquivo tocado em ' + pv.copias + '. Arquivo novo que for desfeito vai para lá (nada é apagado).'),
            caixaConfirmar('Conferi os arquivos e a diferença acima', v => { conferiu = v; bAplicar.disabled = !conferiu; }),
            h('div', { class: 'acoes-conf' }, bAplicar, h('button', { type: 'button', class: 'bt leve fino', onclick: () => caixa.remove() }, 'Cancelar')))
          : h('div', null, h('p', { class: 'muted' }, 'Nada a aplicar aqui.'), h('button', { type: 'button', class: 'bt leve fino', onclick: () => caixa.remove() }, 'Fechar')),
        msg);
    }
    carregar();
    return caixa;
  }

  /* Botão de cada item do plano (substitui o antigo "Aplicar" desabilitado) */
  UI.botaoEncaixe = (slug, item, recarregar) => {
    const acao = ACAO_DO_PLANO[item.id];
    if (!acao) return null;
    const lugar = h('div');
    const abrir = a => { lugar.replaceChildren(painelAcao(slug, a, recarregar)); };
    return h('div', null,
      h('div', { class: 'acoes-conf' },
        h('button', { type: 'button', class: 'bt leve fino', title: 'Mostra exatamente o que mudaria no projeto; nada muda sem o seu clique em Aplicar', onclick: () => abrir(acao) }, 'Ver o que muda e aplicar…'),
        acao === 'segredos' ? h('button', { type: 'button', class: 'bt leve fino', title: 'Tira só o que é do Cérebro (pelo marcador)', onclick: () => abrir('segredos-tirar') }, 'Tirar o gancho do Cérebro…') : null),
      lugar);
  };

  /* Rodapé da aba Inventário: últimas aplicações e "Desfazer a última" */
  UI.rodapeEncaixe = (slug, recarregar) => {
    const secao = h('section', { class: 'cartao', estilo: { marginTop: '14px' } }, h('h3', null, 'Aplicações neste projeto'), h('div', { class: 'vazio' }, 'Carregando…'));
    api(base(slug) + '/encaixe').then(d => {
      if (d.bloqueado) { trocar(secao, h('h3', null, 'Aplicações neste projeto'), h('div', { class: 'aviso-caixa' }, 'O Cérebro não escreve neste projeto: ' + d.bloqueado)); return; }
      let conferiu = false, aceite = null, viuDiferenca = false;
      const msg = h('p', { class: 'nota' });
      const mexidos = h('div');                         /* arquivos que o dono mexeu depois da aplicação (com a diferença) */
      const liberar = () => { bDesfazer.disabled = !conferiu || (aceite !== null && !viuDiferenca); };
      const bDesfazer = h('button', { type: 'button', class: 'bt leve fino', disabled: true, onclick: async () => {
        bDesfazer.disabled = true;
        try {
          const r = await post(base(slug) + '/encaixe/desfazer', viuDiferenca && aceite ? { confirmar: true, aceitar_mexidos: aceite } : { confirmar: true });
          msg.className = 'msg-ok'; msg.textContent = 'Desfeito: ' + r.titulo + '. ' + r.feito.join(' · ');
          setTimeout(recarregar, 1500);
        } catch (e) { msg.className = 'msg-erro'; msg.textContent = e.message; }
      } }, 'Desfazer a última aplicação');
      trocar(secao, h('h3', null, 'Aplicações neste projeto'),
        d.historico.length ? h('table', { class: 'tabela' }, h('thead', null, h('tr', null, ['Quando', 'O quê', 'Arquivos', 'Situação'].map(t => h('th', null, t)))),
          h('tbody', null, d.historico.map(x => h('tr', null, h('td', null, dataCurta(x.em)), h('td', null, x.titulo),
            h('td', { class: 'tit', title: x.operacoes.map(o => o.rel).join(', ') }, x.operacoes.map(o => o.rel).join(', ')),
            h('td', null, h('span', { class: 'chip ' + (x.desfeita ? '' : 'ok') }, x.desfeita ? 'desfeita' : 'aplicada'))))))
          : h('p', { class: 'muted' }, 'Nada aplicado ainda.'),
        d.pode_desfazer ? h('div', null, mexidos, caixaConfirmar('Quero voltar a última aplicação (arquivo criado vai para a pasta de cópias; o que mudou volta à cópia)', v => { conferiu = v; liberar(); }),
          h('div', { class: 'acoes-conf' }, bDesfazer)) : null,
        msg);
      if (d.pode_desfazer) {
        api(base(slug) + '/encaixe/desfazer').then(pv => {
          if (!pv.mexidos.length) return;
          aceite = pv.assinatura_mexidos;
          trocar(mexidos, h('div', { class: 'aviso-caixa', estilo: { margin: '8px 0' } },
            h('b', null, 'Atenção: estes arquivos mudaram depois da aplicação (você ou outro programa mexeu). Desfazer troca o que está lá agora:'),
            pv.mexidos.map(m => h('div', null, h('b', null, m.rel), ' — ' + m.motivo, h('pre', { class: 'saida' }, m.diff || '(sem diferença de texto)'))),
            caixaConfirmar('Vi a diferença: quero desfazer mesmo assim (a versão de agora vai para a pasta de cópias)', v => { viuDiferenca = v; liberar(); })));
          liberar();
        }).catch(e => { msg.className = 'msg-erro'; msg.textContent = e.message; });
      }
    }).catch(e => trocar(secao, h('h3', null, 'Aplicações neste projeto'), h('div', { class: 'vazio' }, e.message)));
    return secao;
  };

  /* ------------------------------------------------------------------------------------------------------ */
  /* Instalar ferramenta (aba Ferramentas)                                                                  */
  /* ------------------------------------------------------------------------------------------------------ */
  const cartoesInstalar = {};          // a aba Ferramentas se redesenha a cada 20 s: o mesmo elemento volta, com a confirmação aberta
  UI.extraFerramenta = (slug, f, instalacao, recarregar) => {
    const inst = (instalacao || {})[f.id];
    const chave = slug + '|' + f.id;
    if (f.instalada || !inst || !inst.disponivel) { delete cartoesInstalar[chave]; return null; }
    if (cartoesInstalar[chave]) return cartoesInstalar[chave];
    const lugar = h('div');
    const abrir = async () => {
      lugar.replaceChildren(h('div', { class: 'vazio' }, 'Montando a prévia…'));
      let pv;
      try { pv = await api(base(slug) + '/ferramentas/instalar?id=' + encodeURIComponent(f.id)); } catch (e) { lugar.replaceChildren(h('p', { class: 'msg-erro' }, e.message)); return; }
      let conferiu = false, termos = !pv.precisa_termos;
      const msg = h('p', { class: 'nota' });
      const bInstalar = h('button', { type: 'button', class: 'bt pri fino', disabled: true, onclick: async () => {
        bInstalar.disabled = true; msg.textContent = 'Instalando… acompanhe no histórico abaixo.';
        try { await post(base(slug) + '/ferramentas/instalar', { id: f.id, confirmar: true, aceitar_termos: pv.precisa_termos && termos }); msg.className = 'msg-ok'; msg.textContent = 'Instalação iniciada.'; setTimeout(recarregar, 800); }
        catch (e) { msg.className = 'msg-erro'; msg.textContent = e.message; }
      } }, 'Confirmar e instalar');
      const atualizar = () => { bInstalar.disabled = !(conferiu && termos); };
      lugar.replaceChildren(h('div', { class: 'cartao', estilo: { marginTop: '8px' } },
        h('b', null, 'Instalar ' + pv.nome),
        h('p', { class: 'nota' }, 'Comando exato (roda sem shell, sem janela):'),
        h('pre', { class: 'saida pequeno', estilo: { whiteSpace: 'pre-wrap', wordBreak: 'break-all' } }, pv.comando),
        h('p', { class: 'nota' }, 'De onde vem: ' + pv.de_onde),
        h('p', { class: 'nota' }, 'Onde instala: ' + pv.onde),
        h('p', { class: 'nota' }, 'Tamanho: ' + pv.tamanho + ' · tempo: ' + pv.tempo + ' (interrompe depois de ' + Math.round(pv.limite / 60) + ' min)'),
        pv.aviso ? h('div', { class: 'aviso-caixa' }, pv.aviso) : null,
        pv.precisa_termos ? caixaConfirmar('Aceito os termos do repositório do winget e do pacote (o winget exige)', v => { termos = v; atualizar(); }) : null,
        caixaConfirmar('Conferi o comando e quero instalar', v => { conferiu = v; atualizar(); }),
        h('div', { class: 'acoes-conf' }, bInstalar, h('button', { type: 'button', class: 'bt leve fino', onclick: () => lugar.replaceChildren() }, 'Cancelar')),
        msg));
    };
    cartoesInstalar[chave] = h('div', null, h('button', { type: 'button', class: 'bt leve fino', title: 'Mostra o comando, de onde vem e o tamanho antes de instalar', onclick: abrir }, 'Instalar…'), lugar);
    return cartoesInstalar[chave];
  };
})();
