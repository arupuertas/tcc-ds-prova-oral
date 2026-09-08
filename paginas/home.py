import streamlit as st

from simulador.ui.comum import cabecalho, ir

ETAPAS = [
    ("🎓", "Escolha o concurso", "Selecione entre as provas disponíveis e o simulador sorteia o grupo temático da sua banca."),
    ("🎥", "Teste câmera e microfone", "Uma sala de espera valida seu equipamento antes de a banca começar."),
    ("🎙️", "Responda em voz alta", "O avaliador faz as perguntas em voz e cada resposta sua é transcrita."),
    ("📋", "Receba sua nota", "Nota de 0 a 10 por pergunta, com justificativa e os pontos que faltaram."),
]


def render() -> None:
    cabecalho()
    st.markdown('<span class="spo-etiqueta">Preparação para prova oral</span>', unsafe_allow_html=True)
    st.markdown("# Treine sua prova oral como se fosse a banca de verdade")
    st.markdown(
        "Simule uma prova oral como se estivesse diante de uma banca real. Um avaliador conduz toda a "
        "arguição em voz, suas respostas são transcritas e avaliadas por uma banca de agentes com base no "
        "gabarito e no conteúdo do concurso. Ao final, você recebe sua nota e um feedback detalhado de cada "
        "resposta, com seus acertos e pontos de melhoria."
    )
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Iniciar simulação →", type="primary", use_container_width=True):
            ir("concursos")
    with c2:
        st.markdown('<p class="spo-muted" style="margin-top:.6rem">Sem cadastro · Precisa apenas de microfone (câmera opcional)</p>', unsafe_allow_html=True)

    st.markdown("## Como funciona")
    cols = st.columns(4)
    for i, (icone, titulo, texto) in enumerate(ETAPAS):
        with cols[i]:
            st.markdown(
                f'<div class="spo-card"><div style="font-size:1.6rem">{icone}</div>'
                f'<div class="spo-muted" style="text-transform:uppercase;letter-spacing:.15em;font-size:.7rem">Etapa {i + 1}</div>'
                f"<h4>{titulo}</h4><p class='spo-muted'>{texto}</p></div>",
                unsafe_allow_html=True,
            )
    st.markdown("---")
    st.markdown('<p class="spo-muted">Simulador de Prova Oral</p>', unsafe_allow_html=True)
