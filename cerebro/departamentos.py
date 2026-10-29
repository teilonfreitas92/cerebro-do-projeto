"""Departamentos do mapa por projeto: leitura e validação da configuração (a lógica fica em mapa/deptos.py, usada também pelo gerar.py)."""
import importlib.util
from pathlib import Path

from . import config

_spec = importlib.util.spec_from_file_location("cerebro_mapa_deptos", Path(__file__).resolve().parent.parent / "mapa" / "deptos.py")
deptos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deptos)


def validar(conf):
    return deptos.validar(conf)


def do_projeto(cfg, slug):
    """Configuração atual: {'modo': 'regras'|'pastas', ...}. Sem entrada: uma cor por pasta de primeiro nível."""
    conf = (cfg.get("departamentos") or {}).get(slug)
    if conf is None:
        return {"modo": "pastas"}
    return conf


def salvar(slug, conf):
    """conf None = voltar ao automático (pastas)."""
    limpa = validar(conf) if conf is not None else None

    def mudar(cfg):
        d = cfg.setdefault("departamentos", {})
        if limpa is None:
            d.pop(slug, None)
        else:
            d[slug] = limpa

    config.atualizar_config(mudar)
    return limpa
