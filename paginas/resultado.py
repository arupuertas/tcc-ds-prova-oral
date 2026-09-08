import pandas as pd
import streamlit as st

from simulador.banca import nome_agente
from simulador.simulacao import obter_resultado
from simulador.ui.comum import cabecalho, fixar_parametro, fmt_nota, link, parametro


def _ata(ata: dict) -> None:
    with st.expander(f"⚖️ Ata da banca · divergência {fmt_nota(ata.get('divergencia', 0))}"):
        cols = st.columns(2)
        for i, p in enumerate(ata.get("avaliadores", [])):
            with cols[i % 2]:
                st.markdown(
                    f"**{p.get('nome')}** <span class='spo-badge'>{fmt_nota(p.get('nota'))}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f'<p class="spo-muted">{p.get("parecer", "")}</p>', unsafe_allow_html=True)
                if p.get("alertas"):
                    st.markdown(f"<p style='color:#9b1c1c;font-size:.85rem'>Alertas: {'; '.join(p['alertas'])}</p>", unsafe_allow_html=True)
        delib = ata.get("deliberacao", [])
        if delib:
            st.markdown("**Deliberação**")
            for e in delib:
                if e.get("tipo") == "pergunta":
                    st.markdown(f"- **Juiz → {nome_agente(e.get('para', ''))}:** {e.get('texto', '')}")
                else:
                    rev = f" _(nota revisada: {fmt_nota(e['notaRevisada'])})_" if e.get("notaRevisada") is not None else ""
                    st.markdown(f"- **{nome_agente(e.get('de', ''))}:** {e.get('texto', '')}{rev}")
        juiz = ata.get("juiz", {})
        st.caption(
            f"Nota final do juiz: {fmt_nota(juiz.get('nota'))}"
            + ("" if delib else " · sem divergência relevante, decidiu sem esclarecimentos")
        )


def render() -> None:
    cabecalho()
    sessao_id = st.session_state.get("sessao_id") or parametro("sessao")
    if not sessao_id:
        st.warning("Nenhuma simulação selecionada.")
        link("concursos", "Fazer uma simulação", "🎓")
        return
    fixar_parametro("sessao", sessao_id)

    try:
        estado, respostas = obter_resultado(sessao_id)
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível carregar esta simulação. {e}")
        return

    st.markdown(f'<p class="spo-kicker">{estado.concurso_nome}</p>', unsafe_allow_html=True)
    st.markdown("# Resultado da sua prova oral")

    with st.container(border=True):
        st.markdown('<p class="spo-muted">Nota final</p>', unsafe_allow_html=True)
        st.markdown(f'<div class="spo-nota">{fmt_nota(estado.nota_final, 2)} <span style="font-size:1rem;color:#888">/ 10</span></div>', unsafe_allow_html=True)
        if estado.resumo:
            st.markdown(estado.resumo)

    if estado.postura_resumo:
        st.info(f"👁️ **Postura e confiança** — {estado.postura_resumo}\n\n"
                "Leitura feita a partir das fotos da sua câmera durante as respostas (expressão, olhar e postura).")

    with st.container(border=True):
        st.markdown("#### 💬 Vícios de linguagem")
        vicios = estado.vicios[:8]
        if not vicios:
            st.markdown("Nenhum vício de linguagem recorrente foi identificado na sua fala. Excelente sinal.")
        else:
            if estado.vicios_resumo:
                st.markdown(estado.vicios_resumo)
            df = pd.DataFrame(vicios).set_index("termo")
            st.bar_chart(df, horizontal=True, color="#d9581f")

    st.markdown("## Respostas avaliadas")
    for r in respostas:
        with st.container(border=True):
            a, b = st.columns([6, 1])
            with a:
                st.markdown(f"### {r['ordem']}. {r['pergunta']}")
            with b:
                st.markdown(f"<span class='spo-badge' style='font-size:1rem'>{fmt_nota(r['nota'])}</span>", unsafe_allow_html=True)
            st.markdown('<p class="spo-kicker">Sua resposta</p>', unsafe_allow_html=True)
            st.markdown(f'<p class="spo-muted">{r["transcricao"]}</p>', unsafe_allow_html=True)
            if r["vicios"]:
                st.markdown(" ".join(f"<span class='spo-badge spo-badge-cinza'>{v['termo']} × {v['total']}</span>" for v in r["vicios"]), unsafe_allow_html=True)
            if r["justificativa"]:
                st.markdown('<p class="spo-kicker">Avaliação da banca</p>', unsafe_allow_html=True)
                st.markdown(r["justificativa"])
            if r["ata"]:
                _ata(r["ata"])
            if r["pontos_cobertos"] or r["pontos_faltantes"]:
                for p in r["pontos_cobertos"]:
                    st.markdown(f"✅ {p}")
                for p in r["pontos_faltantes"]:
                    st.markdown(f"❌ {p}")
            if r["nervosismo"] is not None or r["confianca"] is not None or r["postura_observacao"]:
                chips = []
                if r["nervosismo"] is not None:
                    chips.append(f"Nervosismo: {r['nervosismo']}/10")
                if r["confianca"] is not None:
                    chips.append(f"Confiança: {r['confianca']}/10")
                if r["lendo"] is not None:
                    chips.append("Indícios de leitura" if r["lendo"] else "Sem indícios de leitura")
                st.markdown("**Postura na câmera** · " + " · ".join(chips))
                if r["postura_observacao"]:
                    st.caption(r["postura_observacao"])

    c1, c2 = st.columns(2)
    with c1:
        link("concursos", "Fazer outra simulação", "🔁")
    with c2:
        link("home", "Voltar ao início", "🏠")
