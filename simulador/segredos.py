"""Chaves de API cadastradas pelo painel.

Ficam na coleção `segredos` do Chroma, cifradas com AES-256-GCM. A chave de cifra deriva de um
segredo do servidor (`CHAVES_CRIPTO_SECRET`). O formato `v1:<iv>:<dados>` é o mesmo da versão
anterior do app.

Precedência: valor cadastrado no painel > segredo/variável de ambiente do servidor.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .chaves import ChaveId
from .config import segredo_ambiente
from .db import T, agora_iso

TTL_S = 60
_cache: dict[str, tuple[str | None, float]] = {}


@lru_cache(maxsize=1)
def _chave_cripto() -> bytes:
    segredo = segredo_ambiente("CHAVES_CRIPTO_SECRET") or segredo_ambiente("ADMIN_SENHA")
    if not segredo:
        raise RuntimeError("Defina CHAVES_CRIPTO_SECRET nos secrets para cifrar as chaves de API.")
    return hashlib.sha256(f"simulador:chaves:{segredo}".encode()).digest()


def cifrar(texto: str) -> str:
    iv = os.urandom(12)
    dados = AESGCM(_chave_cripto()).encrypt(iv, texto.encode(), None)
    return f"v1:{base64.b64encode(iv).decode()}:{base64.b64encode(dados).decode()}"


def decifrar(valor: str) -> str:
    partes = valor.split(":")
    if len(partes) != 3 or partes[0] != "v1":
        raise ValueError("Formato de segredo desconhecido.")
    iv, dados = base64.b64decode(partes[1]), base64.b64decode(partes[2])
    return AESGCM(_chave_cripto()).decrypt(iv, dados, None).decode()


def _ler_do_painel(id: ChaveId) -> str | None:
    agora = time.time()
    em_cache = _cache.get(id)
    if em_cache and agora - em_cache[1] < TTL_S:
        return em_cache[0]
    valor: str | None = None
    try:
        registro = T("segredos").obter(id)
        if registro and registro.get("valor_cifrado"):
            valor = decifrar(registro["valor_cifrado"])
    except Exception as e:  # banco indisponível ou cifra inválida: cai na variável de ambiente
        print(f"[segredos] falha ao ler {id}: {e}")
    _cache[id] = (valor, agora)
    return valor


def obter_segredo(id: ChaveId) -> str | None:
    """Valor efetivo da chave: painel primeiro, ambiente depois."""
    return _ler_do_painel(id) or segredo_ambiente(id)


@dataclass
class FonteSegredo:
    id: str
    configurada: bool
    fonte: str | None  # "painel" | "servidor" | None
    sufixo: str | None


def fonte_segredo(id: ChaveId) -> FonteSegredo:
    painel = _ler_do_painel(id)
    ambiente = segredo_ambiente(id)
    valor = painel or ambiente
    return FonteSegredo(
        id=id,
        configurada=bool(valor),
        fonte="painel" if painel else ("servidor" if ambiente else None),
        sufixo=valor[-4:] if valor else None,
    )


def salvar_segredo(id: ChaveId, valor: str) -> FonteSegredo:
    T("segredos").salvar({"id": id, "valor_cifrado": cifrar(valor.strip()), "atualizado_em": agora_iso()})
    _cache.pop(id, None)
    return fonte_segredo(id)


def remover_segredo(id: ChaveId) -> FonteSegredo:
    T("segredos").remover(id)
    _cache.pop(id, None)
    return fonte_segredo(id)


def _ping(url: str, headers: dict[str, str]) -> tuple[bool, str]:
    try:
        r = httpx.get(url, headers=headers, timeout=15)
        if r.is_success:
            return True, "Chave válida."
        corpo = r.text[:200]
        if r.status_code in (401, 403):
            return False, f"Chave recusada ({r.status_code})."
        return False, f"O provedor respondeu {r.status_code}{': ' + corpo if corpo else '.'}"
    except Exception as e:
        return False, str(e) or "Falha de rede."


def testar_chave(id: ChaveId) -> tuple[bool, str]:
    """Faz uma chamada barata ao provedor para confirmar que a chave funciona."""
    valor = obter_segredo(id)
    if not valor:
        return False, "Chave não configurada."
    if id == "OPENAI_API_KEY":
        return _ping("https://api.openai.com/v1/models", {"Authorization": f"Bearer {valor}"})
    if id == "ANTHROPIC_API_KEY":
        return _ping("https://api.anthropic.com/v1/models", {"x-api-key": valor, "anthropic-version": "2023-06-01"})
    if id == "GOOGLE_GENERATIVE_AI_API_KEY":
        return _ping(f"https://generativelanguage.googleapis.com/v1beta/models?key={valor}", {})
    return False, "Esta chave não tem teste automático."
