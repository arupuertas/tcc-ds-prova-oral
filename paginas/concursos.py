import streamlit as st

from simulador.simulacao import listar_concursos_publicos
from simulador.ui.comum import cabecalho, ir, link


def render() -> None:
    cabecalho()
    link("home", "← Voltar")
    st.markdown("# Qual prova oral você vai simular?")
    st.markdown(
        "Escolha o certame. Ao iniciar, o simulador sorteia um grupo temático e monta a sequência de "
        "perguntas de início, meio e fim da arguição."
    )
    try:
        concursos = listar_concursos_publicos()
    except Exception as e:  # noqa: BLE001
        st.error("Não foi possível carregar os concursos. Recarregue a página.")
        st.caption(str(e))
        return

    if not concursos:
        st.info("Ainda não há concursos disponíveis para simulação. Volte em breve.")
        return

    for c in concursos:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            with a:
                st.markdown(f"### {c['nome']}")
                if c.get("descricao"):
                    st.markdown(f'<p class="spo-muted">{c["descricao"]}</p>', unsafe_allow_html=True)
                st.caption("5 a 30 perguntas · você escolhe na sala de espera")
            with b:
                if st.button("Simular →", key=f"sim_{c['id']}", type="primary", use_container_width=True):
                    ir("sala", concurso_id=c["id"], concurso=c)
