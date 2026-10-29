"""Mascaramento de segredos antes de qualquer texto de transcrição ir para a tela.

Os transcritos do Claude Code guardam o que o agente leu e imprimiu (inclusive .env, chaves e senhas), sem criptografia.
Tudo que o Cérebro mostra passa por mascarar(). A lista é conservadora: prefere esconder demais a vazar.
"""
import re

OCULTO = "[segredo oculto]"

# Padrões que são o segredo inteiro
_INTEIROS = [
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE|PGP[A-Z ]*BLOCK)-----.*?(?:-----END [A-Z ]*-----|\Z)", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                                              # chave temporária da AWS
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_\-]{20,}"),                                       # token OAuth do Google
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
    re.compile(r"\b(?:rk|sk)_(?:live|test)_[A-Za-z0-9]{10,}"),                        # Stripe (secreta e restrita)
    re.compile(r"\bwhsec_[A-Za-z0-9+/=_\-]{16,}"),                                    # segredo de webhook do Stripe
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),                    # SendGrid
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),                                   # bot do Telegram
    re.compile(r"\b[MNO][A-Za-z0-9_\-]{21,25}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,38}\b"),   # bot do Discord
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),   # JWT
]
# Esquema + valor: guarda o esquema
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/\-]{12,}=*")
# Cabeçalho inteiro (Authorization: ..., Cookie: ...)
_CABECALHO = re.compile(r"(?im)^(\s*(?:authorization|cookie|set-cookie|x-api-key|proxy-authorization)\s*:\s*).+$")

_CHAVES = (r"(?:password|passwd|pwd|senha|secret|segredo|token(?!s)|api[_-]?key|apikey|access[_-]?key|private[_-]?key"
           r"|client[_-]?secret|chave)")
# "senha": "valor"   (JSON)
_JSON = re.compile(r'(?i)("[A-Za-z0-9_\-]*' + _CHAVES + r'[A-Za-z0-9_\-]*"\s*:\s*)"(?:[^"\\]|\\.)*"')
# senha = valor   /   SENHA=valor   /   TELEGRAM_TOKEN=valor  (a chave pode ter prefixo/sufixo e aspas: {'password': 'x'} do Python)
_ATRIB = re.compile(r"(?i)(\b[A-Za-z0-9_\-]*" + _CHAVES + r"[A-Za-z0-9_\-]*['\"]?\s*[=:]\s*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;]{4,})")
# senha curta (1 a 3 caracteres): só para chaves que são senha mesmo (token/chave curtos seriam números comuns)
_CURTA = re.compile(r"(?i)(\b[A-Za-z0-9_\-]*(?:password|passwd|pwd|senha)[A-Za-z0-9_\-]*['\"]?\s*[=:]\s*)[^\s\"',;]{1,3}(?=[\s\"',;]|$)")
# linha de comando: --password x, --passwd x, --pass x, --pwd x
_OPCAO = re.compile(r"(?i)(--(?:password|passwd|pass|pwd)[ \t]+)(?!-)(?:\"[^\"\n]*\"|'[^'\n]*'|\S+)")
# -p x só nos programas em que -p é a senha (nunca em outros comandos): sshpass, mysql, mysqldump, mariadb, psql
_P_CURTO = re.compile(r"(?i)\b(sshpass|mysql|mysqldump|mariadb|psql)\b([^\n|;&]*?[ \t])(-p[ \t]*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\-]\S*)")
# URL com usuário:senha@host
_URL = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
# frase: "my password is x", "minha senha é x"
_FRASE = re.compile(r"(?i)\b((?:password|passwd|senha)\s+(?:is|was|é|eh|era)\s+)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;]+)")


def mascarar(texto):
    """Devolve o texto com segredos trocados por [segredo oculto]. Aceita None e valores que não são texto."""
    if texto is None:
        return ""
    if not isinstance(texto, str):
        texto = str(texto)
    if not texto:
        return texto
    for p in _INTEIROS:
        texto = p.sub(OCULTO, texto)
    texto = _CABECALHO.sub(lambda m: m.group(1) + OCULTO, texto)
    texto = _BEARER.sub(lambda m: m.group(1) + " " + OCULTO, texto)
    texto = _JSON.sub(lambda m: m.group(1) + '"' + OCULTO + '"', texto)
    texto = _ATRIB.sub(lambda m: m.group(1) + OCULTO, texto)
    texto = _CURTA.sub(lambda m: m.group(1) + OCULTO, texto)
    texto = _OPCAO.sub(lambda m: m.group(1) + OCULTO, texto)
    texto = _P_CURTO.sub(lambda m: m.group(1) + m.group(2) + m.group(3) + OCULTO, texto)
    texto = _URL.sub(lambda m: m.group(1) + OCULTO + "@", texto)
    texto = _FRASE.sub(lambda m: m.group(1) + OCULTO, texto)
    return texto


def encurtar(texto, limite=300):
    """Máscara primeiro, depois corta em 'limite' caracteres (assim o corte nunca expõe um pedaço de segredo)."""
    t = mascarar(texto)
    if len(t) > limite:
        t = t[:limite].rstrip() + "…"
    return t
