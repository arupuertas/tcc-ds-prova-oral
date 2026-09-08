import streamlit as st

from simulador.auth import entrar
from simulador.ui.comum import cabecalho, ir, link


def render() -> None:
    cabecalho()
    if st.session_state.get("admin_user_id"):
        ir("admin")

    _, meio, _ = st.columns([1, 1.2, 1])
    with meio:
        st.markdown("# Acesso administrativo")
        st.markdown('<p class="spo-muted">Área restrita para gestão de concursos, perguntas e base de conhecimento.</p>', unsafe_allow_html=True)
        with st.form("login"):
            usuario = st.text_input("Usuário", autocomplete="username")
            senha = st.text_input("Senha", type="password", autocomplete="current-password")
            ok = st.form_submit_button("Entrar", type="primary", use_container_width=True)
        if ok:
            try:
                user_id = entrar(usuario, senha)
            except ValueError as e:
                st.error(str(e))
            except Exception as e:  # noqa: BLE001
                st.error(f"Falha ao autenticar: {e}")
            else:
                ir("admin", admin_user_id=user_id)
        link("home", "Voltar ao simulador")
