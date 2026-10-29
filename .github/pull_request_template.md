## O que muda

<!-- Em poucas linhas, com as suas palavras. Se resolve uma issue, escreva "Resolve #número". -->

## Como testei

- [ ] `python -m unittest discover -s testes -t . -p "test_*.py"` passou (as pastas impressas no começo estão em `~/.cerebro-testes`)
- [ ] `ruff check .` passou
- [ ] Vi a mudança funcionando na demonstração (`python demo/rodar_demo.py`), se mexe na tela

## Segurança e privacidade

- [ ] Nenhum teste toca `~/.claude`, `~/.cerebro`, `settings.json` real, Agendador, registro do Windows, rede, nem roda `claude`/`pip`/`winget` de verdade
- [ ] Nada é apagado fora das travas (`config.remover()` no app; `testes/_ambiente.apagar()` nos testes)
- [ ] Não há dados reais (conversas, nomes, e-mails, caminhos pessoais, segredos) em código, testes, docs ou fotos
- [ ] Rota nova exige a chave da página; texto de conversa/memória passa por `segredos.mascarar()` e vai para a tela com `textContent`

**Escreve fora de `~/.cerebro`?** <!-- Não / Sim: onde, e como pede confirmação, mostra a prévia e guarda cópia antes. -->

## Documentação

- [ ] Atualizei o que a pessoa lê, se mudou algo visível (`web/guia.js`, `README.md`, `docs/referencia.md`, `CHANGELOG.md`)
