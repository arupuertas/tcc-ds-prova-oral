"""Utilidades compartilhadas pelas páginas: navegação, cabeçalho, estado e assets."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parents[2]
ASSETS = RAIZ / "assets"


@lru_cache(maxsize=32)
def asset_bytes(nome: str) -> bytes:
    return (ASSETS / nome).read_bytes()


@lru_cache(maxsize=32)
def asset_data_url(nome: str, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(asset_bytes(nome)).decode()}"


# ---------- navegação ----------


def rotas() -> dict:
    return st.session_state.get("_rotas", {})


def ir(nome: str, **estado) -> None:
    """Troca de página programaticamente, guardando estado em `st.session_state`."""
    for k, v in estado.items():
        st.session_state[k] = v
    pagina = rotas().get(nome)
    if pagina is None:
        st.error(f"Página desconhecida: {nome}")
        st.stop()
    st.switch_page(pagina)


def link(nome: str, rotulo: str, icone: str | None = None) -> None:
    pagina = rotas().get(nome)
    if pagina is not None:
        st.page_link(pagina, label=rotulo, icon=icone)


def cabecalho() -> None:
    esq, dir_ = st.columns([6, 1])
    with esq:
        st.markdown(
            f'<div class="spo-marca"><img src="{asset_data_url("marca.png", "image/png")}" alt="Simulador de Prova Oral" />'
            "<span>Simulador de Prova Oral</span></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        if st.session_state.get("admin_user_id"):
            link("admin", "Painel", "🛠️")
        else:
            link("auth", "Admin", "🔐")
    st.markdown("---")


ESTILO = """
<style>
.spo-marca { display:flex; align-items:center; gap:.6rem; }
.spo-marca img { height: 34px; }
.spo-marca span { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.03em; }
.spo-etiqueta { display:inline-block; padding:.2rem .7rem; border-radius:999px; background:#fbe9de; color:#9a3f0e; font-size:.75rem; font-weight:600; }
.spo-card { border:1px solid #ece6df; border-radius:14px; padding:1.1rem 1.2rem; background:#fff; margin-bottom:.8rem; }
.spo-card h4 { margin:.2rem 0 .3rem; }
.spo-muted { color:#6b6b76; font-size:.9rem; }
.spo-nota { font-size:3rem; color:#d9581f; font-weight:700; line-height:1; }
.spo-badge { display:inline-block; padding:.15rem .5rem; border-radius:6px; background:#fbe9de; color:#9a3f0e; font-size:.8rem; font-weight:600; }
.spo-badge-cinza { background:#efece8; color:#444; }
.spo-badge-vermelho { background:#fde3e3; color:#9b1c1c; }
.spo-pergunta { font-size:1.15rem; line-height:1.5; }
.spo-kicker { text-transform:uppercase; letter-spacing:.18em; font-size:.7rem; color:#d9581f; }
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(ESTILO, unsafe_allow_html=True)


# ---------- contexto ----------


def ip_cliente() -> str | None:
    try:
        return st.context.ip_address
    except Exception:  # noqa: BLE001
        return None


def parametro(nome: str) -> str | None:
    try:
        v = st.query_params.get(nome)
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, str) and v else None


def fixar_parametro(nome: str, valor: str) -> None:
    try:
        if st.query_params.get(nome) != valor:
            st.query_params[nome] = valor
    except Exception:  # noqa: BLE001
        pass


def limpar_parametros() -> None:
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass


def card(html: str) -> None:
    st.markdown(f'<div class="spo-card">{html}</div>', unsafe_allow_html=True)


def fmt_nota(n: float | None, casas: int = 1) -> str:
    return "—" if n is None else f"{n:.{casas}f}".replace(".", ",")
