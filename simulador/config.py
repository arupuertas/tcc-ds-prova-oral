"""Leitura de configuração: `st.secrets` (Streamlit Cloud) com fallback em variáveis de ambiente."""

from __future__ import annotations

import os


def _do_streamlit(nome: str) -> str | None:
    try:
        import streamlit as st  # import tardio: o núcleo não depende do Streamlit

        if nome in st.secrets:
            valor = st.secrets[nome]
            return str(valor) if valor is not None else None
    except Exception:
        return None
    return None


def segredo_ambiente(nome: str, padrao: str | None = None) -> str | None:
    """Valor de configuração do servidor (nunca exposto ao candidato)."""
    valor = _do_streamlit(nome)
    if valor:
        return valor
    valor = os.environ.get(nome)
    return valor if valor else padrao


def exigir(nome: str) -> str:
    valor = segredo_ambiente(nome)
    if not valor:
        raise RuntimeError(
            f"Configuração ausente: {nome}. Defina em .streamlit/secrets.toml (local) "
            "ou nos Secrets do app no Streamlit Community Cloud."
        )
    return valor


def inteiro_ambiente(nome: str, padrao: int) -> int:
    bruto = segredo_ambiente(nome)
    try:
        n = int(float(bruto)) if bruto else padrao
    except ValueError:
        return padrao
    return n if n > 0 else padrao
