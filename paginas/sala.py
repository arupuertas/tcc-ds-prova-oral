import streamlit as st

from simulador.config_app import obter_config_avaliador, videos_prontos
from simulador.limites import CapacidadeError
from simulador.quantidades import QUANTIDADES_PERGUNTAS, quantidade_padrao
from simulador.simulacao import iniciar_simulacao, listar_concursos_publicos
from simulador.ui.avatar import render_avatar
from simulador.ui.comum import cabecalho, ip_cliente, ir, link
from simulador.ui.formatos import FORMATOS


def _limpar_estado_prova() -> None:
    for k in list(st.session_state.keys()):
        if k.startswith("prova_"):
            del st.session_state[k]


def render() -> None:
    cabecalho()
    concurso_id = st.session_state.get("concurso_id")
    if not concurso_id:
        st.warning("Escolha um concurso para começar.")
        link("concursos", "Ir para a lista de concursos", "🎓")
        return

    concurso = st.session_state.get("concurso")
    if not concurso or concurso.get("id") != concurso_id:
        try:
            concurso = next((c for c in listar_concursos_publicos() if c["id"] == concurso_id), None)
        except Exception as e:  # noqa: BLE001
            st.error(f"Não foi possível carregar o concurso: {e}")
            link("concursos", "Voltar aos concursos")
            return
        st.session_state["concurso"] = concurso
    if not concurso:
        st.error("Concurso não encontrado ou inativo.")
        link("concursos", "Trocar concurso")
        return

    try:
        config = obter_config_avaliador()
    except Exception:  # noqa: BLE001
        config = None
    videos = config.videos if config else None
    formatos = [f for f in FORMATOS if f.id != "video" or videos_prontos(videos)]

    link("concursos", "← Trocar concurso")
    st.markdown("# Sala de espera")
    st.markdown(f'<p class="spo-kicker">{concurso["nome"]}</p>', unsafe_allow_html=True)
    st.markdown(
        "Grave um teste curto para validar o microfone, informe como o avaliador deve chamá-lo e escolha o "
        "formato da banca. Quando estiver tudo certo, clique em **Iniciar teste**."
    )

    esq, dir_ = st.columns([1.4, 1])
    with esq:
        st.markdown("#### Prévia do avaliador")
        formato = st.session_state.get("sala_formato", "foto")
        render_avatar(formato, None, videos=videos)
        st.markdown("#### Sua câmera (opcional)")
        st.caption(
            "Se você tirar uma foto aqui e durante as respostas, a banca também avalia postura, "
            "olhar e sinais de leitura. Sem foto, a prova segue normalmente."
        )
        st.camera_input("Teste da câmera", key="sala_camera", label_visibility="collapsed")

    with dir_:
        with st.container(border=True):
            st.markdown("**Microfone**")
            st.caption("Use o Chrome ou o Edge: em outros navegadores a gravação pode falhar com o aviso \"An error has occurred\".")
            teste = st.audio_input("Fale algo e pare a gravação para testar", key="sala_mic")
            audio_ok = teste is not None and len(teste.getvalue()) > 1000
            st.markdown("✅ Microfone funcionando" if audio_ok else "⚪ Grave um teste para validar o microfone")

            nome = st.text_input("Como o avaliador deve chamá-lo?", placeholder="Seu nome", key="sala_nome")

            quantidade = st.radio(
                "Quantas perguntas você quer responder?",
                QUANTIDADES_PERGUNTAS,
                index=QUANTIDADES_PERGUNTAS.index(quantidade_padrao(concurso.get("quantidade_perguntas"))),
                horizontal=True,
                key="sala_quantidade",
            )
            st.caption(
                "A banca segue a ordem real da arguição: início, meio e fim. Se o grupo sorteado tiver "
                "menos perguntas, a prova usa as disponíveis."
            )

            st.radio(
                "Formato do avaliador",
                [f.id for f in formatos],
                format_func=lambda fid: next(f.nome for f in formatos if f.id == fid),
                captions=[f.descricao for f in formatos],
                key="sala_formato",
            )

            pronto = audio_ok and len(nome.strip()) >= 2
            if st.button("Iniciar teste", type="primary", disabled=not pronto, use_container_width=True):
                with st.spinner("Convocando a banca…"):
                    try:
                        sessao_id = iniciar_simulacao(concurso_id, nome.strip(), int(quantidade), ip_cliente())
                    except CapacidadeError as e:
                        st.error(str(e))
                        return
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Não foi possível iniciar a simulação: {e}")
                        return
                _limpar_estado_prova()
                ir(
                    "prova",
                    sessao_id=sessao_id,
                    candidato_nome=nome.strip(),
                    formato_avaliador=st.session_state.get("sala_formato", "foto"),
                )
