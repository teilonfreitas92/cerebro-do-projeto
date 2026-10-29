"""Departamentos do mapa configuráveis por projeto (usado pelo gerar.py e pelo servidor, para validar o que vem da página).

Dois jeitos de dividir o projeto em departamentos (cor + nome), guardados em config.json > departamentos > <slug>:
  * modo "regras"   lista de departamentos, cada um com nome, cor, caminhos e (opcional) "ancora" [x, y] da posição no mapa;
                    vale o PRIMEIRO departamento da lista que casar;
  * sem entrada     automático pelas pastas de primeiro nível (as 10 maiores; o resto vira "Outros"), cores automáticas.
Um caminho é uma regra sobre o caminho do arquivo (sem diferenciar maiúsculas):
    "programa/"      começa por programa/ (ou tem /programa/ no meio)
    "*.test.js"      curinga (* e ?) sobre o caminho inteiro ou só o nome do arquivo
    "chat"           contém a palavra em qualquer parte do caminho
    "re:^src/.*\\.ts$" expressão regular sobre o caminho em minúsculas (para quem precisa de mais controle)
"""
import fnmatch
import re
from collections import Counter

CORES = ["#29e0a0", "#3cc8f5", "#ffb340", "#ff5fd2", "#8c8cff", "#bfe84a", "#ff7a52", "#4d94ff", "#bb6dff", "#ff4f6d", "#e0cfa2", "#8f9bb0"]
COR_PADRAO = "#8f9bb0"
_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


_regex_cache = {}


def _regex(texto):
    r = _regex_cache.get(texto)
    if r is None:
        try:
            r = re.compile(texto)
        except re.error:
            r = False
        _regex_cache[texto] = r
    return r


def casa_padrao(padrao, caminho):
    bruto = (padrao or "").strip()
    c = (caminho or "").lower().replace("\\", "/")
    if bruto[:3].lower() == "re:":
        r = _regex(bruto[3:])
        return bool(r) and r.search(c) is not None
    p = bruto.lower().replace("\\", "/")
    if not p:
        return False
    if any(ch in p for ch in "*?["):
        return fnmatch.fnmatchcase(c, p) or fnmatch.fnmatchcase(c.rsplit("/", 1)[-1], p)
    if p.endswith("/"):
        return c.startswith(p) or ("/" + p) in c
    return p in c


class Esquema:
    """nomes[i] e cores[i] descrevem o departamento i; indice(caminho) devolve o i do caminho (ou -1)."""

    def __init__(self, nomes, cores, funcao, padrao, ancoras=None):
        self.nomes, self.cores, self._f, self.padrao = list(nomes), list(cores), funcao, padrao
        self.ancoras = list(ancoras) if ancoras else [None] * len(self.nomes)      # posição no mapa (opcional) de cada departamento
        self._idx = {n: i for i, n in enumerate(self.nomes)}

    def indice(self, caminho):
        d = self._f(caminho)
        return self._idx.get(d, -1) if d else -1

    @property
    def indice_padrao(self):
        return self._idx.get(self.padrao, 0)


def validar(conf):
    """Valida/limpa a configuração vinda da página. Devolve dict limpo ou levanta ValueError."""
    if not isinstance(conf, dict):
        raise ValueError("configuração de departamentos inválida")
    modo = conf.get("modo")
    if modo == "pastas":
        return {"modo": modo}
    if modo != "regras":
        raise ValueError("modo precisa ser 'regras' ou 'pastas'")
    deptos = conf.get("deptos")
    if not isinstance(deptos, list) or not 1 <= len(deptos) <= 24:
        raise ValueError("informe de 1 a 24 departamentos")
    limpos, vistos = [], set()
    for d in deptos:
        if not isinstance(d, dict):
            raise ValueError("departamento inválido")
        nome = str(d.get("nome", "")).strip()
        if not 1 <= len(nome) <= 40 or nome.lower() in vistos:
            raise ValueError(f"nome de departamento inválido ou repetido: {nome!r}")
        cor = str(d.get("cor", "")).strip() or CORES[len(limpos) % len(CORES)]
        if not _COR.match(cor):
            raise ValueError(f"cor inválida em {nome}: use #rrggbb")
        caminhos = d.get("caminhos")
        if isinstance(caminhos, str):
            caminhos = re.split(r"[,\n;]", caminhos)
        if not isinstance(caminhos, list) or len(caminhos) > 60:
            raise ValueError(f"caminhos inválidos em {nome}")
        caminhos = [str(c).strip() for c in caminhos if str(c).strip()]
        if any(len(c) > 120 for c in caminhos):
            raise ValueError(f"caminho grande demais em {nome}")
        if any(str(c)[:3].lower() == "re:" and not _regex(str(c)[3:]) for c in caminhos):
            raise ValueError(f"expressão regular inválida em {nome}")
        item = {"nome": nome, "cor": cor.lower(), "caminhos": caminhos}
        anc = d.get("ancora")
        if anc is not None:
            if (not isinstance(anc, (list, tuple)) or len(anc) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= 3000 for v in anc)):
                raise ValueError(f"âncora inválida em {nome}: use [x, y] entre -3000 e 3000")
            item["ancora"] = [float(anc[0]), float(anc[1])]
        vistos.add(nome.lower())
        limpos.append(item)
    padrao = str(conf.get("padrao") or "Outros").strip()[:40] or "Outros"
    return {"modo": "regras", "deptos": limpos, "padrao": padrao}


def esquema_regras(conf):
    conf = validar(conf)
    nomes = [d["nome"] for d in conf["deptos"]]
    cores = [d["cor"] for d in conf["deptos"]]
    ancoras = [d.get("ancora") for d in conf["deptos"]]
    padrao = conf["padrao"]
    if padrao not in nomes:
        nomes.append(padrao)
        cores.append(COR_PADRAO)
        ancoras.append(None)

    def funcao(caminho):
        for d in conf["deptos"]:
            if any(casa_padrao(p, caminho) for p in d["caminhos"]):
                return d["nome"]
        return padrao

    return Esquema(nomes, cores, funcao, padrao, ancoras)


def esquema_pastas(arquivos, maximo=10):
    """Automático: uma cor por pasta de primeiro nível (as maiores), arquivos soltos na raiz em 'Raiz', o resto em 'Outros'."""
    def primeira(c):
        c = re.sub(r"^\./", "", (c or "").replace("\\", "/"))
        return c.split("/", 1)[0] if "/" in c else "Raiz"

    cont = Counter(primeira(f) for f in arquivos)
    top = [n for n, _ in cont.most_common(maximo)]
    nomes = list(top)
    if len(cont) > maximo:
        nomes.append("Outros")
    if not nomes:
        nomes = ["Raiz"]
    cores = [CORES[i % len(CORES)] for i in range(len(nomes))]
    conj = set(top)

    def funcao(caminho):
        p = primeira(caminho)
        return p if p in conj else ("Outros" if "Outros" in nomes else nomes[0])

    return Esquema(nomes, cores, funcao, "Outros" if "Outros" in nomes else nomes[0])
