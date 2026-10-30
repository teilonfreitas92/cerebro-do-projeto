/* Cérebro do Projeto — Configurações › "Outras IAs": chaves e modelos da OpenAI, DeepSeek, Grok e Gemini, que o gestor
   comanda como subagentes (python cerebro_cli.py ia rodar ...). A chave só entra: a tela nunca recebe a chave de volta,
   só se ela existe e os 4 últimos caracteres. Tudo na tela é criado com h()/textContent (nunca HTML com dado). */
(() => {
  'use strict';
  const UI = window.CerebroUI;
  const { h, api, post } = UI;

  /* "Remover" pede um segundo clique (como os botões do Backup) */
  function botaoRemover(acao) {
    let armado = false;
    const b = h('button', { type: 'button', class: 'bt leve fino', onclick: async () => {
      if (!armado) { armado = true; b.textContent = 'Clique de novo para remover'; setTimeout(() => { armado = false; b.textContent = 'Remover'; }, 5000); return; }
      armado = false; b.textContent = 'Remover'; await acao();
    } }, 'Remover');
    return b;
  }

  UI.secoesConfig.push(({ dizer }) => {
    const titulo = () => h('h3', null, 'Outras IAs (OpenAI, DeepSeek, Grok, Gemini)');
    const secao = h('section', { class: 'cartao secao' }, titulo(), h('div', { class: 'vazio' }, 'Carregando…'));

    function linha(i, redesenhar) {
      const chave = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false', maxlength: 400,
        placeholder: i.configurada ? 'chave salva (…' + i.final + '); cole outra para trocar' : 'cole aqui a chave da ' + i.nome,
        'aria-label': 'Chave da ' + i.nome, estilo: { flex: 1, minWidth: '220px' } });
      const modelo = h('input', { type: 'text', value: i.modelo, maxlength: 80, 'aria-label': 'Modelo da ' + i.nome,
        title: 'Modelo usado (padrão: ' + i.modelo_padrao + '). Vazio volta ao padrão.', estilo: { width: '170px' } });
      const salvar = async () => {
        try {
          if (chave.value.trim()) await post('/api/ias/chave', { ia: i.id, chave: chave.value.trim() });
          if (modelo.value.trim() !== i.modelo) await post('/api/ias/modelo', { ia: i.id, modelo: modelo.value.trim() });
          chave.value = '';
          dizer(i.nome + ': salvo.');
          redesenhar();
        } catch (e) { dizer(e.message, false); }
      };
      return h('div', { class: 'linha-cfg' },
        h('b', { estilo: { minWidth: '130px' } }, i.nome),
        h('span', { class: 'chip ' + (i.configurada ? 'ok' : '') }, i.configurada ? 'chave ok' : 'sem chave'),
        chave, modelo,
        h('button', { type: 'button', class: 'bt pri fino', onclick: salvar }, 'Salvar'),
        i.configurada ? botaoRemover(async () => {
          try { await post('/api/ias/chave', { ia: i.id, remover: true }); dizer('Chave da ' + i.nome + ' removida.'); redesenhar(); } catch (e) { dizer(e.message, false); }
        }) : null);
    }

    async function desenhar() {
      let s;
      try { s = await api('/api/ias'); } catch (e) { secao.replaceChildren(titulo(), h('div', { class: 'vazio' }, e.message)); return; }
      secao.replaceChildren(titulo(),
        h('p', { class: 'nota' }, 'O gestor pode mandar uma destas IAs fazer o serviço de um subagente: ler, procurar, editar e rodar testes. ',
          'Ela trabalha numa cópia separada do projeto; nada entra no projeto antes de o gestor conferir. O passo a passo aparece em Agentes ao vivo.'),
        s.ias.map(i => linha(i, desenhar)),
        h('p', { class: 'nota' }, 'A chave fica só neste PC, num arquivo que só a sua conta do Windows abre; não vai para o backup nem para o GitHub. ',
          'Cada IA cobra na sua própria conta. Comandos que elas podem rodar: ' + s.comandos.join(', ') + '.'),
        h('p', { class: 'nota' }, 'Para o gestor: python cerebro_cli.py ia rodar <projeto> --ia deepseek --tarefa "..." · depois ia juntar ou ia descartar.'));
    }
    desenhar();
    return secao;
  });
})();
