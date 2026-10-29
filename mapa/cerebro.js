/* Cérebro do Projeto — página local, sem servidor e sem bibliotecas: motor de forças próprio em Canvas 2D.
   Os dados vêm de dados.js (window.CEREBRO), gerado por gerar.py a partir do mapa do Graphify.
   Partes: 1 utilidades e modelo · 2 simulação · 3 desenho e mouse · 4 janela lateral, busca, legenda, painel, atualização. */
(function () {
  'use strict';

  /* ==================================================================== 1. utilidades e modelo */
  const $ = (s, r) => (r || document).querySelector(s);
  try { if (window.self !== window.top) document.documentElement.classList.add('embutido'); } catch (e) { document.documentElement.classList.add('embutido'); }
  const fmt = n => Number(n).toLocaleString('pt-BR');
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ESC[c]);
  const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const salvar = (k, v) => { try { localStorage.setItem('cerebro.' + k, v); } catch (e) { /* sem armazenamento: tudo bem */ } };
  const ler = k => { try { return localStorage.getItem('cerebro.' + k); } catch (e) { return null; } };
  const agora = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
  function aleatorio(semente) {            // mulberry32: o mesmo desenho a cada abertura
    let a = semente >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function dataBonita(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  }
  function haQuanto(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 90) return 'agora há pouco';
    if (s < 5400) return 'há ' + Math.round(s / 60) + ' min';
    if (s < 129600) return 'há ' + Math.round(s / 3600) + ' h';
    return 'há ' + Math.round(s / 86400) + ' dias';
  }

  // As cores dos departamentos vêm do dados.js (cada projeto tem as suas)
  function misturar(hex, alvo, p) {
    const n = parseInt(hex.slice(1), 16), m = parseInt(alvo.slice(1), 16);
    const c = [16, 8, 0].map(s => Math.round(((n >> s) & 255) * (1 - p) + ((m >> s) & 255) * p));
    return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
  }
  // Âncoras dos departamentos no "cérebro" (visão geral): lobo frontal à esquerda, occipital à direita, cerebelo embaixo.
  // Cada departamento pode trazer a própria âncora no dados.js; sem ela vale a posição pelo número do departamento.
  const ANCORA_GENERICA = [[-900, 250], [-300, -430], [-560, -40], [130, -470], [560, -290], [830, 60], [520, 330], [190, 20], [-80, 450], [330, 480], [-430, 420], [-110, -20]];
  const anc = (Dd, d) => ((Dd && Dd.ancoras && Dd.ancoras[d]) || ANCORA_GENERICA[d % ANCORA_GENERICA.length]);
  // Espaçamento entre as bolinhas (controle − / + no cabeçalho, lembrado no navegador). 1 = o desenho antigo, mais apertado.
  const ESPACO = { min: 0.8, max: 2.6, padrao: 1.6, f: 1.6 };
  ESPACO.f = clamp(Number(ler('mapa.espaco')) || ESPACO.padrao, ESPACO.min, ESPACO.max);

  const TEMA = { escuro: true, cor: [], brilho: [], halo: [] };
  function aplicarTema(escuro) {
    TEMA.escuro = escuro;
    document.documentElement.setAttribute('data-tema', escuro ? 'escuro' : 'claro');
    salvar('tema', escuro ? 'escuro' : 'claro');
    TEMA.cor = []; TEMA.brilho = []; TEMA.halo = [];
    const nomes = (D && D.deptos) || [];
    nomes.forEach((nome, i) => {
      const base = (D && D.cores && D.cores[i]) || '#aab';   // cores vêm do dados.js (departamentos por projeto)
      const cor = escuro ? base : misturar(base, '#000000', 0.3);
      TEMA.cor[i] = cor;
      TEMA.brilho[i] = esfera(cor, 64, escuro ? 0.85 : 0.5);
      TEMA.halo[i] = esfera(cor, 128, escuro ? 0.55 : 0.3);
    });
    const cs = getComputedStyle(document.documentElement);
    TEMA.texto = cs.getPropertyValue('--text').trim() || '#fff';
    TEMA.suave = cs.getPropertyValue('--muted').trim() || '#999';
    est.sujo = true;
  }
  function esfera(cor, tam, forca) {        // bolinha de luz pré-desenhada (desenhar isso é bem mais barato que um gradiente por ponto)
    const c = document.createElement('canvas');
    c.width = c.height = tam;
    const x = c.getContext('2d');
    const g = x.createRadialGradient(tam / 2, tam / 2, 0, tam / 2, tam / 2, tam / 2);
    g.addColorStop(0, hexA(cor, forca));
    g.addColorStop(0.35, hexA(cor, forca * 0.35));
    g.addColorStop(1, hexA(cor, 0));
    x.fillStyle = g;
    x.fillRect(0, 0, tam, tam);
    return c;
  }
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // ---- modelo: dados mastigados para consulta rápida ----
  let D = window.CEREBRO;
  let M = null;

  const FRASE = {   // relação -> [como o item atual se liga ao outro, como o outro se liga ao item atual]
    calls: ['chama', 'é chamado por'],
    indirect_call: ['chama (indiretamente)', 'é chamado (indiretamente) por'],
    imports: ['importa', 'é importado por'],
    imports_from: ['importa de', 'é fonte de importação para'],
    contains: ['contém', 'faz parte de'],
    method: ['tem o método', 'é método de'],
    references: ['referencia', 'é referenciado por'],
    case_of: ['tem a variante', 'é variante de'],
    uses: ['usa', 'é usado por'],
    inherits: ['herda de', 'é base de'],
    re_exports: ['reexporta', 'é reexportado por'],
    declares: ['declara', 'é declarado por'],
    implements: ['implementa', 'é implementado por'],
  };
  const ROTULO_REL = {
    calls: 'chamadas', indirect_call: 'chamadas indiretas', imports: 'importações de itens', imports_from: 'importações de arquivos',
    contains: 'contém', method: 'métodos', references: 'referências', case_of: 'variantes', uses: 'usos', inherits: 'heranças',
    re_exports: 'reexportações', declares: 'declarações', implements: 'implementações',
  };

  function preparar(dados) {
    const nn = dados.nos.n.length, nF = dados.arquivos.length, nG = dados.grupos.length, nd = dados.deptos.length;
    const L = dados.lig;
    const m = { D: dados, nn, nF, nG, nd };
    m.nome = dados.nos.n; m.arq = dados.nos.a; m.lin = dados.nos.l; m.tipo = dados.nos.k; m.grp = dados.nos.g; m.dep = dados.nos.d;
    const grau = new Uint32Array(nn);
    for (let i = 0; i < L.length; i += 3) { grau[L[i]]++; grau[L[i + 1]]++; }
    const off = new Uint32Array(nn + 1);
    for (let i = 0; i < nn; i++) off[i + 1] = off[i] + grau[i];
    const pos = off.slice(0, nn);
    const adjA = new Int32Array(off[nn]), adjR = new Uint8Array(off[nn]), adjD = new Uint8Array(off[nn]);
    for (let i = 0; i < L.length; i += 3) {
      const s = L[i], t = L[i + 1], r = L[i + 2];
      let p = pos[s]++; adjA[p] = t; adjR[p] = r; adjD[p] = 0;
      p = pos[t]++; adjA[p] = s; adjR[p] = r; adjD[p] = 1;
    }
    m.grau = grau; m.off = off; m.adjA = adjA; m.adjR = adjR; m.adjD = adjD;
    m.membros = Array.from({ length: nG }, () => []);
    m.itensDoArq = Array.from({ length: nF }, () => []);
    for (let e = 0; e < nn; e++) {
      m.membros[m.grp[e]].push(e);
      if (e >= nF && m.arq[e] >= 0) m.itensDoArq[m.arq[e]].push(e);
    }
    // ligações entre grupos (peso = quantas ligações) e entre departamentos
    const peso = new Map();
    const matriz = new Float64Array(nd * nd);
    const porRel = new Float64Array(14);
    const internas = new Uint32Array(nG), externas = new Uint32Array(nG);
    for (let i = 0; i < L.length; i += 3) {
      const s = L[i], t = L[i + 1];
      const gs = m.grp[s], gt = m.grp[t];
      matriz[m.dep[s] * nd + m.dep[t]]++;
      porRel[L[i + 2] >> 1]++;
      if (gs === gt) { internas[gs]++; continue; }
      externas[gs]++; externas[gt]++;
      const k = gs < gt ? gs * nG + gt : gt * nG + gs;
      peso.set(k, (peso.get(k) || 0) + 1);
    }
    m.gs = []; m.gt = []; m.gw = [];
    m.vizinhosG = Array.from({ length: nG }, () => []);
    peso.forEach((w, k) => {
      const a = Math.floor(k / nG), b = k % nG;
      m.gs.push(a); m.gt.push(b); m.gw.push(w);
      m.vizinhosG[a].push([b, w]); m.vizinhosG[b].push([a, w]);
    });
    m.vizinhosG.forEach(v => v.sort((x, y) => y[1] - x[1]));
    m.matriz = matriz; m.porRel = porRel; m.internas = internas; m.externas = externas;
    m.grupoPorNome = new Map(dados.grupos.map((g, i) => [g.n, i]));
    m.porChave = new Map();                                     // "arquivo\0nome" -> item (para a linha do tempo)
    for (let e = 0; e < nn; e++) {
      const f = m.arq[e] >= 0 ? dados.arquivos[m.arq[e]] : '';
      const k = f + '\u0000' + m.nome[e];
      if (!m.porChave.has(k)) m.porChave.set(k, e);
    }
    m.deptoGrupos = new Uint32Array(nd); m.deptoItens = new Uint32Array(nd); m.deptoArq = new Uint32Array(nd);
    dados.grupos.forEach(g => { m.deptoGrupos[g.d]++; });
    for (let e = 0; e < nn; e++) { m.deptoItens[m.dep[e]]++; if (e < nF) m.deptoArq[m.dep[e]]++; }
    m.indiceBusca = null;
    return m;
  }

  /* ==================================================================== 2. simulação de forças */
  // Barnes-Hut: a repulsão entre todos os pontos sem testar todos os pares.
  const QT = { cap: 0 };
  function qtGarantir(cap) {
    if (QT.cap >= cap) return;
    QT.cap = cap;
    QT.x0 = new Float64Array(cap); QT.y0 = new Float64Array(cap); QT.s = new Float64Array(cap);
    QT.m = new Float64Array(cap); QT.sx = new Float64Array(cap); QT.sy = new Float64Array(cap);
    QT.b = new Int32Array(cap); QT.c = new Int32Array(cap * 4); QT.pilha = new Int32Array(256);
  }
  function qtCelula(x0, y0, s) {
    const c = QT.n++;
    QT.x0[c] = x0; QT.y0[c] = y0; QT.s[c] = s; QT.m[c] = 0; QT.sx[c] = 0; QT.sy[c] = 0; QT.b[c] = -1;
    QT.c[c * 4] = QT.c[c * 4 + 1] = QT.c[c * 4 + 2] = QT.c[c * 4 + 3] = -1;
    return c;
  }
  function qtConstruir(G) {
    const n = G.n, x = G.x, y = G.y, w = G.carga;
    qtGarantir(n * 6 + 64);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i < n; i++) {
      if (x[i] < x0) x0 = x[i]; if (x[i] > x1) x1 = x[i];
      if (y[i] < y0) y0 = y[i]; if (y[i] > y1) y1 = y[i];
    }
    QT.n = 0;
    qtCelula(x0 - 1, y0 - 1, Math.max(x1 - x0, y1 - y0) + 2);
    for (let i = 0; i < n; i++) {
      let c = 0, prof = 0;
      const xi = x[i], yi = y[i], wi = w[i];
      for (;;) {
        QT.m[c] += wi; QT.sx[c] += xi * wi; QT.sy[c] += yi * wi;
        if (QT.b[c] === -1 && QT.m[c] === wi) { QT.b[c] = i; break; }
        if (QT.b[c] >= 0) {
          if (prof > 28) break;               // pontos praticamente no mesmo lugar: só soma a massa
          const j = QT.b[c];
          QT.b[c] = -2;
          const half = QT.s[c] / 2;
          const q = (x[j] >= QT.x0[c] + half ? 1 : 0) + (y[j] >= QT.y0[c] + half ? 2 : 0);
          const cj = qtCelula(QT.x0[c] + (q & 1 ? half : 0), QT.y0[c] + (q & 2 ? half : 0), half);
          QT.b[cj] = j; QT.m[cj] = w[j]; QT.sx[cj] = x[j] * w[j]; QT.sy[cj] = y[j] * w[j];
          QT.c[c * 4 + q] = cj;
        }
        const half = QT.s[c] / 2;
        const q = (xi >= QT.x0[c] + half ? 1 : 0) + (yi >= QT.y0[c] + half ? 2 : 0);
        const filho = QT.c[c * 4 + q];
        if (filho === -1) {
          const cc = qtCelula(QT.x0[c] + (q & 1 ? half : 0), QT.y0[c] + (q & 2 ? half : 0), half);
          QT.b[cc] = i; QT.m[cc] = wi; QT.sx[cc] = xi * wi; QT.sy[cc] = yi * wi;
          QT.c[c * 4 + q] = cc;
          break;
        }
        c = filho; prof++;
      }
    }
  }
  function repulsao(G, forca, alcance2) {
    const n = G.n, x = G.x, y = G.y, vx = G.vx, vy = G.vy, pilha = QT.pilha;
    const teta2 = 0.81;
    for (let i = 0; i < n; i++) {
      if (G.fixo[i]) continue;
      const xi = x[i], yi = y[i];
      let sp = 0, ax = 0, ay = 0;
      pilha[sp++] = 0;
      while (sp > 0) {
        const c = pilha[--sp];
        const mc = QT.m[c];
        if (mc === 0) continue;
        const b = QT.b[c];
        if (b === i) continue;
        const dx = QT.sx[c] / mc - xi, dy = QT.sy[c] / mc - yi;
        let d2 = dx * dx + dy * dy;
        if (b !== -2 || QT.s[c] * QT.s[c] < teta2 * d2) {
          if (d2 < 1) d2 = 1;
          if (d2 < alcance2) {                 // acima de ~300 unidades (× espaçamento) a repulsão já é desprezível
            const f = mc / d2;
            ax -= dx * f; ay -= dy * f;
          }
          continue;
        }
        const base = c * 4;
        for (let q = 0; q < 4; q++) { const f = QT.c[base + q]; if (f >= 0 && sp < 250) pilha[sp++] = f; }
      }
      vx[i] += ax * forca; vy[i] += ay * forca;
    }
  }
  // colisão suave: pontos não ficam em cima uns dos outros
  const COL = { cab: null, prox: null };
  function colisao(G, folga) {
    const n = G.n, x = G.x, y = G.y, r = G.r;
    let rmax = 0, x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i < n; i++) {
      if (r[i] > rmax) rmax = r[i];
      if (x[i] < x0) x0 = x[i]; if (x[i] > x1) x1 = x[i];
      if (y[i] < y0) y0 = y[i]; if (y[i] > y1) y1 = y[i];
    }
    const cs = Math.max(8, 2 * rmax + folga);
    const cols = Math.min(256, Math.ceil((x1 - x0) / cs) + 1), lins = Math.min(256, Math.ceil((y1 - y0) / cs) + 1);
    const cel = cols * lins;
    if (!COL.cab || COL.cab.length < cel) COL.cab = new Int32Array(cel);
    if (!COL.prox || COL.prox.length < n) COL.prox = new Int32Array(n);
    COL.cab.fill(-1, 0, cel);
    const cab = COL.cab, prox = COL.prox;
    const idx = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      const cx = Math.min(cols - 1, Math.floor((x[i] - x0) / cs)), cy = Math.min(lins - 1, Math.floor((y[i] - y0) / cs));
      idx[i] = cy * cols + cx;
      prox[i] = cab[idx[i]]; cab[idx[i]] = i;
    }
    for (let i = 0; i < n; i++) {
      const cx = idx[i] % cols, cy = (idx[i] / cols) | 0;
      for (let oy = -1; oy <= 1; oy++) {
        const yy = cy + oy; if (yy < 0 || yy >= lins) continue;
        for (let ox = -1; ox <= 1; ox++) {
          const xx = cx + ox; if (xx < 0 || xx >= cols) continue;
          for (let j = cab[yy * cols + xx]; j >= 0; j = prox[j]) {
            if (j <= i) continue;
            let dx = x[j] - x[i], dy = y[j] - y[i];
            const min = r[i] + r[j] + folga;
            const d2 = dx * dx + dy * dy;
            if (d2 >= min * min) continue;
            let d = Math.sqrt(d2);
            if (d < 0.01) { dx = 0.5; dy = 0.3; d = 0.6; }
            const e = (min - d) / d * 0.5 * 0.7;
            const ex = dx * e, ey = dy * e;
            const mi = G.fixo[i] ? 0 : 1, mj = G.fixo[j] ? 0 : 1, tot = mi + mj || 1;
            x[i] -= ex * 2 * mi / tot; y[i] -= ey * 2 * mi / tot;
            x[j] += ex * 2 * mj / tot; y[j] += ey * 2 * mj / tot;
          }
        }
      }
    }
  }
  function passo(G) {
    const n = G.n, P = G.param, a = G.alfa;
    const x = G.x, y = G.y, vx = G.vx, vy = G.vy;
    qtConstruir(G);
    repulsao(G, P.carga * a, P.alcance * P.alcance);
    // molas das ligações
    const ls = G.ls, lt = G.lt;
    for (let i = 0; i < ls.length; i++) {
      const s = ls[i], t = lt[i];
      let dx = x[t] + vx[t] - x[s] - vx[s], dy = y[t] + vy[t] - y[s] - vy[s];
      let d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const alvo = G.lc[i];
      const f = (d - alvo) / d * G.lf[i] * a;
      dx *= f; dy *= f;
      const bias = G.gr[t] / (G.gr[s] + G.gr[t]);
      if (!G.fixo[t]) { vx[t] -= dx * bias; vy[t] -= dy * bias; }
      if (!G.fixo[s]) { vx[s] += dx * (1 - bias); vy[s] += dy * (1 - bias); }
    }
    // âncora (a região do departamento) e gravidade
    const k = P.ancora * (0.35 + 0.65 * a);
    for (let i = 0; i < n; i++) {
      if (G.fixo[i]) { vx[i] = vy[i] = 0; continue; }
      vx[i] += (G.tx[i] - x[i]) * G.ta[i] * k;
      vy[i] += (G.ty[i] - y[i]) * G.ta[i] * k;
      vx[i] *= 0.58; vy[i] *= 0.58;
      const v2 = vx[i] * vx[i] + vy[i] * vy[i];
      if (v2 > 900) { const s = 30 / Math.sqrt(v2); vx[i] *= s; vy[i] *= s; }
      x[i] += vx[i]; y[i] += vy[i];
    }
    colisao(G, P.folga);
    G.alfa += (G.alvoAlfa - G.alfa) * 0.022;
  }

  /* ---- construção dos grafos exibidos ---- */
  function novoGrafo(n) {
    return {
      n, x: new Float64Array(n), y: new Float64Array(n), vx: new Float64Array(n), vy: new Float64Array(n),
      r: new Float64Array(n), carga: new Float64Array(n), fixo: new Uint8Array(n), tx: new Float64Array(n), ty: new Float64Array(n),
      ta: new Float64Array(n), dep: new Uint8Array(n), tipo: new Uint8Array(n), ref: new Int32Array(n), gr: new Float64Array(n),
      nome: new Array(n), chave: new Array(n), esc: new Uint8Array(n),   // esc = escondido pelo filtro de departamento
      ls: null, lt: null, lw: null, lc: null, lf: null, lk: null, alfa: 1, alvoAlfa: 0, assentou: false, param: null,
    };
  }
  // índice de vizinhança do grafo exibido (para realce) e baldes de ligações por departamento e espessura
  function indexar(G) {
    const n = G.n, m = G.ls.length;
    const cont = new Uint32Array(n + 1);
    for (let i = 0; i < m; i++) { cont[G.ls[i] + 1]++; cont[G.lt[i] + 1]++; }
    for (let i = 0; i < n; i++) cont[i + 1] += cont[i];
    const pos = cont.slice(0, n);
    G.off = cont; G.viz = new Int32Array(cont[n]); G.vizL = new Int32Array(cont[n]);
    for (let i = 0; i < m; i++) {
      const s = G.ls[i], t = G.lt[i];
      G.viz[pos[s]] = t; G.vizL[pos[s]++] = i;
      G.viz[pos[t]] = s; G.vizL[pos[t]++] = i;
    }
    for (let i = 0; i < n; i++) G.gr[i] = Math.max(1, cont[i + 1] - cont[i]);
    G.baldes = [];
    const tmp = new Map();
    for (let i = 0; i < m; i++) {
      const tier = G.lw[i] > 40 ? 2 : G.lw[i] > 6 ? 1 : 0;
      const k = (G.lk[i] & 1 ? 100 : 0) + G.dep[G.ls[i]] * 3 + tier;
      if (!tmp.has(k)) tmp.set(k, []);
      tmp.get(k).push(i);
    }
    tmp.forEach((lista, k) => {
      const inf = k >= 100, kk = k % 100;
      G.baldes.push({ dep: Math.floor(kk / 3), tier: kk % 3, inf, ids: Int32Array.from(lista) });
    });
  }
  function fecharGrafo(G, param) {
    G.param = param;
    indexar(G);
    G.pulsoLig = [];
    for (let i = 0; i < G.ls.length; i++) if (G.lw[i] >= (G.modo === 'geral' ? 3 : 1)) G.pulsoLig.push(i);
    G.alfa = 1; G.alvoAlfa = 0; G.assentou = false;
    return G;
  }

  function construirGeral(m, antigos) {
    const n = m.nG, G = novoGrafo(n), rnd = aleatorio(20261029);
    const s = ESPACO.f, sd = s + 0.6 * (s - 1);   // os departamentos se afastam mais que os pontos (1 = desenho antigo)
    G.modo = 'geral';
    const nomes = m.D.deptos;
    for (let i = 0; i < n; i++) {
      const g = m.D.grupos[i];
      const a = anc(m.D, g.d);
      G.r[i] = 3.6 + Math.sqrt(g.t) * 1.3;
      G.carga[i] = 1 + G.r[i] * 0.55;
      G.tx[i] = a[0] * 1.12 * sd; G.ty[i] = a[1] * 0.8 * sd; G.ta[i] = 0.035;
      const ang = rnd() * 6.2832, rad = (20 + rnd() * 60) * s;
      G.x[i] = a[0] * 0.14 * sd + Math.cos(ang) * rad; G.y[i] = a[1] * 0.1 * sd + Math.sin(ang) * rad;
      G.dep[i] = g.d; G.tipo[i] = 0; G.ref[i] = i; G.nome[i] = g.n; G.chave[i] = g.n;
    }
    G.ls = Int32Array.from(m.gs); G.lt = Int32Array.from(m.gt); G.lw = Float64Array.from(m.gw);
    G.lk = new Uint8Array(G.ls.length);
    G.lc = new Float64Array(G.ls.length); G.lf = new Float64Array(G.ls.length);
    for (let i = 0; i < G.ls.length; i++) {
      const s = G.ls[i], t = G.lt[i], w = G.lw[i];
      const mesmo = G.dep[s] === G.dep[t];
      G.lc[i] = ((G.r[s] + G.r[t]) * (mesmo ? 1.3 : 1.9) + 34 + 60 / Math.sqrt(w)) * ESPACO.f;
      G.lf[i] = clamp(0.012 + Math.log2(1 + w) * 0.012, 0.012, 0.14) * (mesmo ? 1.4 : 0.55);
    }
    if (antigos) {
      for (let i = 0; i < n; i++) { const a = antigos.get(G.chave[i]); if (a) { G.x[i] = a[0]; G.y[i] = a[1]; G.fixo[i] = a[2]; } }
    }
    fecharGrafo(G, { carga: 520 * s * s, ancora: 0.55, folga: 7 * s + 4 * (s - 1), alcance: 300 * s });
    if (antigos) G.alfa = 0.25;
    return G;
  }

  function construirGrupo(m, g, antigos) {
    const G0 = [], nF = m.nF;
    const noGrupo = new Map();      // item -> índice
    const adicionar = (e, tipoNo) => { if (!noGrupo.has(e)) { noGrupo.set(e, G0.length); G0.push([e, tipoNo]); } };
    m.membros[g].forEach(e => { if (e >= nF) adicionar(e, 2); });
    const hubs = new Set();
    m.membros[g].forEach(e => { if (e < nF) hubs.add(e); else if (m.arq[e] >= 0) hubs.add(m.arq[e]); });
    hubs.forEach(a => adicionar(a, 1));
    const nucleo = G0.length;
    // vizinhos diretos de outros grupos (apagados), os mais ligados primeiro
    const conta = new Map();
    for (let k = 0; k < nucleo; k++) {
      const e = G0[k][0];
      for (let p = m.off[e]; p < m.off[e + 1]; p++) {
        const o = m.adjA[p];
        if (noGrupo.has(o)) continue;
        conta.set(o, (conta.get(o) || 0) + 1);
      }
    }
    const ranque = Array.from(conta.entries()).sort((a, b) => b[1] - a[1] || m.grau[b[0]] - m.grau[a[0]]).slice(0, 110);
    ranque.forEach(([e]) => adicionar(e, 3));
    const n = G0.length, G = novoGrafo(n), rnd = aleatorio(g * 7919 + 13);
    G.modo = 'grupo'; G.grupo = g; G.nVizinhos = conta.size; G.nGhost = ranque.length;
    const centro = anc(m.D, m.D.grupos[g].d);
    const ng = Math.max(1, nucleo);
    const esp = ESPACO.f;
    const raioAnel = (280 + Math.sqrt(ng) * 30) * (1 + (esp - 1) * 0.5);   // vizinhos de fora afastam menos: o grupo ganha a tela
    for (let k = 0; k < n; k++) {
      const [e, tp] = G0[k];
      G.ref[k] = e; G.tipo[k] = tp; G.dep[k] = m.dep[e]; G.nome[k] = m.nome[e];
      const arqPath = m.arq[e] >= 0 ? m.D.arquivos[m.arq[e]] : '';
      G.chave[k] = tp === 1 ? 'arq:' + (e < nF ? m.D.arquivos[e] : arqPath) : arqPath + '|' + m.nome[e] + '|' + m.tipo[e];
      const grau = m.grau[e];
      if (tp === 1) { G.r[k] = 8 + Math.sqrt((m.itensDoArq[e < nF ? e : m.arq[e]] || []).length) * 1.5; G.carga[k] = 3 + G.r[k] * 0.6; }
      else if (tp === 2) { G.r[k] = 3.4 + Math.min(10, Math.sqrt(grau) * 0.85); G.carga[k] = 1 + G.r[k] * 0.35; }
      else { G.r[k] = 3 + Math.min(5, Math.sqrt(grau) * 0.3); G.carga[k] = 0.6 + G.r[k] * 0.2; }
      if (tp === 3) {
        const og = m.D.grupos[m.grp[e]].d;
        const ang = Math.atan2(anc(m.D, og)[1] - centro[1] + (rnd() - 0.5) * 300, anc(m.D, og)[0] - centro[0] + (rnd() - 0.5) * 300);
        G.tx[k] = Math.cos(ang) * raioAnel; G.ty[k] = Math.sin(ang) * raioAnel; G.ta[k] = 0.012;
        G.x[k] = G.tx[k] * 0.6; G.y[k] = G.ty[k] * 0.6;
      } else {
        G.tx[k] = 0; G.ty[k] = 0; G.ta[k] = tp === 1 ? 0.006 : 0.012;
        const ang = rnd() * 6.2832, rad = (8 + rnd() * 40) * esp;
        G.x[k] = Math.cos(ang) * rad; G.y[k] = Math.sin(ang) * rad;
      }
    }
    // ligações: reais entre os pontos exibidos + "faz parte de" (item -> arquivo)
    const S = [], T = [], W = [], K = [];
    const L = m.D.lig;
    for (let k = 0; k < n; k++) {
      const e = G0[k][0];
      for (let p = m.off[e]; p < m.off[e + 1]; p++) {
        if (m.adjD[p] !== 0) continue;              // cada ligação uma vez (do lado de saída)
        const j = noGrupo.get(m.adjA[p]);
        if (j === undefined || (G0[k][1] === 3 && G0[j][1] === 3)) continue;
        S.push(k); T.push(j); W.push(1); K.push(m.adjR[p]);
      }
      if (G0[k][1] === 2) {
        const hub = noGrupo.get(m.arq[e]);
        if (hub !== undefined) { S.push(k); T.push(hub); W.push(1); K.push(254); }
      }
    }
    void L;
    G.ls = Int32Array.from(S); G.lt = Int32Array.from(T); G.lw = Float64Array.from(W); G.lk = Uint8Array.from(K);
    G.lc = new Float64Array(S.length); G.lf = new Float64Array(S.length);
    for (let i = 0; i < S.length; i++) {
      const s = S[i], t = T[i], membro = K[i] === 254;
      const gh = G.tipo[s] === 3 || G.tipo[t] === 3;
      G.lc[i] = ((G.r[s] + G.r[t]) + (membro ? 26 : gh ? 120 : 52)) * esp;
      G.lf[i] = membro ? 0.09 : gh ? 0.012 : 0.03;
    }
    if (antigos) {                                  // reaproveita onde cada ponto estava (atualização sem perder a visão)
      for (let k = 0; k < n; k++) {
        const a = antigos.get(G.chave[k]);
        if (a) { G.x[k] = a[0]; G.y[k] = a[1]; G.fixo[k] = a[2]; }
      }
    }
    fecharGrafo(G, { carga: 70 * esp * esp, ancora: 0.5, folga: 5 * esp + 3 * (esp - 1), alcance: 300 * esp });
    if (antigos) G.alfa = 0.25;
    return G;
  }

  /* ==================================================================== 3. desenho e mouse */
  const cv = $('#tela'), ctx = cv.getContext('2d');
  let W = 0, H = 0, DPR = 1;
  const cam = { x: 0, y: 0, k: 1 };
  let G = null;                 // grafo exibido agora (visão geral ou um grupo)
  let padrao = null;            // posições "de fábrica" da visão geral, para o botão Voltar ao padrão
  let camAnim = null, tweenPos = null, camMexida = false, refocar = false;
  const est = { hover: -1, sel: -1, deptoHover: -1, sujo: true, sujoFoco: true, pulsos: true, foco: null, fixos: 0 };
  const filtro = new Uint8Array(32);       // 1 = departamento escondido pela legenda
  const pulsos = [], pings = [];
  let SX = new Float32Array(0), SY = new Float32Array(0);
  let ultimoDesenho = 0, ultimoQuadro = 0;
  const rnd = aleatorio(99);

  function redimensionar() {
    const r = cv.getBoundingClientRect();
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = Math.max(1, r.width); H = Math.max(1, r.height);
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    est.sujo = true;
  }
  const paraTelaX = x => (x - cam.x) * cam.k + W / 2;
  const paraTelaY = y => (y - cam.y) * cam.k + H / 2;

  function aplicarEsc() {
    if (!G) return;
    for (let i = 0; i < G.n; i++) G.esc[i] = filtro[G.dep[i]] ? 1 : 0;
    est.sujo = est.sujoFoco = true;
  }
  function calcularFoco() {
    est.sujoFoco = false;
    if (!G) { est.foco = null; return; }
    const centro = est.hover >= 0 ? est.hover : est.sel;
    if (centro >= 0 && centro < G.n) {
      const f = new Uint8Array(G.n);
      f[centro] = 2;
      for (let p = G.off[centro]; p < G.off[centro + 1]; p++) f[G.viz[p]] = 1;
      est.foco = f; est.centro = centro;
    } else if (est.deptoHover >= 0) {
      const f = new Uint8Array(G.n);
      for (let i = 0; i < G.n; i++) if (G.dep[i] === est.deptoHover) f[i] = 1;
      est.foco = f; est.centro = -1;
    } else { est.foco = null; est.centro = -1; }
  }

  /* ---- loop de animação: 60 qps enquanto algo mexe; parado quando assenta (só os pulsos de luz, a ~30 qps) ---- */
  const medidas = { n: 0, ms: 0, nSim: 0, msSim: 0, primeiro: 0 };   // só para conferir a fluidez (window.__cerebro.medidas)
  function laco(t) {
    requestAnimationFrame(laco);
    if (!G || document.hidden) return;
    const tIni = agora();
    let mexeu = false;
    if (camAnim) {
      const p = clamp((t - camAnim.t0) / camAnim.ms, 0, 1), e = 1 - Math.pow(1 - p, 3);
      cam.x = camAnim.de.x + (camAnim.para.x - camAnim.de.x) * e;
      cam.y = camAnim.de.y + (camAnim.para.y - camAnim.de.y) * e;
      cam.k = camAnim.de.k * Math.pow(camAnim.para.k / camAnim.de.k, e);
      if (p >= 1) camAnim = null;
      mexeu = true;
    }
    if (tweenPos) {
      const p = clamp((t - tweenPos.t0) / tweenPos.ms, 0, 1), e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      for (let i = 0; i < G.n; i++) {
        G.x[i] = tweenPos.de[i * 2] + (tweenPos.para[i * 2] - tweenPos.de[i * 2]) * e;
        G.y[i] = tweenPos.de[i * 2 + 1] + (tweenPos.para[i * 2 + 1] - tweenPos.de[i * 2 + 1]) * e;
      }
      if (p >= 1) { const reenquadrar = tweenPos.enquadrar; tweenPos = null; G.alfa = 0; G.assentou = false; if (reenquadrar && !camMexida) enquadrar(true); }
      mexeu = true;
    } else if (G.alfa > 0.0035 || G.alvoAlfa > 0) {
      const n = G.alfa > 0.3 ? 2 : 1;
      for (let i = 0; i < n; i++) passo(G);
      G.assentou = false;
      // o desenho já tomou forma: enquadra tudo uma vez antes de assentar (o espaçamento maior não deixa pontos fora da tela)
      if (!camMexida && !G.preEnquadrado && G.alfa < 0.15) { G.preEnquadrado = true; enquadrar(true); }
      mexeu = true;
    } else if (!G.assentou) {
      G.assentou = true; mexeu = true;
      aoAssentar();
    }
    const soPulsos = !mexeu && !est.sujo && est.pulsos;
    if (!mexeu && !est.sujo && !est.pulsos) return;
    if (soPulsos && t - ultimoDesenho < 32) return;
    const dt = Math.min(0.06, (t - ultimoQuadro) / 1000 || 0.016);
    ultimoQuadro = t; ultimoDesenho = t;
    const t0 = agora();
    desenhar(t, dt);
    est.sujo = false;
    medidas.n++; medidas.ms += agora() - t0; if (mexeu) { medidas.nSim++; medidas.msSim += t0 - tIni; }
    if (!medidas.primeiro) medidas.primeiro = Math.round(agora());
  }

  function aoAssentar() {
    if (G.modo === 'geral' && !padrao) {
      padrao = new Float64Array(G.n * 2);
      for (let i = 0; i < G.n; i++) { padrao[i * 2] = G.x[i]; padrao[i * 2 + 1] = G.y[i]; }
    }
    if (!camMexida) enquadrar(true);
    else if (refocar && est.sel >= 0) centrarEm(est.sel, 1.2);
    refocar = false;
    document.body.dataset.pronto = '1';
  }

  function enquadrar(animar) {
    if (!G) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, achou = false;
    for (let i = 0; i < G.n; i++) {
      if (G.esc[i]) continue;
      achou = true;
      const r = G.r[i];
      if (G.x[i] - r < x0) x0 = G.x[i] - r; if (G.x[i] + r > x1) x1 = G.x[i] + r;
      if (G.y[i] - r < y0) y0 = G.y[i] - r; if (G.y[i] + r > y1) y1 = G.y[i] + r;
    }
    if (!achou) return;
    // folgas: a janela lateral (direita), a legenda aberta (esquerda), as migalhas (em cima) e a dica (embaixo) não cobrem pontos
    // (os nomes ficam centrados na bolinha e passam do raio: ~90 px de folga de cada lado para não cortar)
    const lado = Math.min(110, W * 0.1);
    const folgaDir = $('#detalhe').classList.contains('fechado') ? lado : Math.min(440, W * 0.45) + 30;
    const leg = $('#legenda');
    const folgaEsq = leg && !leg.classList.contains('recolhida') && leg.offsetWidth ? Math.min(leg.offsetWidth + 40, W * 0.3) : lado;
    const cima = 70, baixo = 80;          // embaixo fica a dica de uso
    const bw = Math.max(80, x1 - x0), bh = Math.max(80, y1 - y0);
    const k = clamp(Math.min((W - folgaEsq - folgaDir) / bw, (H - cima - baixo) / bh), 0.05, 2.4);
    const alvo = { x: (x0 + x1) / 2 + (folgaDir - folgaEsq) / 2 / k, y: (y0 + y1) / 2 - (cima - baixo) / 2 / k, k };
    if (animar) camAnim = { de: { x: cam.x, y: cam.y, k: cam.k }, para: alvo, t0: agora(), ms: 800 };
    else { cam.x = alvo.x; cam.y = alvo.y; cam.k = alvo.k; camAnim = null; }
    est.sujo = true;
  }
  function centrarEm(i, zoomMin) {
    const k = Math.max(cam.k, zoomMin || 0.9);
    const folga = $('#detalhe').classList.contains('fechado') ? 0 : Math.min(440, W * 0.45) / 2 / k;
    camAnim = { de: { x: cam.x, y: cam.y, k: cam.k }, para: { x: G.x[i] + folga, y: G.y[i], k }, t0: agora(), ms: 650 };
    camMexida = true; est.sujo = true;
  }

  /* ---- desenho ---- */
  function desenhar(t, dt) {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const n = G.n, k = cam.k, hw = W / 2, hh = H / 2;
    if (SX.length < n) { SX = new Float32Array(n); SY = new Float32Array(n); }
    if (est.sujoFoco) calcularFoco();
    const foco = est.foco, centro = est.centro;
    if (!G.ordem) G.ordem = Array.from({ length: n }, (_, i) => i).sort((a, b) => G.r[b] - G.r[a]);
    const dentro = new Uint8Array(n);
    const m = 40;
    for (let i = 0; i < n; i++) {
      SX[i] = (G.x[i] - cam.x) * k + hw; SY[i] = (G.y[i] - cam.y) * k + hh;
      const r = G.r[i] * k + 30;
      dentro[i] = !G.esc[i] && SX[i] > -r - m && SX[i] < W + r + m && SY[i] > -r - m && SY[i] < H + r + m ? 1 : 0;
    }
    const escuro = TEMA.escuro;
    const geral = G.modo === 'geral';

    // halos das regiões (visão geral)
    if (geral) {
      ctx.globalCompositeOperation = escuro ? 'lighter' : 'source-over';
      for (let i = 0; i < n; i++) {
        if (!dentro[i]) continue;
        const a = (foco && !foco[i] ? 0.25 : 1) * (escuro ? 0.5 : 0.35);
        const sz = (G.r[i] * 5 + 70) * k;
        ctx.globalAlpha = a;
        ctx.drawImage(TEMA.halo[G.dep[i]], SX[i] - sz, SY[i] - sz, sz * 2, sz * 2);
      }
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      desenharRegioes();
    }

    // ligações
    ctx.lineCap = 'round';
    const baseA = escuro ? 1 : 0.8;
    for (let b = 0; b < G.baldes.length; b++) {
      const bd = G.baldes[b], ids = bd.ids;
      const alfaBase = (geral ? [0.1, 0.17, 0.3][bd.tier] : 0.17) * baseA * (foco ? 0.18 : 1);
      ctx.strokeStyle = hexA(TEMA.cor[bd.dep], Math.min(0.9, alfaBase));
      ctx.lineWidth = geral ? [0.6, 1, 1.7][bd.tier] : 0.8;
      ctx.setLineDash(bd.inf ? [3, 4] : []);
      ctx.beginPath();
      for (let q = 0; q < ids.length; q++) {
        const li = ids[q], s = G.ls[li], tt = G.lt[li];
        if (!dentro[s] && !dentro[tt]) continue;
        if (G.esc[s] || G.esc[tt]) continue;
        traco(s, tt, G.lk[li] === 254);
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (foco) {            // ligações do ponto em foco, bem visíveis
      ctx.lineWidth = 1.5 + (geral ? 0.6 : 0.2);
      for (let i = 0; i < G.ls.length; i++) {
        const s = G.ls[i], tt = G.lt[i];
        const vale = centro >= 0 ? (s === centro || tt === centro) : (foco[s] && foco[tt]);
        if (!vale || G.esc[s] || G.esc[tt]) continue;
        ctx.strokeStyle = hexA(TEMA.cor[G.dep[centro >= 0 ? (s === centro ? tt : s) : s]], 0.85);
        ctx.setLineDash(G.lk[i] & 1 && G.lk[i] !== 254 ? [3, 4] : []);
        ctx.beginPath(); traco(s, tt, G.lk[i] === 254); ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // pulsos de luz correndo pelas ligações
    if (est.pulsos) desenharPulsos(t, dt, dentro);

    // brilho dos pontos
    ctx.globalCompositeOperation = escuro ? 'lighter' : 'source-over';
    for (let q = 0; q < n; q++) {
      const i = G.ordem[q];
      if (!dentro[i]) continue;
      let a = G.tipo[i] === 3 ? 0.5 : 1;
      if (foco && !foco[i]) a *= 0.12;
      const sz = (G.r[i] * (geral ? 2.6 : 2.2) + 6) * k;
      ctx.globalAlpha = a * (escuro ? 0.9 : 0.55);
      ctx.drawImage(TEMA.brilho[G.dep[i]], SX[i] - sz, SY[i] - sz, sz * 2, sz * 2);
    }
    ctx.globalCompositeOperation = 'source-over';

    // corpo dos pontos
    for (let q = 0; q < n; q++) {
      const i = G.ordem[q];
      if (!dentro[i]) continue;
      let a = G.tipo[i] === 3 ? 0.62 : 1;
      if (foco && !foco[i]) a *= 0.14;
      const rs = Math.max(1.6, G.r[i] * k), cor = TEMA.cor[G.dep[i]];
      ctx.globalAlpha = a;
      ctx.beginPath(); ctx.arc(SX[i], SY[i], rs, 0, 6.2832);
      if (G.tipo[i] === 1) {             // arquivo: anel vazado
        ctx.fillStyle = hexA(cor, 0.22); ctx.fill();
        ctx.lineWidth = Math.max(1.4, 2 * k); ctx.strokeStyle = cor; ctx.stroke();
      } else {
        ctx.fillStyle = cor; ctx.fill();
        ctx.lineWidth = 1; ctx.strokeStyle = escuro ? 'rgba(255,255,255,.35)' : 'rgba(0,0,0,.28)'; ctx.stroke();
        if (rs > 7) {
          ctx.beginPath(); ctx.arc(SX[i] - rs * 0.28, SY[i] - rs * 0.3, rs * 0.3, 0, 6.2832);
          ctx.fillStyle = 'rgba(255,255,255,.28)'; ctx.fill();
        }
      }
      if (G.fixo[i]) {                   // preso: alfinete
        ctx.beginPath(); ctx.arc(SX[i] + rs * 0.72, SY[i] - rs * 0.72, Math.max(2.2, rs * 0.22), 0, 6.2832);
        ctx.fillStyle = escuro ? '#fff' : '#111'; ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // selecionado: anel que respira
    if (est.sel >= 0 && est.sel < n && dentro[est.sel]) {
      const i = est.sel, rs = G.r[i] * k + 5 + Math.sin(t / 380) * 1.8;
      ctx.beginPath(); ctx.arc(SX[i], SY[i], rs, 0, 6.2832);
      ctx.lineWidth = 2; ctx.strokeStyle = TEMA.texto; ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
    }
    desenharRotulos(dentro, foco);
  }

  function traco(s, tt, reta) {
    const ax = SX[s], ay = SY[s], bx = SX[tt], by = SY[tt];
    ctx.moveTo(ax, ay);
    if (reta) ctx.lineTo(bx, by);
    else ctx.quadraticCurveTo((ax + bx) / 2 - (by - ay) * 0.1, (ay + by) / 2 + (bx - ax) * 0.1, bx, by);
  }

  function desenharRegioes() {
    const n = G.n, nd = M.nd;
    const sx = new Float64Array(nd), sy = new Float64Array(nd), c = new Float64Array(nd);
    for (let i = 0; i < n; i++) { if (G.esc[i]) continue; const d = G.dep[i], w = G.r[i]; sx[d] += G.x[i] * w; sy[d] += G.y[i] * w; c[d] += w; }
    const alfa = clamp(1.7 - cam.k, 0, 1);
    if (alfa <= 0) return;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (let d = 0; d < nd; d++) {
      if (!c[d]) continue;
      const tam = clamp(34 * cam.k, 12, 40);
      ctx.font = '700 ' + tam + 'px "Chakra Petch", "IBM Plex Sans", "Segoe UI", sans-serif';
      ctx.globalAlpha = alfa * (est.deptoHover >= 0 && est.deptoHover !== d ? 0.2 : 0.55);
      ctx.fillStyle = TEMA.cor[d];
      ctx.fillText(M.D.deptos[d].toUpperCase(), paraTelaX(sx[d] / c[d]), paraTelaY(sy[d] / c[d]));
    }
    ctx.globalAlpha = 1;
  }

  function desenharPulsos(t, dt, dentro) {
    const lista = G.pulsoLig;
    if (!lista.length) return;
    while (pulsos.length < 16) {
      const li = lista[Math.floor(rnd() * lista.length)];
      pulsos.push({ li, p: rnd() * 0.3, v: 0.25 + rnd() * 0.35, ida: rnd() < 0.5 });
    }
    ctx.globalCompositeOperation = TEMA.escuro ? 'lighter' : 'source-over';
    for (let q = 0; q < pulsos.length; q++) {
      const pu = pulsos[q], s = G.ls[pu.li], tt = G.lt[pu.li];
      pu.p += pu.v * dt;
      if (pu.p >= 1) {
        pings.push({ no: pu.ida ? tt : s, t0: t });
        pulsos[q] = { li: lista[Math.floor(rnd() * lista.length)], p: 0, v: 0.25 + rnd() * 0.35, ida: rnd() < 0.5 };
        continue;
      }
      if (G.esc[s] || G.esc[tt] || (!dentro[s] && !dentro[tt])) continue;
      const a = pu.ida ? s : tt, b = pu.ida ? tt : s;
      const reta = G.lk[pu.li] === 254;
      for (let c = 0; c < 4; c++) {
        const p = pu.p - c * 0.035;
        if (p < 0) break;
        const x0 = SX[a], y0 = SY[a], x1 = SX[b], y1 = SY[b];
        const cx = (x0 + x1) / 2 - (y1 - y0) * 0.1 * (reta ? 0 : 1), cy = (y0 + y1) / 2 + (x1 - x0) * 0.1 * (reta ? 0 : 1);
        const u = 1 - p, x = u * u * x0 + 2 * u * p * cx + p * p * x1, y = u * u * y0 + 2 * u * p * cy + p * p * y1;
        const sz = (c === 0 ? 11 : 7 - c);
        ctx.globalAlpha = (c === 0 ? 1 : 0.5 / c) * (est.foco ? 0.5 : 1);
        ctx.drawImage(TEMA.brilho[G.dep[a]], x - sz, y - sz, sz * 2, sz * 2);
        if (c === 0) { ctx.globalAlpha = 0.95; ctx.fillStyle = TEMA.escuro ? '#fff' : '#223'; ctx.fillRect(x - 1, y - 1, 2, 2); }
      }
    }
    for (let q = pings.length - 1; q >= 0; q--) {
      const pg = pings[q], p = (t - pg.t0) / 700;
      if (p >= 1) { pings.splice(q, 1); continue; }
      const i = pg.no;
      if (!dentro[i]) continue;
      ctx.globalAlpha = (1 - p) * 0.8;
      ctx.beginPath(); ctx.arc(SX[i], SY[i], G.r[i] * cam.k + 3 + p * 16, 0, 6.2832);
      ctx.lineWidth = 1.4; ctx.strokeStyle = TEMA.cor[G.dep[i]]; ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  const colocados = [];
  function desenharRotulos(dentro, foco) {
    const k = cam.k, geral = G.modo === 'geral';
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    colocados.length = 0;
    let usados = 0;
    const fundo = TEMA.escuro ? 'rgba(8,12,18,.78)' : 'rgba(244,246,251,.85)';
    const talvez = (i, forcado) => {
      if (usados > 140) return;
      const rs = G.r[i] * k;
      const tam = G.tipo[i] === 1 ? 13 : 12;
      let txt = G.nome[i];
      if (txt.length > 38) txt = txt.slice(0, 37) + '…';
      ctx.font = (G.tipo[i] === 1 || forcado ? '650 ' : '500 ') + tam + 'px "IBM Plex Sans", "Segoe UI", sans-serif';
      const w = ctx.measureText(txt).width;
      const x = SX[i] + rs + 5, y = SY[i] + 4;
      if (!forcado) {
        for (let c = 0; c < colocados.length; c++) {
          const r = colocados[c];
          if (x < r[2] && x + w > r[0] && y - 12 < r[3] && y + 4 > r[1]) return;
        }
      }
      colocados.push([x, y - 12, x + w, y + 4]);
      usados++;
      ctx.lineWidth = 3; ctx.strokeStyle = fundo; ctx.strokeText(txt, x, y);
      ctx.fillStyle = TEMA.texto; ctx.fillText(txt, x, y);
    };
    ctx.lineJoin = 'round';
    if (est.sel >= 0 && dentro[est.sel]) talvez(est.sel, true);
    if (est.hover >= 0 && est.hover !== est.sel && dentro[est.hover]) talvez(est.hover, true);
    for (let q = 0; q < G.n; q++) {
      const i = G.ordem[q];
      if (!dentro[i] || i === est.sel || i === est.hover) continue;
      if (foco && !foco[i]) continue;
      const rs = G.r[i] * k;
      const mostra = geral ? (rs >= 11 || (k > 1.25 && rs >= 4) || (foco && rs >= 4.5))
        : (G.tipo[i] === 1 || (G.tipo[i] === 2 && (rs >= 9 || k > 1.3)) || (G.tipo[i] === 3 && k > 1.1 && foco));
      if (mostra) talvez(i, false);
    }
  }

  /* ---- mouse e toque ---- */
  const ponteiros = new Map();
  let arrasto = null, pinca = null, ultimoToque = 0;
  function mundo(mx, my) { return [(mx - W / 2) / cam.k + cam.x, (my - H / 2) / cam.k + cam.y]; }
  function acharNo(mx, my) {
    if (!G) return -1;
    let melhor = -1, ms = 1e9;
    for (let i = 0; i < G.n; i++) {
      if (G.esc[i]) continue;
      const dx = (G.x[i] - cam.x) * cam.k + W / 2 - mx, dy = (G.y[i] - cam.y) * cam.k + H / 2 - my;
      const rs = Math.max(G.r[i] * cam.k, 5), lim = rs + 3;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d <= lim) { const sc = d / lim + (G.tipo[i] === 3 ? 0.3 : 0) - G.r[i] * 0.004; if (sc < ms) { ms = sc; melhor = i; } }
    }
    return melhor;
  }
  function posicao(ev) { const r = cv.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; }

  cv.addEventListener('pointerdown', ev => {
    if (ev.button !== 0 && ev.pointerType === 'mouse') return;
    cv.setPointerCapture(ev.pointerId);
    const [mx, my] = posicao(ev);
    ponteiros.set(ev.pointerId, [mx, my]);
    escondeDica();
    if (ponteiros.size === 2) {
      const [a, b] = Array.from(ponteiros.values());
      pinca = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), k: cam.k };
      arrasto = null; return;
    }
    const no = acharNo(mx, my);
    arrasto = { no, mx, my, ox: mx, oy: my, moveu: false, id: ev.pointerId, tempo: agora() };
    if (no >= 0) { const [wx, wy] = mundo(mx, my); arrasto.dx = G.x[no] - wx; arrasto.dy = G.y[no] - wy; }
    cv.classList.add('agarrando');
  });
  cv.addEventListener('pointermove', ev => {
    const [mx, my] = posicao(ev);
    if (ponteiros.has(ev.pointerId)) ponteiros.set(ev.pointerId, [mx, my]);
    if (pinca && ponteiros.size === 2) {
      const [a, b] = Array.from(ponteiros.values());
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomEm((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, clamp(pinca.k * d / pinca.d, 0.06, 9));
      return;
    }
    if (arrasto && arrasto.id === ev.pointerId) {
      if (!arrasto.moveu && Math.hypot(mx - arrasto.ox, my - arrasto.oy) > 4) arrasto.moveu = true;
      if (arrasto.moveu) {
        camMexida = true;
        if (arrasto.no >= 0) {              // esticar: o ponto vai com o mouse, fica preso, e as ligações puxam os vizinhos
          const [wx, wy] = mundo(mx, my), i = arrasto.no;
          if (!G.fixo[i]) { G.fixo[i] = 1; est.fixos++; atualizarBotaoSoltar(); }
          G.x[i] = wx + arrasto.dx; G.y[i] = wy + arrasto.dy; G.vx[i] = G.vy[i] = 0;
          G.alvoAlfa = 0.22; G.alfa = Math.max(G.alfa, 0.3);
          tweenPos = null;
        } else {
          cam.x -= (mx - arrasto.mx) / cam.k; cam.y -= (my - arrasto.my) / cam.k; camAnim = null;
        }
        est.sujo = true;
      }
      arrasto.mx = mx; arrasto.my = my;
      return;
    }
    if (ev.pointerType === 'mouse') passarMouse(mx, my);
  });
  function fimPonteiro(ev) {
    ponteiros.delete(ev.pointerId);
    if (ponteiros.size < 2) pinca = null;
    cv.classList.remove('agarrando');
    if (!arrasto || arrasto.id !== ev.pointerId) return;
    const a = arrasto; arrasto = null;
    if (G) G.alvoAlfa = 0;
    if (a.moveu) return;
    const agoraT = agora(), duplo = agoraT - ultimoToque < 330;
    ultimoToque = agoraT;
    if (a.no >= 0) { if (duplo) aoDuploClique(a.no); else aoSelecionar(a.no); }
    else if (!duplo) aoFundo();
  }
  cv.addEventListener('pointerup', fimPonteiro);
  cv.addEventListener('pointercancel', fimPonteiro);
  cv.addEventListener('pointerleave', () => { if (!arrasto) passarMouse(-1e4, -1e4); });
  cv.addEventListener('dblclick', ev => ev.preventDefault());
  cv.addEventListener('wheel', ev => {
    ev.preventDefault();
    const [mx, my] = posicao(ev);
    camMexida = true; camAnim = null;
    const f = Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0013));
    zoomEm(mx, my, clamp(cam.k * f, 0.06, 9));
  }, { passive: false });
  function zoomEm(mx, my, novoK) {
    const [wx, wy] = mundo(mx, my);
    cam.k = novoK;
    cam.x = wx - (mx - W / 2) / novoK; cam.y = wy - (my - H / 2) / novoK;
    camMexida = true; est.sujo = true;
  }
  function passarMouse(mx, my) {
    const i = G ? acharNo(mx, my) : -1;
    if (i !== est.hover) {
      est.hover = i; est.sujoFoco = est.sujo = true;
      cv.classList.toggle('sobre', i >= 0);
    }
    aoPassar(i, mx, my);
  }
  window.addEventListener('resize', () => { redimensionar(); if (!camMexida) enquadrar(false); });
  // a área do mapa também muda sem a janela mudar (faixa de números recolhida, painel do Cérebro): o canvas acompanha
  if (window.ResizeObserver) new ResizeObserver(() => { redimensionar(); if (!camMexida) enquadrar(false); }).observe($('#vista-grafo'));

  /* ---- troca de visão e comandos ---- */
  let dicaVisivel = true;
  function escondeDica() { if (dicaVisivel) { dicaVisivel = false; $('#dica').classList.add('some'); } }
  function transicao(fn) {
    cv.classList.add('apagada');
    setTimeout(() => { fn(); requestAnimationFrame(() => cv.classList.remove('apagada')); }, 180);
  }
  function trocarGrafo(novo, prewarm) {
    G = novo;
    $('#tooltip').hidden = true;
    est.hover = est.sel = -1; est.deptoHover = -1; est.sujo = est.sujoFoco = true;
    est.fixos = 0; for (let i = 0; i < G.n; i++) if (G.fixo[i]) est.fixos++;
    pulsos.length = 0; pings.length = 0; tweenPos = null; camAnim = null;
    aplicarEsc();
    for (let i = 0; i < prewarm; i++) passo(G);
    enquadrar(false);
    atualizarBotaoSoltar();
  }
  function soltarTodos() {
    if (!G) return;
    for (let i = 0; i < G.n; i++) G.fixo[i] = 0;
    est.fixos = 0; G.alfa = Math.max(G.alfa, 0.3); est.sujo = true;
    atualizarBotaoSoltar();
  }
  function voltarAoPadrao() {
    for (let d = 0; d < filtro.length; d++) filtro[d] = 0;
    atualizarLegenda();
    if (!G || G.modo !== 'geral') { irGeral(true); return; }
    est.sel = -1; fecharDetalhe();
    for (let i = 0; i < G.n; i++) { G.fixo[i] = 0; G.vx[i] = G.vy[i] = 0; }
    est.fixos = 0; atualizarBotaoSoltar();
    aplicarEsc();
    camMexida = false;
    if (padrao) {
      const de = new Float64Array(G.n * 2);
      for (let i = 0; i < G.n; i++) { de[i * 2] = G.x[i]; de[i * 2 + 1] = G.y[i]; }
      tweenPos = { de, para: padrao, t0: agora(), ms: 1000, enquadrar: true };   // enquadra de novo quando as posições chegarem
      G.alfa = 0; G.alvoAlfa = 0;
    } else { G.alfa = 1; }
    enquadrar(true);
  }

  /* ==================================================================== 4. janela lateral, busca, legenda, painel, atualização */
  const painelLado = $('#detalhe');
  const dep = d => '<span class="chip"><i style="background:' + TEMA.cor[d] + '"></i>' + esc(M.D.deptos[d]) + '</span>';
  const bola = d => '<i class="bola" style="background:' + TEMA.cor[d] + ';color:' + TEMA.cor[d] + '"></i>';
  const arqNome = e => (M.arq[e] >= 0 ? M.D.arquivos[M.arq[e]] : '');
  const base = p => p.split('/').pop();
  const plural = (n, um, varios) => fmt(n) + ' ' + (n === 1 ? um : varios);

  function atualizarBotaoSoltar() {
    const b = $('#b-soltar');
    b.disabled = !est.fixos;
    b.textContent = est.fixos ? 'Soltar pontos (' + est.fixos + ')' : 'Soltar pontos';
  }
  function fecharDetalhe() { painelLado.classList.add('fechado'); }

  /* ---- reações do desenho ---- */
  function aoSelecionar(i) {
    est.sel = i; est.sujo = est.sujoFoco = true;
    abrirDetalhe(i);
    migalhas();
  }
  function aoDuploClique(i) {
    if (G.fixo[i]) { G.fixo[i] = 0; est.fixos--; G.alfa = Math.max(G.alfa, 0.3); atualizarBotaoSoltar(); est.sujo = true; return; }
    if (G.modo === 'geral') abrirGrupo(G.ref[i]);
    else if (G.tipo[i] === 3) irParaEnt(G.ref[i]);
    else centrarEm(i, 1.3);
  }
  function aoFundo() {
    if (est.sel < 0 && painelLado.classList.contains('fechado')) return;
    est.sel = -1; est.sujo = est.sujoFoco = true; fecharDetalhe(); migalhas();
  }
  const tip = $('#tooltip');
  function aoPassar(i, mx, my) {
    if (i < 0 || arrasto) { tip.hidden = true; return; }
    let sub;
    if (G.modo === 'geral') {
      const g = M.D.grupos[G.ref[i]];
      sub = M.D.deptos[g.d] + ' · ' + plural(g.t, 'item', 'itens') + ' · duplo clique abre';
    } else {
      const e = G.ref[i];
      sub = M.D.tipos[M.tipo[e]] + (M.arq[e] >= 0 ? ' · ' + base(arqNome(e)) + (e >= M.nF ? ':' + M.lin[e] : '') : '') + ' · ' + plural(M.grau[e], 'ligação', 'ligações');
    }
    tip.innerHTML = '<b>' + esc(G.nome[i]) + '</b><span>' + esc(sub) + '</span>';
    tip.hidden = false;
    const box = $('#vista-grafo').getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = clamp(mx + 16, 6, box.width - w - 6) + 'px';
    tip.style.top = clamp(my + 18, 6, box.height - h - 6) + 'px';
  }

  /* ---- navegação ---- */
  function irGeral(animar, depois) {
    const fazer = () => {
      const g0 = construirGeral(M);
      trocarGrafo(g0, 40);
      padrao = null; camMexida = false; migalhas(); fecharDetalhe();
      if (depois) depois();
    };
    if (animar) transicao(fazer); else fazer();
  }
  function abrirGrupo(g, focoEnt, antigos) {
    transicao(() => {
      trocarGrafo(construirGrupo(M, g, antigos), 150);
      camMexida = false;
      fecharDetalhe();
      if (focoEnt != null) {
        const i = indiceNoGrafo(focoEnt);
        if (i >= 0) { est.sel = i; abrirDetalhe(i); camMexida = true; refocar = true; centrarEm(i, 1.2); }
      }
      migalhas();
    });
  }
  function indiceNoGrafo(e) { for (let i = 0; i < G.n; i++) if (G.ref[i] === e && (G.modo === 'grupo')) return i; return -1; }
  function irParaEnt(e) {
    mostrarAba('grafo');
    if (G.modo === 'grupo') {
      const i = indiceNoGrafo(e);
      if (i >= 0 && !filtro[G.dep[i]]) { aoSelecionar(i); centrarEm(i, 1.2); return; }
    }
    abrirGrupo(M.grp[e], e);
  }
  function irParaGrupo(g) {
    mostrarAba('grafo');
    const sel = () => { if (filtro[G.dep[g]]) { filtro[G.dep[g]] = 0; aplicarEsc(); atualizarLegenda(); } aoSelecionar(g); centrarEm(g, 1.1); };
    if (G.modo !== 'geral') irGeral(true, () => setTimeout(sel, 40)); else sel();
  }
  function migalhas() {
    const el = $('#migalhas');
    let h = '';
    if (G.modo === 'geral') {
      h = '<span class="atual">Visão geral</span>';
      if (est.sel >= 0) h += '<span class="sep">›</span><span class="atual">' + esc(G.nome[est.sel]) + '</span><button type="button" class="bt pri comp" data-abrir="' + G.ref[est.sel] + '">Abrir grupo</button>';
      else h += '<span class="sep">·</span><span class="suave">' + plural(M.nG, 'grupo', 'grupos') + ', ' + plural(M.gs.length, 'ligação entre grupos', 'ligações entre grupos') + '</span>';
    } else {
      const g = M.D.grupos[G.grupo];
      h = '<button type="button" data-geral="1">Visão geral</button><span class="sep">›</span><span class="atual">' + esc(g.n) + '</span>' +
        '<span class="sep">·</span><span class="suave">' + plural(G.n - G.nGhost, 'ponto', 'pontos') + (G.nGhost ? ' + ' + G.nGhost + ' vizinhos de outros grupos' + (G.nVizinhos > G.nGhost ? ' (mostrando os mais ligados)' : '') : '') + '</span>';
    }
    el.innerHTML = h;
  }
  $('#migalhas').addEventListener('click', ev => {
    const a = ev.target.closest('[data-abrir]'), g = ev.target.closest('[data-geral]');
    if (a) abrirGrupo(+a.dataset.abrir);
    if (g) irGeral(true);
  });

  /* ---- janela lateral ---- */
  function abrirDetalhe(i) {
    painelLado.innerHTML = '<button type="button" class="fechar bt so" data-fechar="1" aria-label="Fechar">✕</button>' + (G.modo === 'geral' ? htmlGrupo(G.ref[i]) : htmlEnt(G.ref[i]));
    painelLado.classList.remove('fechado');
    painelLado.scrollTop = 0;
    if (!camMexida) { /* o enquadramento já considera o painel aberto */ }
  }
  painelLado.addEventListener('click', ev => {
    const t = ev.target.closest('button');
    if (!t) return;
    if (t.dataset.fechar) { est.sel = -1; est.sujo = est.sujoFoco = true; fecharDetalhe(); migalhas(); }
    else if (t.dataset.irEnt != null) irParaEnt(+t.dataset.irEnt);
    else if (t.dataset.irGrupo != null) irParaGrupo(+t.dataset.irGrupo);
    else if (t.dataset.abrir != null) abrirGrupo(+t.dataset.abrir);
    else if (t.dataset.tarefaEnt != null && window.CerebroTarefa) window.CerebroTarefa.abrir(pontoDaEnt(+t.dataset.tarefaEnt));
    else if (t.dataset.tarefaGrupo != null && window.CerebroTarefa) window.CerebroTarefa.abrir(pontoDoGrupo(+t.dataset.tarefaGrupo));
    else if (t.dataset.mais) {
      const ul = document.getElementById(t.dataset.mais);
      ul.classList.toggle('aberta');
      t.textContent = ul.classList.contains('aberta') ? 'ver menos' : t.dataset.rotulo;
    }
  });

  /* ---- "Criar tarefa aqui" (tarefa.js): o ponto do mapa que vai preenchido na tarefa para o gestor ---- */
  function pontoDaEnt(e) {
    const ehArq = e < M.nF;
    return { tipo: ehArq ? 'arquivo' : M.D.tipos[M.tipo[e]], nome: M.nome[e], arquivo: arqNome(e), linha: ehArq || !M.lin[e] ? null : M.lin[e],
      grupo: M.D.grupos[M.grp[e]].n, arquivos: [] };
  }
  function pontoDoGrupo(g) {
    const porArq = new Map();
    M.membros[g].forEach(e => { if (e >= M.nF && M.arq[e] >= 0) porArq.set(M.arq[e], (porArq.get(M.arq[e]) || 0) + 1); });
    const arqs = Array.from(porArq.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([a]) => M.D.arquivos[a]);
    return { tipo: 'grupo', nome: M.D.grupos[g].n, arquivo: '', linha: null, grupo: M.D.grupos[g].n, arquivos: arqs };
  }
  const botaoTarefa = (atributo, valor) => (window.CerebroTarefa ? '<button type="button" class="bt leve acao-grande" data-' + atributo + '="' + valor + '" title="Cria uma tarefa para o gestor já com este ponto do mapa">Criar tarefa aqui</button>' : '');

  function itemLista(e, inf, extra) {
    const g = M.grp[e];
    const resto = extra != null ? extra : (G.modo === 'grupo' && g !== G.grupo ? M.D.grupos[g].n : base(arqNome(e)));
    return '<li><button type="button" data-ir-ent="' + e + '">' + bola(M.dep[e]) + '<span class="nome">' + esc(M.nome[e]) + '</span>' +
      (inf ? '<span class="inf" title="ligação deduzida pelo Graphify, não escrita no código">inferida</span>' : '') +
      '<span class="resto">' + esc(resto) + '</span></button></li>';
  }
  let contadorLista = 0;
  function listaComMais(linhas, limite) {
    if (linhas.length <= limite) return '<ul class="lista">' + linhas.join('') + '</ul>';
    const id = 'lst' + (++contadorLista);
    const rotulo = 'ver mais (' + (linhas.length - limite) + ')';
    return '<ul class="lista cortada" id="' + id + '" style="--limite:' + limite + '">' + linhas.map((l, q) => q >= limite ? l.replace('<li>', '<li class="extra">') : l).join('') +
      '</ul><button type="button" class="mais" data-mais="' + id + '" data-rotulo="' + rotulo + '">' + rotulo + '</button>';
  }
  function fatos(lista) {
    return '<div class="fatos">' + lista.map(f => '<div class="fato"><b>' + esc(f[0]) + '</b><span>' + esc(f[1]) + '</span></div>').join('') + '</div>';
  }

  // Explicação escrita por IA (opcional, gerada na aba Mapa do painel): 0 = atual, 1 = desatualizada, -1 = o texto é do próprio código
  const ROTULO_IA = 'explicação automática (IA)';
  function iaDe(e) { return M.D.ia && M.D.ia[e] !== undefined ? M.D.ia[e] : -1; }

  function htmlGrupo(g) {
    const gr = M.D.grupos[g], mem = M.membros[g];
    const porArq = new Map();
    let itens = 0;
    mem.forEach(e => { if (e >= M.nF) { itens++; if (M.arq[e] >= 0) porArq.set(M.arq[e], (porArq.get(M.arq[e]) || 0) + 1); } });
    const arqs = Array.from(porArq.entries()).sort((a, b) => b[1] - a[1]);
    const top = mem.filter(e => e >= M.nF).sort((a, b) => M.grau[b] - M.grau[a]);
    let explica = '';
    for (const [a] of arqs.slice(0, 3)) {
      const t = M.D.expl[a];
      if (t) { explica = '<div class="explica"><small class="suave">' + (iaDe(a) >= 0 ? ROTULO_IA + ' de ' : 'Do cabeçalho de ') + esc(base(M.D.arquivos[a])) + ':</small>\n' + esc(t) + '</div>'; break; }
    }
    if (!explica) {
      for (const e of top.slice(0, 12)) {
        const t = M.D.expl[e];
        if (t) { explica = '<div class="explica"><small class="suave">' + (iaDe(e) >= 0 ? ROTULO_IA + ' de ' : 'Do comentário de ') + esc(M.nome[e]) + ':</small>\n' + esc(t) + '</div>'; break; }
      }
    }
    const resumo = 'Grupo do departamento ' + M.D.deptos[gr.d] + ' com ' + plural(gr.t, 'item', 'itens') + (arqs.length ? ' em ' + plural(arqs.length, 'arquivo', 'arquivos') : '') +
      '. ' + (top.length ? 'O mais ligado é ' + M.nome[top[0]] + ' (' + M.D.tipos[M.tipo[top[0]]] + ', ' + plural(M.grau[top[0]], 'ligação', 'ligações') + ').' : '');
    const viz = M.vizinhosG[g];
    return '<h2>' + esc(gr.n) + '</h2><div class="chips">' + dep(gr.d) + '<span class="chip">grupo</span></div>' +
      '<h4>O que é</h4><p class="resumo">' + esc(resumo) + '</p>' + (explica || '<div class="explica vazia">Nenhum arquivo deste grupo tem texto explicativo no começo; veja os fatos abaixo.</div>') +
      '<h4>Em números</h4>' + fatos([[fmt(gr.t), 'itens'], [fmt(arqs.length), 'arquivos'], [fmt(M.internas[g]), 'ligações internas'],
        [fmt(M.externas[g]), 'ligações p/ fora'], [fmt(viz.length), 'grupos vizinhos'], [Math.round(gr.c * 100) + '%', 'coesão']]) +
      '<button type="button" class="bt pri acao-grande" data-abrir="' + g + '">Abrir grupo (arquivos e funções)</button>' + botaoTarefa('tarefa-grupo', g) +
      '<h4>Ligado a (outros grupos)</h4>' + (viz.length ? listaComMais(viz.map(([o, w]) =>
        '<li><button type="button" data-ir-grupo="' + o + '">' + bola(M.D.grupos[o].d) + '<span class="nome">' + esc(M.D.grupos[o].n) + '</span><span class="resto">' + fmt(w) + (w === 1 ? ' ligação' : ' ligações') + '</span></button></li>'), 10)
        : '<p class="vazio">Sem ligações com outros grupos.</p>') +
      '<h4>Arquivos do grupo</h4>' + listaComMais(arqs.map(([a, c]) =>
        '<li><button type="button" data-ir-ent="' + a + '">' + bola(M.dep[a]) + '<span class="nome">' + esc(base(M.D.arquivos[a])) + '</span><span class="resto">' + esc(M.D.arquivos[a].replace(/\/[^/]*$/, '') || '/') + ' · ' + c + '</span></button></li>'), 8) +
      '<h4>Itens mais ligados</h4>' + listaComMais(top.slice(0, 30).map(e => itemLista(e, false, plural(M.grau[e], 'ligação', 'ligações'))), 8);
  }

  function htmlEnt(e) {
    const tipo = M.tipo[e], ehArq = e < M.nF;
    const caminho = arqNome(e);
    const sub = caminho ? caminho + (ehArq ? '' : ':' + M.lin[e]) : 'dependência externa (fora do projeto)';
    const gr = M.D.grupos[M.grp[e]];
    let explica = M.D.expl[e];
    let blocoExp;
    if (explica) blocoExp = '<div class="explica">' + (iaDe(e) >= 0 ? '<small class="suave">' + ROTULO_IA + (iaDe(e) === 1 ? ' · desatualizada: o código mudou depois' : '') + ':</small>\n' : '') + esc(explica) + '</div>';
    else {
      const donoArq = !ehArq && M.arq[e] >= 0 ? M.D.expl[M.arq[e]] : '';
      blocoExp = '<div class="explica vazia">Nenhum comentário nem docstring explica o que ' + esc(M.nome[e]) + ' faz.' +
        (donoArq ? ' O arquivo diz:\n' + esc(donoArq) : ' Só os fatos abaixo estão no mapa.') + '</div>';
    }
    // "ligado a": agrupado pela frase
    const grupos = new Map();
    for (let p = M.off[e]; p < M.off[e + 1]; p++) {
      const rel = M.D.relacoes[M.adjR[p] >> 1], dir = M.adjD[p];
      const frase = (FRASE[rel] || [rel, rel])[dir];
      const chave = rel + '|' + dir;
      if (!grupos.has(chave)) grupos.set(chave, { frase, itens: [] });
      grupos.get(chave).itens.push([M.adjA[p], M.adjR[p] & 1]);
    }
    const blocos = Array.from(grupos.values()).sort((a, b) => b.itens.length - a.itens.length);
    let ligas = '';
    if (!ehArq && M.arq[e] >= 0) {
      ligas += '<div class="rel"><div class="titulo">faz parte do arquivo <small>1</small></div><ul class="lista">' + itemLista(M.arq[e], false, M.D.arquivos[M.arq[e]].replace(/\/[^/]*$/, '') || '/') + '</ul></div>';
    }
    if (ehArq) {
      const conteudo = M.itensDoArq[e].slice().sort((a, b) => M.grau[b] - M.grau[a]);
      if (conteudo.length) ligas += '<div class="rel"><div class="titulo">contém <small>' + conteudo.length + '</small></div>' + listaComMais(conteudo.map(x => itemLista(x, false, M.D.tipos[M.tipo[x]])), 8) + '</div>';
    }
    blocos.forEach(b => {
      b.itens.sort((x, y) => M.grau[y[0]] - M.grau[x[0]]);
      ligas += '<div class="rel"><div class="titulo">' + esc(b.frase) + ' <small>' + b.itens.length + '</small></div>' + listaComMais(b.itens.slice(0, 300).map(([o, inf]) => itemLista(o, inf)), 8) + '</div>';
    });
    if (!ligas) ligas = '<p class="vazio">Sem ligações registradas no mapa.</p>';
    let acima = 0;
    for (let i = 0; i < M.nn; i++) if (M.grau[i] > M.grau[e]) acima++;
    let inferidas = 0;
    for (let p = M.off[e]; p < M.off[e + 1]; p++) inferidas += M.adjR[p] & 1;
    let saindo = 0;
    for (let p = M.off[e]; p < M.off[e + 1]; p++) if (M.adjD[p] === 0) saindo++;
    const grupoBtn = '<button type="button" class="chip" data-ir-grupo="' + M.grp[e] + '" title="Ver o grupo na visão geral">grupo: ' + esc(gr.n) + '</button>';
    return '<h2>' + esc(M.nome[e]) + '</h2><div class="sub">' + esc(sub) + '</div>' +
      '<div class="chips">' + dep(M.dep[e]) + '<span class="chip">' + esc(M.D.tipos[tipo]) + '</span>' + grupoBtn + '</div>' +
      '<h4>O que faz</h4>' + blocoExp +
      '<h4>Em números</h4>' + fatos([[fmt(M.grau[e]), 'ligações'], [fmt(saindo), 'saindo'], [fmt(M.grau[e] - saindo), 'chegando'],
        ['#' + fmt(acima + 1), 'mais ligado de ' + fmt(M.nn)], [fmt(inferidas), 'inferidas'], [ehArq ? fmt(M.itensDoArq[e].length) : (M.lin[e] ? 'L' + M.lin[e] : '—'), ehArq ? 'itens dentro' : 'linha']]) +
      (G.modo === 'grupo' && M.grp[e] !== G.grupo ? '<button type="button" class="bt pri acao-grande" data-ir-ent="' + e + '">Ir para o grupo deste item</button>' : '') + botaoTarefa('tarefa-ent', e) +
      '<h4>Ligado a</h4>' + ligas;
  }

  /* ---- legenda dos departamentos ---- */
  function montarLegenda() {
    const el = $('#legenda');
    const recolhida = ler('mapa.legenda') === '0';
    el.classList.toggle('recolhida', recolhida);
    let h = '<h3><button type="button" class="dobrar" data-dobrar="1" aria-expanded="' + !recolhida + '" title="Mostra ou esconde a lista de departamentos">Departamentos <span aria-hidden="true">' + (recolhida ? '▸' : '▾') + '</span></button><button type="button" data-todos="1">mostrar todos</button></h3>';
    M.D.deptos.forEach((nome, d) => {
      h += '<button type="button" class="item" data-dep="' + d + '" title="Clique para esconder ou mostrar; passe o mouse para destacar"><span class="bola" style="background:' + TEMA.cor[d] + ';color:' + TEMA.cor[d] + '"></span><span class="nome">' + esc(nome) + '</span><span class="num">' + fmt(M.deptoGrupos[d]) + '</span></button>';
    });
    el.innerHTML = h;
  }
  function atualizarLegenda() {
    document.querySelectorAll('#legenda .item').forEach(b => b.classList.toggle('off', !!filtro[+b.dataset.dep]));
    if (G) aplicarEsc();
  }
  $('#legenda').addEventListener('click', ev => {
    const b = ev.target.closest('button');
    if (!b) return;
    if (b.dataset.dobrar) {                                // recolhe / abre a legenda (lembrado)
      salvar('mapa.legenda', $('#legenda').classList.contains('recolhida') ? '1' : '0');
      montarLegenda(); atualizarLegenda(); return;
    }
    if (b.dataset.todos) { filtro.fill(0); }
    else if (ev.detail === 2 || ev.shiftKey) {            // duplo clique ou Shift: só este
      const d = +b.dataset.dep;
      filtro.fill(1); filtro[d] = 0;
    } else { const d = +b.dataset.dep; filtro[d] = filtro[d] ? 0 : 1; }
    atualizarLegenda();
  });
  $('#legenda').addEventListener('pointerover', ev => {
    const b = ev.target.closest('.item');
    const d = b ? +b.dataset.dep : -1;
    if (d !== est.deptoHover) { est.deptoHover = d; est.sujoFoco = est.sujo = true; }
  });
  $('#legenda').addEventListener('pointerleave', () => { est.deptoHover = -1; est.sujoFoco = est.sujo = true; });

  /* ---- busca ---- */
  let sugestoes = [], ativo = -1;
  function indiceBusca() {
    if (M.indiceBusca) return M.indiceBusca;
    const lista = [];
    M.D.grupos.forEach((g, i) => lista.push({ t: 'g', id: i, n: g.n, k: norm(g.n), peso: 0 }));
    for (let e = 0; e < M.nn; e++) {
      if (M.tipo[e] === 5) continue;
      lista.push({ t: e < M.nF ? 'a' : 'e', id: e, n: M.nome[e], k: norm(M.nome[e] + ' ' + (e < M.nF ? M.D.arquivos[e] : base(arqNome(e)))), peso: e < M.nF ? 1 : 2 });
    }
    M.indiceBusca = lista;
    return lista;
  }
  function buscar(q) {
    q = norm(q.trim());
    if (!q) return [];
    const res = [];
    for (const it of indiceBusca()) {
      const p = it.k.indexOf(q);
      if (p < 0) continue;
      const nome = norm(it.n);
      const pontos = (nome === q ? 0 : nome.startsWith(q) ? 1 : p === 0 ? 2 : 3) * 10 + it.peso;
      res.push([pontos, it]);
    }
    res.sort((a, b) => a[0] - b[0] || a[1].n.length - b[1].n.length);
    return res.slice(0, 12).map(r => r[1]);
  }
  function mostrarSugestoes() {
    const ul = $('#sugestoes');
    if (!sugestoes.length) { ul.hidden = true; return; }
    ul.innerHTML = sugestoes.map((s, i) => {
      const d = s.t === 'g' ? M.D.grupos[s.id].d : M.dep[s.id];
      const rot = s.t === 'g' ? 'grupo' : s.t === 'a' ? 'arquivo' : M.D.tipos[M.tipo[s.id]];
      const sub = s.t === 'g' ? plural(M.D.grupos[s.id].t, 'item', 'itens') : s.t === 'a' ? M.D.arquivos[s.id] : base(arqNome(s.id)) + ' · ' + M.D.grupos[M.grp[s.id]].n;
      return '<li data-i="' + i + '" class="' + (i === ativo ? 'ativo' : '') + '">' + bola(d) + '<span class="nome">' + esc(s.n) + '</span><span class="tipo">' + esc(rot) + '</span><span class="sub">' + esc(sub) + '</span></li>';
    }).join('');
    ul.hidden = false;
  }
  function escolher(s) {
    $('#sugestoes').hidden = true; $('#busca').value = '';
    sugestoes = []; ativo = -1;
    if (s.t === 'g') irParaGrupo(s.id); else irParaEnt(s.id);
  }
  const campo = $('#busca');
  campo.addEventListener('input', () => { sugestoes = buscar(campo.value); ativo = sugestoes.length ? 0 : -1; mostrarSugestoes(); });
  campo.addEventListener('keydown', ev => {
    if (ev.key === 'ArrowDown') { ativo = Math.min(sugestoes.length - 1, ativo + 1); mostrarSugestoes(); ev.preventDefault(); }
    else if (ev.key === 'ArrowUp') { ativo = Math.max(0, ativo - 1); mostrarSugestoes(); ev.preventDefault(); }
    else if (ev.key === 'Enter' && sugestoes[ativo]) escolher(sugestoes[ativo]);
    else if (ev.key === 'Escape') { campo.value = ''; sugestoes = []; mostrarSugestoes(); campo.blur(); }
  });
  $('#sugestoes').addEventListener('mousedown', ev => {
    const li = ev.target.closest('li');
    if (li) { ev.preventDefault(); escolher(sugestoes[+li.dataset.i]); }
  });
  campo.addEventListener('blur', () => setTimeout(() => { $('#sugestoes').hidden = true; }, 120));
  campo.addEventListener('focus', () => { if (sugestoes.length) mostrarSugestoes(); });
  document.addEventListener('keydown', ev => {
    if (ev.target.closest && ev.target.closest('input')) return;
    if (ev.key === '/') { ev.preventDefault(); campo.focus(); }
    else if (ev.key === 'Escape') aoFundo();
    else if (ev.key === '0') voltarAoPadrao();
  });

  /* ---- abas, botões ---- */
  function mostrarAba(a) {
    document.querySelectorAll('.abas button').forEach(b => b.classList.toggle('ativa', b.dataset.aba === a));
    $('#vista-grafo').hidden = a !== 'grafo';
    $('#vista-painel').hidden = a !== 'painel';
    if (a === 'grafo') { redimensionar(); est.sujo = true; } else renderPainel();
  }
  document.querySelectorAll('.abas button').forEach(b => b.addEventListener('click', () => mostrarAba(b.dataset.aba)));
  $('#b-padrao').addEventListener('click', () => { mostrarAba('grafo'); voltarAoPadrao(); });
  $('#b-centro').addEventListener('click', () => { camMexida = false; enquadrar(true); });
  $('#b-soltar').addEventListener('click', soltarTodos);
  $('#b-pulsos').addEventListener('click', () => {
    est.pulsos = !est.pulsos; $('#b-pulsos').setAttribute('aria-pressed', String(est.pulsos)); salvar('pulsos', est.pulsos ? '1' : '0'); est.sujo = true;
  });
  $('#b-tema').addEventListener('click', () => { aplicarTema(!TEMA.escuro); montarLegenda(); atualizarLegenda(); if (!$('#vista-painel').hidden) renderPainel(); });

  /* ---- espaçamento entre os pontos (− / +), lembrado neste navegador ---- */
  function mostrarEspaco() {
    $('#esp-valor').textContent = 'Espaço ' + Math.round(100 * ESPACO.f / ESPACO.padrao) + '%';
    $('#b-esp-menos').disabled = ESPACO.f <= ESPACO.min + 1e-6;
    $('#b-esp-mais').disabled = ESPACO.f >= ESPACO.max - 1e-6;
  }
  function mudarEspaco(delta) {
    ESPACO.f = clamp(Math.round((ESPACO.f + delta) * 100) / 100, ESPACO.min, ESPACO.max);
    salvar('mapa.espaco', String(ESPACO.f));
    mostrarEspaco();
    if (!M || !G) return;
    if (G.modo === 'grupo') abrirGrupo(G.grupo); else irGeral(true);      // refaz o desenho e enquadra tudo de novo
  }
  $('#b-esp-menos').addEventListener('click', () => mudarEspaco(-0.25));
  $('#b-esp-mais').addEventListener('click', () => mudarEspaco(0.25));
  mostrarEspaco();

  /* ---- faixa de números: recolhível (lembrada) ---- */
  function mostrarFaixa(ver) {
    $('#faixa').hidden = !ver;
    $('#b-numeros').setAttribute('aria-pressed', String(ver));
    salvar('mapa.faixa', ver ? '1' : '0');
  }
  $('#b-numeros').addEventListener('click', () => mostrarFaixa($('#faixa').hidden));
  mostrarFaixa(ler('mapa.faixa') !== '0');

  /* ---- faixa de números e cabeçalho ---- */
  function renderFaixa() {
    const t = D.meta.totais, ger = D.config && D.config.sessaoGestora;
    $('#subtitulo').textContent = 'mapa de ' + dataBonita(D.meta.data) + ' · commit ' + (D.meta.commit || '').slice(0, 7) + (D.meta.ramo ? ' · ' + D.meta.ramo : '');
    const gb = $('#gestor');
    if (ger && ger.nome) { gb.hidden = false; gb.innerHTML = '<span class="rot">Gestor</span><b>' + esc(ger.nome) + '</b>'; gb.title = 'Sessão gestora' + (ger.conversa ? ' · conversa ' + ger.conversa : '') + ' (troque em Configurações do projeto, no Cérebro)'; }
    else { gb.hidden = false; gb.innerHTML = '<span class="rot">Gestor</span><b>não escolhida</b>'; gb.title = 'Escolha a sessão gestora em Configurações do projeto, no Cérebro'; }
    const cards = [
      ['Grupos', fmt(t.grupos), 'áreas do código', 0], ['Arquivos', fmt(t.arquivos), 'no mapa', 1],
      ['Funções e itens', fmt(t.itens), plural(M.D.deptos.length, 'departamento', 'departamentos'), 2], ['Ligações', fmt(t.ligacoes), 'entre itens', 3],
      ['Explicados', Math.round(100 * t.explicados / (t.itens + t.arquivos)) + '%', fmt(t.explicados) + ' com texto do código' + (t.explicadosIA ? ' (+ ' + fmt(t.explicadosIA) + ' por IA)' : ''), 4],
      ['Atualizado', haQuanto(D.meta.data), dataBonita(D.meta.data), 5],
    ];
    $('#faixa').innerHTML = cards.map(c => '<div class="numero" data-n="' + c[3] + '" title="' + esc(c[2]) + '"><span class="rot">' + esc(c[0]) + '</span><b>' + esc(c[1]) + '</b><small>' + esc(c[2]) + '</small></div>').join('');
  }

  /* ---- painel (dashboard de leitura) ---- */
  const REL_PT = r => ROTULO_REL[r] || r;
  function barra(cor, rot, valor, max, txt, dados) {
    return '<button type="button" class="barra" ' + dados + '><span class="rot"><i style="background:' + cor + '"></i>' + esc(rot) + '</span><span class="trilho"><span style="width:' + Math.max(1.5, 100 * valor / max) + '%;background:' + cor + '"></span></span><span class="val">' + esc(txt) + '</span></button>';
  }
  function chipsMudanca(m) {
    if (!m) return '';
    const out = [];
    const add = (o, nome1, nomeN) => {
      if (o.nEntrou) out.push('<span class="mais-n">+' + fmt(o.nEntrou) + ' ' + (o.nEntrou === 1 ? nome1 : nomeN) + '</span>');
      if (o.nSaiu) out.push('<span class="menos-n">−' + fmt(o.nSaiu) + ' ' + (o.nSaiu === 1 ? nome1 : nomeN) + '</span>');
    };
    add(m.arquivos, 'arquivo', 'arquivos'); add(m.grupos, 'grupo', 'grupos'); add(m.itens, 'item', 'itens'); add(m.ligacoes, 'ligação', 'ligações');
    return out.join('');
  }
  function listaMud(titulo, classe, itens, total, tipo) {
    if (!total) return '';
    const li = itens.map(x => {
      if (tipo === 'arq') { const e = M.D.arquivos.indexOf(x); return '<li>' + (e >= 0 ? '<button type="button" data-ir-ent="' + e + '">' + esc(x) + '</button>' : esc(x)) + '</li>'; }
      if (tipo === 'grupo') { const g = M.grupoPorNome.get(x); return '<li>' + (g != null ? '<button type="button" data-ir-grupo="' + g + '">' + esc(x) + '</button>' : esc(x)) + '</li>'; }
      if (tipo === 'item') { const e = M.porChave.get(x[1] + '\u0000' + x[0]); return '<li>' + (e != null ? '<button type="button" data-ir-ent="' + e + '">' + esc(x[0]) + '</button>' : esc(x[0])) + ' <small>' + esc(x[1]) + '</small></li>'; }
      return '<li>' + esc(x[0]) + ' <small>' + esc((FRASE[x[1]] || [x[1]])[0]) + '</small> ' + esc(x[2]) + '</li>';
    }).join('');
    return '<div><h5 class="' + classe + '">' + (classe === 'ent' ? 'Entrou' : 'Saiu') + ' · ' + esc(titulo) + ' (' + fmt(total) + ')</h5><ul>' + li + '</ul>' +
      (total > itens.length ? '<small class="vazio">e mais ' + fmt(total - itens.length) + '…</small>' : '') + '</div>';
  }
  function corpoTempo(h) {
    if (h.inicial || !h.mudancas) return '<p class="vazio">Primeira geração: é o mapa de referência. As próximas comparações mostram o que entrou, saiu ou mudou a partir daqui.</p><div class="fatos">' +
      [[h.totais.grupos, 'grupos'], [h.totais.arquivos, 'arquivos'], [h.totais.itens, 'itens'], [h.totais.ligacoes, 'ligações']].map(f => '<div class="fato"><b>' + fmt(f[0]) + '</b><span>' + f[1] + '</span></div>').join('') + '</div>';
    const m = h.mudancas;
    const partes = [
      listaMud('arquivos', 'ent', m.arquivos.entrou, m.arquivos.nEntrou, 'arq'), listaMud('arquivos', 'sai', m.arquivos.saiu, m.arquivos.nSaiu, 'arq'),
      listaMud('grupos', 'ent', m.grupos.entrou, m.grupos.nEntrou, 'grupo'), listaMud('grupos', 'sai', m.grupos.saiu, m.grupos.nSaiu, 'grupo'),
      listaMud('funções e itens', 'ent', m.itens.entrou, m.itens.nEntrou, 'item'), listaMud('funções e itens', 'sai', m.itens.saiu, m.itens.nSaiu, 'item'),
      listaMud('ligações', 'ent', m.ligacoes.entrou, m.ligacoes.nEntrou, 'lig'), listaMud('ligações', 'sai', m.ligacoes.saiu, m.ligacoes.nSaiu, 'lig'),
    ].filter(Boolean);
    return partes.length ? '<div class="dois">' + partes.join('') + '</div>' : '<p class="vazio">Mapa refeito sem mudança em arquivos, grupos, itens ou ligações.</p>';
  }
  let abertoTempo = 0;
  function renderPainel() {
    const t = D.meta.totais, el = $('#vista-painel');
    const nd = M.nd, maxItens = Math.max(...Array.from(M.deptoItens));
    const ger = D.config && D.config.sessaoGestora;
    let h = '<div class="grade">';
    h += '<div class="cartao gestor"><h3>Sessão gestora</h3>' + (ger && ger.nome ? '<p class="gestor-nome">' + esc(ger.nome) + '</p><dl class="kv"><dt>Conversa</dt><dd><code>' + esc(ger.conversa || '—') + '</code></dd></dl>' : '<p class="vazio">Nenhuma sessão definida.</p>') +
      '<p class="vazio">Para trocar, use a aba Configurações do projeto no Cérebro (a escolha vale logo aqui, sem refazer o mapa).</p></div>';
    h += '<div class="cartao"><h3>Última atualização</h3><dl class="kv"><dt>Mapa gerado</dt><dd>' + esc(dataBonita(D.meta.data)) + ' (' + esc(haQuanto(D.meta.data)) + ')</dd>' +
      '<dt>Commit</dt><dd><code title="' + esc(D.meta.commit) + '">' + esc((D.meta.commit || '').slice(0, 10)) + '</code></dd><dt>Ramo</dt><dd>' + esc(D.meta.ramo || '—') + '</dd>' +
      '<dt>Página montada</dt><dd>' + esc(dataBonita(D.meta.geradoEm)) + '</dd><dt>Graphify</dt><dd>' + esc(D.meta.versaoGraphify || '—') + '</dd>' +
      '<dt>Atualização</dt><dd>confere a cada 30 s se saiu mapa novo</dd></dl></div>';
    h += '<div class="cartao"><h3>Maiores centros (mais ligações)</h3>' + (D.gods.length ? D.gods.map(g => {
      return barra(TEMA.cor[M.dep[g.e]], M.nome[g.e], g.g, D.gods[0].g, fmt(g.g) + ' lig.', 'data-ir-ent="' + g.e + '" title="' + esc(arqNome(g.e)) + '"');
    }).join('') : '<p class="vazio">Sem dados.</p>') + '</div>';
    h += '<div class="cartao"><h3>Surpresas (ligações inesperadas)</h3>' + (D.surpresas.length ? D.surpresas.map(s => {
      const ea = s.ea >= 0 ? s.ea : null, eb = s.eb >= 0 ? s.eb : null;
      const nome = (n, e) => e != null ? '<button type="button" class="mini" data-ir-ent="' + e + '">' + esc(n) + '</button>' : '<b>' + esc(n) + '</b>';
      return '<div class="surpresa">' + nome(s.a, ea) + ' <span class="seta">→ ' + esc((FRASE[s.rel] || [s.rel])[0]) + ' →</span> ' + nome(s.b, eb) + '<small>' + esc(s.fa) + ' ⇄ ' + esc(s.fb) + '<br>' + esc(s.por.replace(/`/g, '')) + '</small></div>';
    }).join('') : '<p class="vazio">Nenhuma surpresa registrada.</p>') + '</div>';
    h += '<div class="cartao"><h3>Por departamento</h3>' + D.deptos.map((nome, d) => barra(TEMA.cor[d], nome, M.deptoItens[d], maxItens,
      fmt(M.deptoItens[d]) + ' itens · ' + M.deptoGrupos[d] + ' grupos', 'data-solo="' + d + '" title="Mostrar só este departamento no cérebro"')).join('') + '</div>';
    // quem fala com quem
    let maxM = 1; for (let i = 0; i < M.matriz.length; i++) if (M.matriz[i] > maxM) maxM = M.matriz[i];
    let mx = '<div class="matriz" style="grid-template-columns:auto repeat(' + nd + ',minmax(18px,1fr))"><span></span>';
    for (let c = 0; c < nd; c++) mx += '<span class="cab" title="' + esc(D.deptos[c]) + '"><i style="background:' + TEMA.cor[c] + '"></i></span>';
    for (let r = 0; r < nd; r++) {
      mx += '<span class="lado"><i style="background:' + TEMA.cor[r] + '"></i>' + esc(D.deptos[r]) + '</span>';
      for (let c = 0; c < nd; c++) {
        const v = M.matriz[r * nd + c];
        const a = v ? 0.12 + 0.88 * Math.log(1 + v) / Math.log(1 + maxM) : 0.04;
        mx += '<span class="cel" style="background:' + 'var(--accent)' + ';opacity:' + a.toFixed(2) + '" title="' + esc(D.deptos[r] + ' → ' + D.deptos[c] + ': ' + fmt(v) + ' ligações') + '"></span>';
      }
    }
    h += '<div class="cartao"><h3>Quem fala com quem (ligações entre departamentos)</h3>' + mx + '</div></div>';
    const maxR = Math.max(...Array.from(M.porRel));
    h += '<div class="cartao"><h3>Tipos de ligação</h3>' + D.relacoes.map((r, i) => M.porRel[i] ? barra('var(--accent)', REL_PT(r), M.porRel[i], maxR, fmt(M.porRel[i]), 'disabled') : '').join('') + '</div>';
    h += '<div class="cartao largo"><h3>Linha do tempo — o que entrou, saiu ou mudou</h3><ol class="tempo">' + (D.historico || []).map((x, i) => {
      const quando = dataBonita(x.data);
      return '<li class="' + (i === abertoTempo ? 'aberto' : '') + '"><button type="button" class="cab" data-tempo="' + i + '"><span class="quando">' + esc(quando) + '</span><span class="commit">' + esc((x.commit || '').slice(0, 7)) + (x.ramo ? ' · ' + esc(x.ramo) : '') + '</span>' +
        (x.inicial ? '<span class="etq">primeira geração</span>' : '') + '<span class="mais-menos">' + chipsMudanca(x.mudancas) + '</span></button><div class="corpo">' + corpoTempo(x) + '</div></li>';
    }).join('') + '</ol></div>';
    h += '</div>';
    el.innerHTML = h;
  }
  $('#vista-painel').addEventListener('click', ev => {
    const t = ev.target.closest('button');
    if (!t) return;
    if (t.dataset.tempo != null) { abertoTempo = abertoTempo === +t.dataset.tempo ? -1 : +t.dataset.tempo; renderPainel(); }
    else if (t.dataset.irEnt != null) irParaEnt(+t.dataset.irEnt);
    else if (t.dataset.irGrupo != null) irParaGrupo(+t.dataset.irGrupo);
    else if (t.dataset.solo != null) {
      const d = +t.dataset.solo; filtro.fill(1); filtro[d] = 0;
      mostrarAba('grafo'); if (G.modo !== 'geral') irGeral(false);
      atualizarLegenda();
      camMexida = false; enquadrar(true);
    }
  });

  /* ---- atualização automática ---- */
  function aviso(txt) {
    const el = $('#aviso');
    el.textContent = txt; el.hidden = false;
    clearTimeout(aviso.t);
    aviso.t = setTimeout(() => { el.hidden = true; }, 7000);
  }
  function aplicarNovosDados(nova) {
    const velho = D;
    const antigos = new Map();
    if (G) for (let i = 0; i < G.n; i++) antigos.set(G.chave[i], [G.x[i], G.y[i], G.fixo[i]]);
    const chaveSel = G && est.sel >= 0 ? G.chave[est.sel] : null;
    const modoAnt = G ? G.modo : 'geral', nomeGrupo = G && G.modo === 'grupo' ? velho.grupos[G.grupo].n : null;
    D = nova; window.CEREBRO = nova;
    M = preparar(D);
    aplicarTema(TEMA.escuro);
    montarLegenda(); atualizarLegenda(); renderFaixa();
    const cx = cam.x, cy = cam.y, ck = cam.k, mexida = camMexida;
    if (modoAnt === 'grupo' && M.grupoPorNome.has(nomeGrupo)) {
      const g = M.grupoPorNome.get(nomeGrupo);
      trocarGrafo(construirGrupo(M, g, antigos), 0);
    } else {
      trocarGrafo(construirGeral(M, antigos), 0);
    }
    cam.x = cx; cam.y = cy; cam.k = ck; camMexida = mexida; camAnim = null;
    if (chaveSel) { const i = G.chave.indexOf(chaveSel); if (i >= 0) { est.sel = i; abrirDetalhe(i); } else fecharDetalhe(); } else fecharDetalhe();
    migalhas();
    if (!$('#vista-painel').hidden) renderPainel();
    const h = (D.historico || [])[0];
    const m = h && h.mudancas;
    let txt = 'Mapa atualizado';
    if (m) {
      const mais = m.arquivos.nEntrou + m.itens.nEntrou, menos = m.arquivos.nSaiu + m.itens.nSaiu;
      txt = 'Atualizado: +' + fmt(mais) + ' / −' + fmt(menos) + ' (' + fmt(m.ligacoes.nEntrou) + ' ligações novas)';
    }
    aviso(txt);
  }
  /* A sessão gestora vem do config.json do Cérebro: o servidor a entrega em gestora.json (vale na hora, sem refazer o mapa). */
  function buscarGestora() {
    if (!window.fetch || location.protocol === 'file:') return;
    fetch('gestora.json?t=' + Date.now(), { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(g => {
      if (!g || !D) return;
      const antes = JSON.stringify(D.config && D.config.sessaoGestora);
      D.config = Object.assign({}, D.config, { sessaoGestora: g });
      if (JSON.stringify(g) !== antes) { renderFaixa(); if (!$('#vista-painel').hidden) renderPainel(); }
    }).catch(() => {});
  }
  function conferirAtualizacao() {
    if (document.hidden) return;
    buscarGestora();
    const s = document.createElement('script');
    s.charset = 'utf-8';
    s.src = 'dados.js?t=' + Date.now();
    const anterior = D;
    s.onload = () => {
      s.remove();
      const nova = window.CEREBRO;
      if (nova && nova !== anterior && nova.meta && (nova.meta.commit !== anterior.meta.commit || nova.meta.hash !== anterior.meta.hash)) aplicarNovosDados(nova);
      else window.CEREBRO = anterior;
    };
    s.onerror = () => s.remove();
    document.head.appendChild(s);
  }

  /* ---- partida ---- */
  function iniciar() {
    if (!D || !D.nos) {
      $('#carregando').innerHTML = '<div class="erro">Não achei o mapa (dados.js).<br>Gere com <code>python mapa/gerar.py --projeto &lt;pasta do projeto&gt;</code> e abra de novo.</div>';
      $('#carregando').classList.remove('some');
      return;
    }
    const t0 = agora();
    M = preparar(D);
    est.pulsos = ler('pulsos') !== '0' && !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    $('#b-pulsos').setAttribute('aria-pressed', String(est.pulsos));
    aplicarTema(ler('tema') !== 'claro');
    montarLegenda(); renderFaixa(); buscarGestora();
    redimensionar();
    trocarGrafo(construirGeral(M), 45);
    migalhas();
    requestAnimationFrame(laco);
    requestAnimationFrame(() => { $('#carregando').classList.add('some'); });
    setTimeout(() => $('#dica').classList.add('some'), 16000);
    setInterval(conferirAtualizacao, 30000);
    setInterval(() => { if (!document.hidden) renderFaixa(); }, 60000);
    window.__cerebro = {
      preparoMs: Math.round(agora() - t0), abrirGrupo, irGeral, irParaEnt, irParaGrupo, mostrarAba, aplicarNovosDados, conferirAtualizacao,
      estado: () => ({ modo: G.modo, n: G.n, links: G.ls.length, alfa: G.alfa, k: cam.k, fixos: est.fixos, ligacoes: M.D.meta.totais.ligacoes }),
      selecionar: i => aoSelecionar(i), cam, medidas, grafo: () => G, sel: () => est.sel,
    };
  }
  iniciar();
})();
