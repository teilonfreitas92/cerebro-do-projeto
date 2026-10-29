"""Quem pode abrir um arquivo no Windows, lido direto do sistema (sem ler texto de comando).

Antes a conferência lia a saída do icacls, que muda com a língua do Windows ("BUILTIN\\Administradores") e vem numa
codificação antiga (OEM): com o Python em UTF-8 (PYTHONUTF8=1, como no GitHub Actions) a leitura quebrava. Aqui os
dados vêm pela API do Windows (advapi32) como SIDs ("S-1-5-21-..."), que são iguais em qualquer língua.
restringir() grava uma lista de acesso nova e protegida (sem herança) com UMA entrada só: acesso total para o usuário.
Isso também tira as entradas EXPLÍCITAS que um processo de administrador põe ao criar o arquivo (SYSTEM,
Administradores, OWNER RIGHTS), que o `icacls /inheritance:r` não tira. Quem chama é config._restringir_ao_dono.
"""
import ctypes
import os

# Tipos de entrada (ACE) que NEGAM acesso: não abrem o arquivo para ninguém, então não contam contra o "só do dono".
_NEGAM = (1, 6, 10, 12)        # ACCESS_DENIED, ..._OBJECT, ..._CALLBACK, ..._CALLBACK_OBJECT
_PERMITE = 0                   # ACCESS_ALLOWED_ACE_TYPE: o SID fica depois do cabeçalho (4 bytes) e da máscara (4 bytes)


def _dlls():
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    adv.GetLengthSid.argtypes = [ctypes.c_void_p]
    adv.GetLengthSid.restype = wintypes.DWORD
    adv.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    adv.AddAccessAllowedAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    adv.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    adv.SetNamedSecurityInfoW.restype = wintypes.DWORD
    return adv, k32


def restringir(caminho, sid):
    """Troca a lista de acesso do arquivo por uma protegida (não herda nada) com uma única entrada: acesso total para
    `sid`. Tudo o que havia antes (herdado ou explícito) sai. True se o Windows aceitou."""
    if os.name != "nt" or not str(sid).startswith("S-"):
        return False
    try:
        adv, k32 = _dlls()
        psid = ctypes.c_void_p()
        if not adv.ConvertStringSidToSidW(str(sid), ctypes.byref(psid)):
            return False
        try:
            # ACL (8 bytes) + ACCESS_ALLOWED_ACE sem o SidStart (8 bytes) + o SID, arredondado para múltiplo de 4
            tam = (8 + 8 + adv.GetLengthSid(psid) + 3) & ~3
            acl = ctypes.create_string_buffer(tam)
            if not adv.InitializeAcl(acl, tam, 2):                                   # 2 = ACL_REVISION
                return False
            if not adv.AddAccessAllowedAce(acl, 2, 0x001F01FF, psid):                # 0x1F01FF = FILE_ALL_ACCESS
                return False
            # 1 = SE_FILE_OBJECT; 4 = DACL_SECURITY_INFORMATION; 0x80000000 = PROTECTED_DACL (corta a herança)
            return adv.SetNamedSecurityInfoW(str(caminho), 1, 0x80000004, None, None, acl, None) == 0
        finally:
            k32.LocalFree(psid)
    except (OSError, AttributeError, ValueError):
        return False


def _sid_texto(adv, k32, psid):
    s = ctypes.c_void_p()
    if not adv.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        return ""
    try:
        return ctypes.wstring_at(s.value)
    finally:
        k32.LocalFree(s)


def sid_do_usuario():
    """SID do usuário que roda o Cérebro ('S-1-5-21-...'), lido do próprio processo. '' se não der (ou fora do Windows)."""
    if os.name != "nt":
        return ""
    from ctypes import wintypes
    try:
        adv, k32 = _dlls()
        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):     # 0x0008 = TOKEN_QUERY
            return ""
        try:
            n = wintypes.DWORD()
            adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(n))                         # 1 = TokenUser: pede o tamanho
            buf = ctypes.create_string_buffer(n.value or 256)
            if not adv.GetTokenInformation(tok, 1, buf, len(buf), ctypes.byref(n)):
                return ""
            return _sid_texto(adv, k32, ctypes.c_void_p.from_buffer(buf).value)              # TOKEN_USER começa pelo ponteiro do SID
        finally:
            k32.CloseHandle(tok)
    except (OSError, AttributeError, ValueError):
        return ""


def entradas(caminho):
    """Lista (tipo, SID) de cada entrada de acesso do arquivo. None se não deu para ler, ou se o arquivo não tem lista
    de acesso nenhuma (no Windows isso quer dizer "todo mundo entra")."""
    if os.name != "nt":
        return None

    class _Tamanho(ctypes.Structure):          # ACL_SIZE_INFORMATION
        _fields_ = [("AceCount", ctypes.c_uint32), ("AclBytesInUse", ctypes.c_uint32), ("AclBytesFree", ctypes.c_uint32)]
    try:
        adv, k32 = _dlls()
        dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
        # 1 = SE_FILE_OBJECT, 4 = DACL_SECURITY_INFORMATION
        if adv.GetNamedSecurityInfoW(str(caminho), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)) != 0:
            return None
        try:
            if not dacl.value:
                return None
            t = _Tamanho()
            if not adv.GetAclInformation(dacl, ctypes.byref(t), ctypes.sizeof(t), 2):        # 2 = AclSizeInformation
                return None
            lista = []
            for i in range(t.AceCount):
                ace = ctypes.c_void_p()
                if not adv.GetAce(dacl, i, ctypes.byref(ace)):
                    return None
                tipo = ctypes.c_ubyte.from_address(ace.value).value
                lista.append((tipo, _sid_texto(adv, k32, ace.value + 8) if tipo in (_PERMITE, *_NEGAM) else ""))
            return lista
        finally:
            k32.LocalFree(sd)
    except (OSError, AttributeError, ValueError):
        return None


def so_do_dono(caminho, sid=None):
    """True se TODA entrada que dá acesso ao arquivo é do usuário atual (e há pelo menos uma). Entradas que só negam
    acesso não contam. Qualquer entrada de outro tipo, de outro SID ou ilegível = False (na dúvida, não está protegido)."""
    sid = sid or sid_do_usuario()
    lista = entradas(caminho)
    if not sid or lista is None:
        return False
    dao = [s for tipo, s in lista if tipo not in _NEGAM]
    return bool(dao) and all(s == sid for s in dao)
