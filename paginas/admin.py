"""Painel administrativo."""

from __future__ import annotations

import json
from io import BytesIO

import streamlit as st

from simulador import admin as adm
from simulador.agentes import previa_dos_prompts, status_provedores
from simulador.auth import sou_admin
from simulador.banca import AVALIADORES, JUIZ_NOME, LIMIAR_DIVERGENCIA, MAX_ESCLARECIMENTOS
from simulador.banco_questoes import TAMANHO_LOTE_IMPORTACAO, converter_banco_questoes
from simulador.catalogo import CATALOGO
from simulador.catalogo import por_id as catalogo_por_id
from simulador.chaves import CHAVES
from simulador.config_app import (
    LIMITES_FAIXA,
    ConfigAvaliador,
    ConfigBanca,
    ConfigLimites,
    ConfigPrompts,
    limites_padrao,
    obter_config_avaliador,
    obter_config_banca,
    obter_config_limites,
    obter_config_prompts,
    salvar_config_avaliador,
    salvar_config_banca,
    salvar_config_limites,
    salvar_config_prompts,
    redefinir_prompts,
)
from simulador.custos import PROVEDORES, formatar_duracao, formatar_usd
from simulador.db import onde_esta_o_banco
from simulador.ia import IntegracaoError, sintetizar_voz
from simulador.limites import sessoes_em_andamento
from simulador.modelos import MODELOS, PROVEDORES_LLM, buscar_modelo, nome_modelo, separar_modelo
from simulador.segredos import fonte_segredo, remover_segredo, salvar_segredo, testar_chave
from simulador.ui.comum import ASSETS, cabecalho, fmt_nota, ir, link
from simulador.ui.formatos import FRASE_TESTE, VOZES

S = st.session_state


def _data(iso: str) -> str:
    return iso.replace("T", " ")[:16] if iso else "—"


def _erro(e: Exception) -> None:
    st.error(str(e) or "Falha inesperada.")


# ---------- abas ----------


def _estatisticas() -> None:
    try:
        d = adm.estatisticas()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    c = st.columns(4)
    c[0].metric("Simulações iniciadas", d["total_simulacoes"])
    c[1].metric("Simulações concluídas", d["total_finalizadas"])
    c[2].metric("Nota média", fmt_nota(d["media_geral"], 2))
    c[3].metric("Perguntas cadastradas", d["total_perguntas"])
    st.markdown("### Por concurso")
    if not d["por_concurso"]:
        st.caption("Nenhuma simulação registrada ainda.")
    for item in d["por_concurso"]:
        st.markdown(f"- **{item['nome']}** — {item['qtd']} simulações")
    if d["por_grupo"]:
        st.markdown("### Nota média por grupo")
        st.dataframe(d["por_grupo"], hide_index=True, use_container_width=True)


def _limites() -> None:
    try:
        config = obter_config_limites()
        padrao = limites_padrao()
        em_andamento = sessoes_em_andamento()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    with st.form("limites"):
        st.markdown("### Limites de capacidade")
        st.caption(f"Valem na próxima prova iniciada, sem deploy. Agora há **{em_andamento}** em andamento (limite {config.max_sessoes}).")
        campos = [
            ("max_sessoes", "Provas simultâneas no app", "Acima disso, o candidato vê “Todas as bancas estão ocupadas”."),
            ("max_sessoes_por_ip", "Provas simultâneas por rede (IP)", "Cursinhos e escritórios compartilham um IP: deixe folga."),
            ("max_inicios_por_hora", "Inícios por hora por rede (IP)", "Freio contra abuso; não conta provas concluídas."),
            ("minutos_sem_sinal", "Minutos sem sinal até abandonar", "Aba fechada ou rede caída: a vaga é liberada após esse tempo."),
        ]
        cols = st.columns(4)
        valores = {}
        for i, (campo, rotulo, ajuda) in enumerate(campos):
            mn, mx = LIMITES_FAIXA[campo]
            with cols[i]:
                valores[campo] = st.number_input(rotulo, min_value=mn, max_value=mx, value=getattr(config, campo), help=f"{ajuda} Padrão: {getattr(padrao, campo)}.")
        if st.form_submit_button("Salvar limites"):
            try:
                salvar_config_limites(ConfigLimites(**{k: int(v) for k, v in valores.items()}))
                st.success("Limites atualizados.")
            except Exception as e:  # noqa: BLE001
                _erro(e)


def _sessoes() -> None:
    _limites()
    try:
        d = adm.metricas_uso()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    c = st.columns(4)
    c[0].metric("Pessoas que usaram", d["total_candidatos"] or d["total_sessoes"])
    c[1].metric("Simulações iniciadas", d["total_sessoes"])
    c[2].metric("Tempo médio", formatar_duracao(d["media_duracao"]))
    c[3].metric("Nota média", fmt_nota(d["media_nota"], 2))
    st.markdown("### Registro de sessões")
    if not d["sessoes"]:
        st.caption("Nenhuma simulação registrada ainda.")
    for s in d["sessoes"]:
        titulo = (
            f"{s['candidato'] or 'Candidato não informado'} · {s['concurso']} · Grupo {s['grupo']} · "
            f"{formatar_duracao(s['duracao'])} · {_data(s['criada_em'])} · "
            f"{fmt_nota(s['nota'], 2) if s['nota'] is not None else s['status'].replace('_', ' ')}"
        )
        with st.expander(titulo):
            try:
                det = adm.detalhe_sessao(s["id"])
            except Exception as e:  # noqa: BLE001
                _erro(e)
                continue
            st.caption(f"Duração: {formatar_duracao(det['duracao'])} · Nota final: {fmt_nota(det['nota'], 2)} · Custo de APIs: {formatar_usd(det['custo'])}")
            for r in det["respostas"]:
                st.markdown(f"**{r['ordem']}. {r['pergunta']}** — nota {fmt_nota(r['nota'])}")
                st.markdown(f'<p class="spo-muted">Resposta: {r["transcricao"]}</p>', unsafe_allow_html=True)
                if r["justificativa"]:
                    st.markdown(r["justificativa"])
                st.caption(f"Pontos cobertos: {'; '.join(r['pontos_cobertos']) or '—'} · Pontos faltantes: {'; '.join(r['pontos_faltantes']) or '—'}")


def _unidade(unidade: str, quantidade: float) -> str:
    if unidade == "segundos":
        return formatar_duracao(quantidade)
    if unidade == "tokens":
        return f"{int(round(quantidade)):,} tokens".replace(",", ".")
    if unidade == "caracteres":
        return f"{int(round(quantidade)):,} caracteres".replace(",", ".")
    return f"{int(round(quantidade)):,} requisições".replace(",", ".")


def _custos() -> None:
    try:
        d = adm.metricas_uso()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    c = st.columns(3)
    c[0].metric("Custo total", formatar_usd(d["custo_total"]))
    c[1].metric("Custo hoje", formatar_usd(d["custo_hoje"]))
    c[2].metric("Custo por simulação", formatar_usd(d["custo_por_sessao"]))
    if not d["provedores"]:
        st.caption("Nenhum consumo de API registrado ainda. Os valores aparecem após a primeira simulação.")
    for p in d["provedores"]:
        info = PROVEDORES.get(p["provedor"], {})
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.markdown(f"### {info.get('nome', p['provedor'])}")
            if info.get("descricao"):
                a.caption(info["descricao"])
            b.markdown(f"<p class='spo-nota' style='font-size:1.4rem'>{formatar_usd(p['custo'])}</p>", unsafe_allow_html=True)
            st.dataframe(
                [
                    {
                        "operação": o["operacao"].replace("_", " "),
                        "modelo": o["modelo"] or "—",
                        "quantidade": _unidade(o["unidade"], o["quantidade"]),
                        "chamadas": o["chamadas"],
                        "custo": formatar_usd(o["custo"]),
                    }
                    for o in p["operacoes"]
                ],
                hide_index=True,
                use_container_width=True,
            )


def _avaliador() -> None:
    try:
        config = obter_config_avaliador()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    st.caption("Escolha a voz da banca e, opcionalmente, os clipes do formato “Juiz em vídeo”.")

    st.markdown("### Voz do avaliador")
    voz_atual = S.get("adm_voz", config.voz)
    cols = st.columns(3)
    for i, v in enumerate(VOZES):
        with cols[i % 3]:
            with st.container(border=True):
                a, b = st.columns([1, 2.2])
                a.image(str(ASSETS / v.foto), width=64)
                b.markdown(f"**{v.nome}**  \n<span class='spo-muted'>{v.descricao}</span>", unsafe_allow_html=True)
                x, y = st.columns(2)
                if x.button("Usar" if voz_atual != v.id else "✓ Selecionada", key=f"voz_{v.id}", disabled=voz_atual == v.id, use_container_width=True):
                    S["adm_voz"] = v.id
                    st.rerun()
                if y.button("🔊 Ouvir", key=f"ouvir_{v.id}", use_container_width=True):
                    try:
                        with st.spinner("Gerando voz de teste…"):
                            mp3 = sintetizar_voz(FRASE_TESTE, v.id)
                        st.audio(mp3, format="audio/mpeg", autoplay=True)
                    except IntegracaoError as e:
                        st.error(str(e))

    st.markdown("### Juiz em vídeo (clipes reais)")
    st.caption(
        "Clipes curtos em loop (8–15 s, 16:9, MP4 H.264, sem áudio) hospedados como arquivo: o juiz "
        "**ouvindo** (olhando para a câmera) e **falando** (boca em movimento sutil). Com os dois preenchidos, "
        "o formato aparece para o candidato na sala de espera."
    )
    with st.form("avaliador"):
        ouvindo = st.text_input("Clipe: ouvindo (obrigatório)", value=config.videos.get("ouvindo", ""), placeholder="https://.../juiz-ouvindo.mp4")
        falando = st.text_input("Clipe: falando (obrigatório)", value=config.videos.get("falando", ""))
        pensando = st.text_input("Clipe: pensando (opcional — usa o de escuta se vazio)", value=config.videos.get("pensando", ""))
        if st.form_submit_button("Salvar avaliador", type="primary"):
            try:
                salvar_config_avaliador(
                    ConfigAvaliador(voz=voz_atual, videos={"ouvindo": ouvindo.strip(), "falando": falando.strip(), "pensando": pensando.strip()})
                )
                st.success("Avaliador atualizado.")
            except Exception as e:  # noqa: BLE001
                _erro(e)
    if ouvindo := config.videos.get("ouvindo"):
        st.video(ouvindo, loop=True, autoplay=True, muted=True)


def _seletor_modelo(titulo: str, subtitulo: str, atual: str, provedores: dict[str, bool], papel: str, config: ConfigBanca) -> None:
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown(f"### {titulo}")
        a.caption(subtitulo)
        b.markdown(f"<span class='spo-badge'>Atual: {nome_modelo(atual)}{' (fora do catálogo)' if not buscar_modelo(atual) else ''}</span>", unsafe_allow_html=True)
        for provedor in ("openai", "anthropic", "google"):
            disponivel = provedores.get(provedor, False)
            st.markdown(
                f"<p class='spo-kicker' style='color:#777'>{PROVEDORES_LLM[provedor]['nome']}"
                + ("" if disponivel else f" <span style='color:#9b1c1c;text-transform:none;letter-spacing:0'>chave {PROVEDORES_LLM[provedor]['chave']} não configurada</span>")
                + "</p>",
                unsafe_allow_html=True,
            )
            cols = st.columns(3)
            for i, m in enumerate([m for m in MODELOS if m.provedor == provedor]):
                with cols[i % 3]:
                    ativo = atual == m.id
                    if st.button(
                        f"{'✓ ' if ativo else ''}{m.nome}\n\n{m.descricao} · {formatar_usd(m.preco_entrada)} / {formatar_usd(m.preco_saida)} por 1M tokens",
                        key=f"{papel}_{m.id}",
                        disabled=not disponivel or ativo,
                        use_container_width=True,
                    ):
                        _salvar_banca(config, papel, m.id)
        with st.form(f"outro_{papel}"):
            x, y, z = st.columns([1, 2, 1])
            prov = x.selectbox("Outro modelo", ["openai", "anthropic", "google"], format_func=lambda p: PROVEDORES_LLM[p]["nome"], key=f"outro_prov_{papel}")
            idm = y.text_input("ID do modelo (ex.: gemini-3.5-flash)", key=f"outro_id_{papel}")
            if z.form_submit_button("Usar") and idm.strip():
                _salvar_banca(config, papel, f"{prov}:{idm.strip()}")
        st.caption("Modelos fora do catálogo funcionam, mas o custo aparece como zero na aba Custos.")


def _salvar_banca(config: ConfigBanca, papel: str, modelo: str) -> None:
    if not separar_modelo(modelo):
        st.error("Use o formato provedor:modelo (ex.: openai:gpt-4o).")
        return
    novo = ConfigBanca(
        modelo_avaliadores=modelo if papel == "avaliadores" else config.modelo_avaliadores,
        modelo_juiz=modelo if papel == "juiz" else config.modelo_juiz,
        modelo_auxiliar=modelo if papel == "auxiliar" else config.modelo_auxiliar,
    )
    try:
        salvar_config_banca(novo)
        st.success("Banca atualizada.")
        st.rerun()
    except Exception as e:  # noqa: BLE001
        _erro(e)


def _banca() -> None:
    try:
        config = obter_config_banca()
        provedores = status_provedores()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    st.caption("Clique em um modelo para trocar. A mudança vale para a próxima resposta avaliada. Modelos de provedor sem chave aparecem desabilitados.")
    _seletor_modelo(
        "Modelo dos avaliadores",
        f"Usado pelos {len(AVALIADORES)} avaliadores independentes (4 chamadas por resposta + esclarecimentos). Um modelo barato costuma bastar.",
        config.modelo_avaliadores,
        provedores,
        "avaliadores",
        config,
    )
    _seletor_modelo(
        "Modelo do juiz",
        "Uma chamada por resposta (mais uma por esclarecimento). Vale investir num modelo forte.",
        config.modelo_juiz,
        provedores,
        "juiz",
        config,
    )
    with st.container(border=True):
        st.markdown("### Como a banca delibera")
        st.caption(
            f"Os avaliadores opinam em paralelo, sem ver uns aos outros. Se a diferença entre a maior e a menor nota "
            f"for de pelo menos {fmt_nota(LIMIAR_DIVERGENCIA)}, o juiz pode pedir até {MAX_ESCLARECIMENTOS} esclarecimentos "
            "(um por avaliador) antes do veredito. Cada agente é um Agent do Agno com saída estruturada."
        )
        cols = st.columns(2)
        agentes = [(a.nome, a.descricao, a.ve) for a in AVALIADORES] + [(JUIZ_NOME, "Recebe tudo e decide a nota final.", None)]
        for i, (nome, desc, ve) in enumerate(agentes):
            with cols[i % 2]:
                ve_txt = ""
                if ve:
                    itens = [n for n, ok in (("gabarito", ve.gabarito), ("base de conhecimento", ve.base_conhecimento), ("pontos-chave", ve.pontos_chave), ("fundamentos legais", ve.fundamentos)) if ok]
                    ve_txt = f"<br><span class='spo-muted'>Vê: {', '.join(itens) or 'só a pergunta e a resposta'}</span>"
                st.markdown(f"<div class='spo-card'><b>{nome}</b><br><span class='spo-muted'>{desc}</span>{ve_txt}</div>", unsafe_allow_html=True)


def _dossie_exemplo():
    """Dossiê real (última pergunta cadastrada) para a prévia dos prompts; cai num exemplo fixo."""
    from simulador.banca import Dossie
    from simulador.db import T

    p = next(iter(T("perguntas").listar(limite=1)), None) or {}
    return Dossie(
        pergunta=p.get("pergunta") or "Em que consiste o princípio da insignificância?",
        resposta_padrao=p.get("resposta_padrao") or "Causa supralegal de exclusão da tipicidade material…",
        transcricao="(aqui entra a transcrição da resposta falada pelo candidato)",
        contexto=["(aqui entram os trechos do material de estudo encontrados pela busca)"],
        pontos_chave=p.get("pontos_chave") or ["(ponto-chave esperado)"],
        fundamentos_legais=p.get("fundamentos_legais") or ["(fundamento legal de referência)"],
        materia=p.get("materia") or "Direito Penal",
        tema=p.get("tema") or "Tipicidade",
    )


def _agentes() -> None:
    """Aba Agentes: como cada Agent do Agno está montado e edição dos prompts."""
    try:
        config = obter_config_prompts()
        banca = obter_config_banca()
        provedores = status_provedores()
        previa = {i["id"]: i for i in previa_dos_prompts(_dossie_exemplo())}
    except Exception as e:  # noqa: BLE001
        return _erro(e)

    modelos_por_papel = {
        "auxiliar": banca.modelo_auxiliar,
        "avaliadores": banca.modelo_avaliadores,
        "juiz": banca.modelo_juiz,
    }
    st.caption(
        f"São {len(CATALOGO)} agentes, todos `Agent` do Agno com saída estruturada em Pydantic. "
        "Aqui você vê como cada um está montado e edita o prompt dele. A mudança vale na próxima "
        "resposta avaliada, sem reiniciar o app."
    )
    editados = [catalogo_por_id(i).nome for i in config.personas if catalogo_por_id(i) and config.editado(i)]
    if editados:
        st.info(f"Prompts personalizados: {', '.join(editados)}. Os demais usam o padrão do código.")

    st.markdown("### Modelo de cada grupo")
    c = st.columns(3)
    rotulos = [
        ("auxiliar", "Agentes da prova", "Classificador de turno e leitor de postura. Precisa enxergar imagem."),
        ("avaliadores", "Avaliadores da banca", "As 4 opiniões em paralelo, mais os esclarecimentos."),
        ("juiz", "Juiz da banca", "Uma chamada por resposta, mais uma por esclarecimento."),
    ]
    for i, (papel, titulo, ajuda) in enumerate(rotulos):
        with c[i]:
            with st.container(border=True):
                st.markdown(f"**{titulo}**")
                st.caption(ajuda)
                st.markdown(f"<span class='spo-badge'>{nome_modelo(modelos_por_papel[papel])}</span>", unsafe_allow_html=True)
    st.caption("Para trocar de modelo, use a aba Banca (avaliadores e juiz) ou o seletor abaixo (agentes da prova).")
    with st.expander("Trocar o modelo dos agentes da prova"):
        _seletor_modelo(
            "Modelo dos agentes da prova",
            "Usado pelo classificador de turno e pelo leitor de postura. Precisa aceitar imagem para a leitura de postura.",
            banca.modelo_auxiliar,
            provedores,
            "auxiliar",
            banca,
        )

    novos: dict[str, str] = {}
    for grupo in ("Prova", "Banca"):
        st.markdown(f"### Agentes da {'prova' if grupo == 'Prova' else 'banca'}")
        for info in [a for a in CATALOGO if a.grupo == grupo]:
            item = previa.get(info.id, {})
            marca = " ✏️" if config.editado(info.id) else ""
            with st.expander(f"{info.nome}{marca}"):
                st.caption(info.descricao)
                ficha = [
                    ("Quando roda", info.quando),
                    ("Modelo", f"{nome_modelo(modelos_por_papel[info.modelo])} · temperatura {info.temperatura}"),
                    ("Recebe", info.entrada),
                    ("Devolve", info.saida),
                    ("Ferramentas", ", ".join(info.ferramentas) or "nenhuma"),
                ]
                st.markdown(
                    "<div class='spo-card'>"
                    + "".join(f"<div><b>{k}:</b> <span class='spo-muted'>{v}</span></div>" for k, v in ficha)
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if info.observacao:
                    st.caption(f"ℹ️ {info.observacao}")

                novos[info.id] = st.text_area(
                    "Prompt (instrução de sistema)",
                    value=config.texto(info.id),
                    height=240,
                    key=f"persona_{info.id}",
                )
                if info.modelo == "avaliadores":
                    st.caption("As regras de saída, no fim desta aba, são acrescentadas ao final deste prompt.")
                if item:
                    st.markdown("**Prompt completo enviado ao modelo**")
                    st.caption("Prévia montada com a primeira pergunta do banco. Reflete o texto salvo, não o que você acabou de digitar.")
                    st.code(f"[SYSTEM]\n{item['instrucoes']}\n\n[USER]\n{item['prompt']}", language="text")

    regras = st.text_area(
        "Regras de saída (coladas ao fim do prompt dos 4 avaliadores)",
        value=config.regras_saida,
        height=110,
        key="persona_regras",
    )

    a, b = st.columns([1, 1])
    if a.button("Salvar prompts", type="primary"):
        try:
            salvar_config_prompts(ConfigPrompts(personas=novos, regras_saida=regras))
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        st.success("Prompts salvos. Valem na próxima resposta avaliada.")
        st.rerun()
    if b.button("Restaurar todos os padrões"):
        try:
            redefinir_prompts()
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        for info in CATALOGO:
            S.pop(f"persona_{info.id}", None)
        S.pop("persona_regras", None)
        st.success("Prompts restaurados ao padrão do código.")
        st.rerun()


def _chaves() -> None:
    st.caption("Cole a chave e salve: ela é cifrada no servidor e passa a valer imediatamente. Uma chave cadastrada aqui tem prioridade sobre a definida nos Secrets do Streamlit; remova-a para voltar ao segredo do servidor.")
    for info in CHAVES:
        try:
            sit = fonte_segredo(info.id)
        except Exception as e:  # noqa: BLE001
            _erro(e)
            continue
        with st.container(border=True):
            a, b = st.columns([3, 1.4])
            a.markdown(f"**{info.nome}**  \n<span class='spo-muted'>{info.descricao}</span>  \n`{info.id}`", unsafe_allow_html=True)
            estado = (
                "Não configurada"
                if not sit.configurada
                else f"Cadastrada no painel · …{sit.sufixo}"
                if sit.fonte == "painel"
                else f"Segredo do servidor · …{sit.sufixo}"
            )
            b.markdown(f"<span class='spo-badge {'spo-badge-vermelho' if not sit.configurada else ''}'>{estado}</span>", unsafe_allow_html=True)
            x, y, z, w = st.columns([4, 1, 1, 1])
            valor = x.text_input("Chave", type="password" if info.secreta else "default", key=f"chave_{info.id}", label_visibility="collapsed", placeholder="Colar nova chave para substituir" if sit.configurada else "Colar a chave")
            if y.button("Salvar", key=f"salvar_{info.id}", disabled=len(valor.strip()) < 4):
                try:
                    salvar_segredo(info.id, valor)
                    st.success(f"{info.nome}: chave salva.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    _erro(e)
            if info.testavel and sit.configurada and z.button("Testar", key=f"testar_{info.id}"):
                ok, detalhe = testar_chave(info.id)
                (st.success if ok else st.error)(detalhe)
            if sit.fonte == "painel" and w.button("Remover", key=f"remover_{info.id}"):
                remover_segredo(info.id)
                st.rerun()


def _concursos() -> None:
    esq, dir_ = st.columns([1, 1.2])
    with esq:
        with st.form("novo_concurso", clear_on_submit=True):
            st.markdown("### Novo concurso")
            nome = st.text_input("Nome")
            descricao = st.text_area("Descrição", height=80)
            qtd = st.number_input("Perguntas por simulação (padrão)", 1, 30, 10, help="O candidato escolhe 5, 10, 15, 20 ou 30 na sala de espera.")
            ativo = st.toggle("Disponível para os candidatos", value=True)
            if st.form_submit_button("Salvar concurso", type="primary", use_container_width=True):
                if len(nome.strip()) < 2:
                    st.error("Informe o nome.")
                else:
                    try:
                        adm.salvar_concurso(nome=nome.strip(), descricao=descricao.strip() or None, quantidade_perguntas=int(qtd), ativo=ativo)
                        st.success("Concurso salvo.")
                    except Exception as e:  # noqa: BLE001
                        _erro(e)
    with dir_:
        try:
            lista = adm.listar_concursos_admin()
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        for c in lista:
            with st.container(border=True):
                a, b = st.columns([5, 1])
                a.markdown(f"**{c['nome']}**  \n<span class='spo-muted'>{c['quantidade_perguntas']} perguntas · {'ativo' if c['ativo'] else 'inativo'}</span>", unsafe_allow_html=True)
                if c.get("descricao"):
                    a.caption(c["descricao"])
                with b.popover("🗑️"):
                    st.write("Excluir o concurso e todas as perguntas e sessões dele?")
                    if st.button("Excluir", key=f"exc_c_{c['id']}", type="primary"):
                        adm.excluir_concurso(c["id"])
                        st.rerun()
                with st.expander("Editar"):
                    with st.form(f"edit_c_{c['id']}"):
                        n = st.text_input("Nome", value=c["nome"])
                        d = st.text_area("Descrição", value=c.get("descricao") or "", height=80)
                        q = st.number_input("Perguntas por simulação", 1, 30, int(c["quantidade_perguntas"]))
                        at = st.toggle("Ativo", value=bool(c["ativo"]))
                        if st.form_submit_button("Salvar alterações"):
                            adm.salvar_concurso(id=c["id"], nome=n.strip(), descricao=d.strip() or None, quantidade_perguntas=int(q), ativo=at)
                            st.rerun()


def _perguntas() -> None:
    try:
        concursos = adm.listar_concursos_admin()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    if not concursos:
        st.caption("Cadastre um concurso antes de criar perguntas.")
        return
    concurso_id = st.selectbox("Concurso", [c["id"] for c in concursos], format_func=lambda i: next(c["nome"] for c in concursos if c["id"] == i), key="perg_concurso")
    esq, dir_ = st.columns([1, 1.1])
    with esq:
        with st.form("nova_pergunta", clear_on_submit=True):
            st.markdown("### Nova pergunta")
            a, b, c = st.columns(3)
            grupo = a.number_input("Grupo", 1, 999, 1)
            seq = b.selectbox("Momento", ["inicio", "meio", "fim"], format_func=lambda s: {"inicio": "Início", "meio": "Meio", "fim": "Fim"}[s])
            ordem = c.number_input("Ordem", 1, 999, 1)
            pergunta = st.text_area("Pergunta", height=90)
            resposta = st.text_area("Resposta padrão (gabarito)", height=160)
            if st.form_submit_button("Salvar pergunta", type="primary", use_container_width=True):
                if len(pergunta.strip()) < 3 or len(resposta.strip()) < 3:
                    st.error("Preencha a pergunta e a resposta padrão.")
                else:
                    try:
                        r = adm.salvar_pergunta(concurso_id=concurso_id, grupo=int(grupo), sequencia=seq, pergunta=pergunta.strip(), resposta_padrao=resposta.strip(), ordem=int(ordem))
                        st.success("Pergunta salva." + (f" (vetorização falhou: {r['erro']})" if r.get("erro") else " Indexada na base de gabaritos."))
                    except Exception as e:  # noqa: BLE001
                        _erro(e)
        with st.container(border=True):
            try:
                g = adm.estado_das_bases(concurso_id)["gabaritos"]
            except Exception as e:  # noqa: BLE001
                return _erro(e)
            st.markdown("**Base de gabaritos**")
            st.caption("Índice semântico das perguntas, usado só aqui no painel. A banca não o consulta durante a prova.")
            st.markdown(f"{g['indexadas']} de {g['perguntas']} perguntas · {g['trechos']} trechos")
            if st.button("Revetorizar perguntas deste concurso", disabled=not g["perguntas"]):
                with st.spinner("Gerando embeddings…"):
                    try:
                        r = adm.vetorizar_concurso(concurso_id)
                    except Exception as e:  # noqa: BLE001
                        return _erro(e)
                st.success(f"{r['vetorizadas']} de {r['perguntas']} perguntas indexadas."
                           + (f" Erros: {'; '.join(r['erros'])}" if r["erros"] else ""))
                st.rerun()
    with dir_:
        try:
            perguntas = adm.listar_perguntas(concurso_id)
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        st.caption(f"{len(perguntas)} perguntas")
        if not perguntas:
            st.caption("Nenhuma pergunta cadastrada.")
        dific = {"facil": "fácil", "media": "média", "dificil": "difícil"}
        for p in perguntas[:300]:
            meta = " · ".join(x for x in (p.get("materia"), p.get("tema"), dific.get(p.get("dificuldade") or "")) if x)
            with st.expander(f"G{p['grupo']} · {p['sequencia']} · #{p['ordem']} — {p['pergunta'][:90]}"):
                if meta:
                    st.caption(meta + (f" · {p['tipo']}" if p.get("tipo") else ""))
                with st.form(f"edit_p_{p['id']}"):
                    a, b, c = st.columns(3)
                    g = a.number_input("Grupo", 1, 999, int(p["grupo"]))
                    s = b.selectbox("Momento", ["inicio", "meio", "fim"], index=["inicio", "meio", "fim"].index(p["sequencia"]))
                    o = c.number_input("Ordem", 1, 999, int(p["ordem"]))
                    pt = st.text_area("Pergunta", value=p["pergunta"], height=90)
                    rp = st.text_area("Resposta padrão (gabarito)", value=p["resposta_padrao"], height=180)
                    x, y = st.columns(2)
                    if x.form_submit_button("Salvar alterações"):
                        try:
                            adm.salvar_pergunta(id=p["id"], concurso_id=concurso_id, grupo=int(g), sequencia=s, pergunta=pt.strip(), resposta_padrao=rp.strip(), ordem=int(o))
                            st.success("Pergunta atualizada e revetorizada na base de conhecimento.")
                        except Exception as e:  # noqa: BLE001
                            _erro(e)
                    if y.form_submit_button("🗑️ Excluir"):
                        adm.excluir_pergunta(p["id"])
                        st.rerun()


def _importar() -> None:
    try:
        concursos = adm.listar_concursos_admin()
    except Exception as e:  # noqa: BLE001
        return _erro(e)
    esq, dir_ = st.columns([1, 1.1])
    with esq:
        with st.container(border=True):
            st.markdown("### 1. Arquivo do banco de questões")
            st.caption("Envie o `banco_final.json`. Cada prova real vira um **grupo** sorteável; momento, matéria, tema, dificuldade, cadeias, pontos-chave e fundamentos legais são preservados.")
            arquivo = st.file_uploader("Arquivo JSON", type=["json"], key="imp_arquivo")
        itens, resumo = [], None
        if arquivo is not None:
            try:
                itens, resumo = converter_banco_questoes(json.load(arquivo))
                if not itens:
                    raise ValueError("Nenhuma pergunta válida encontrada no arquivo.")
                st.success(f"{arquivo.name} lido: {len(itens)} perguntas prontas.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Não foi possível ler o arquivo: {e}")
                itens, resumo = [], None
        with st.container(border=True):
            st.markdown("### 2. Concurso de destino")
            destino = st.radio("Destino", ["novo", "existente"], format_func=lambda d: "Criar concurso novo" if d == "novo" else "Usar concurso existente", horizontal=True, label_visibility="collapsed")
            if destino == "novo":
                nome = st.text_input("Nome", value="MP-SP — Promotor de Justiça")
                descricao = st.text_area("Descrição", value="Banco de perguntas extraído de arguições orais reais do concurso de Promotor de Justiça do MP-SP.", height=70)
                qtd = st.number_input("Perguntas por simulação (padrão)", 1, 30, 10)
                concurso_id = None
                valido = len(nome.strip()) >= 2
            else:
                concurso_id = st.selectbox("Concurso", [c["id"] for c in concursos], format_func=lambda i: next(c["nome"] for c in concursos if c["id"] == i)) if concursos else None
                st.caption("Perguntas já importadas (mesmo uid de origem) são atualizadas, não duplicadas.")
                valido = bool(concurso_id)
        if st.button(f"⬆️ Importar {len(itens) or ''} perguntas", type="primary", disabled=not (itens and valido), use_container_width=True):
            barra = st.progress(0, text="Preparando…")
            acumulado = {"inseridas": 0, "atualizadas": 0, "vetorizadas": 0, "avisos": []}
            try:
                destino_id, nome_destino = adm.preparar_importacao(
                    concurso_id=concurso_id,
                    novo=None if concurso_id else {"nome": nome.strip(), "descricao": descricao.strip() or None, "quantidade_perguntas": int(qtd)},
                )
                for i in range(0, len(itens), TAMANHO_LOTE_IMPORTACAO):
                    lote = itens[i : i + TAMANHO_LOTE_IMPORTACAO]
                    r = adm.importar_lote(destino_id, lote)
                    for k in ("inseridas", "atualizadas", "vetorizadas"):
                        acumulado[k] += r[k]
                    if r.get("erro_vetorizacao") and r["erro_vetorizacao"] not in acumulado["avisos"]:
                        acumulado["avisos"].append(r["erro_vetorizacao"])
                    feitos = min(len(itens), i + len(lote))
                    barra.progress(feitos / len(itens), text=f"{feitos} de {len(itens)} perguntas")
                st.success(f'Importação concluída em "{nome_destino}": {acumulado["inseridas"]} novas, {acumulado["atualizadas"]} atualizadas, {acumulado["vetorizadas"]} vetorizadas.')
                for a in acumulado["avisos"]:
                    st.warning(f"As perguntas foram salvas, mas a vetorização falhou: {a}")
            except Exception as e:  # noqa: BLE001
                st.error(f"{e} — corrija e importe de novo: o que já entrou não será duplicado.")
    with dir_:
        if not resumo:
            st.caption("Selecione o arquivo para ver o que será importado.")
            return
        c = st.columns(3)
        c[0].metric("Perguntas", resumo.total)
        c[1].metric("Grupos (provas)", len(resumo.grupos))
        c[2].metric("Matérias", len(resumo.materias))
        with st.container(border=True):
            st.markdown("**Grupos sorteáveis**")
            st.caption(f"Início {resumo.momentos['inicio']} · meio {resumo.momentos['meio']} · fim {resumo.momentos['fim']}")
            st.dataframe([{"grupo": g["grupo"], "prova": g["provaId"], "perguntas": g["perguntas"]} for g in resumo.grupos], hide_index=True, use_container_width=True)
        with st.container(border=True):
            st.markdown("**Matérias**")
            st.markdown(" ".join(f"<span class='spo-badge spo-badge-cinza'>{m['nome']} · {m['total']}</span>" for m in resumo.materias), unsafe_allow_html=True)
        if resumo.ignoradas:
            st.warning(f"{len(resumo.ignoradas)} perguntas ignoradas por falta de campos: " + "; ".join(f"{i['uid']} ({i['motivo']})" for i in resumo.ignoradas[:10]))


def _extrair_texto(arquivo) -> str:
    nome = arquivo.name.lower()
    dados = arquivo.getvalue()
    if nome.endswith(".pdf"):
        from pypdf import PdfReader

        leitor = PdfReader(BytesIO(dados))
        return "\n\n".join((pagina.extract_text() or "") for pagina in leitor.pages)
    return dados.decode("utf-8", errors="ignore")


def _bases() -> None:
    """Duas bases vetoriais isoladas: material de estudo (lida na prova) e gabaritos (só no painel)."""
    try:
        concursos = adm.listar_concursos_admin()
        estado = adm.estado_das_bases()
    except Exception as e:  # noqa: BLE001
        return _erro(e)

    tipo, descricao, persistente = onde_esta_o_banco()
    if persistente:
        st.caption(f"Banco: {descricao}. Os dados sobrevivem a reinícios do app.")
    else:
        st.warning(
            f"Banco: {descricao}. **Os dados somem quando o app reinicia.** No Streamlit Community Cloud "
            "o disco é apagado a cada reinício: configure CHROMA_API_KEY, CHROMA_TENANT e CHROMA_DATABASE "
            "nos Secrets para usar o Chroma Cloud.",
            icon="⚠️",
        )

    a, b = st.columns(2)
    with a:
        with st.container(border=True):
            st.markdown("#### 📚 Base 1 · Material de estudo")
            st.caption("Arquivos que você envia. É a única base que a banca consulta durante a prova.")
            m = estado["material"]
            st.markdown(f"**{m['documentos']}** arquivos · **{m['trechos']}** trechos indexados"
                        + (f" · {m['erros']} com erro" if m["erros"] else ""))
    with b:
        with st.container(border=True):
            st.markdown("#### 🔑 Base 2 · Gabaritos")
            st.caption("Perguntas e respostas padrão do banco. Isolada: nunca é lida durante a prova, para o gabarito de uma pergunta não vazar na avaliação de outra.")
            g = estado["gabaritos"]
            st.markdown(f"**{g['indexadas']}** de {g['perguntas']} perguntas · **{g['trechos']}** trechos indexados")
            if g["perguntas"] and g["indexadas"] < g["perguntas"]:
                st.caption("Perguntas não indexadas: use *Revetorizar* na aba Perguntas.")

    material_tab, gabarito_tab = st.tabs(["Material de estudo", "Gabaritos (busca)"])
    with gabarito_tab:
        st.caption("Busca semântica no banco de questões. Serve para achar perguntas parecidas ou repetidas. Nada daqui chega à banca.")
        termo = st.text_input("Buscar no gabarito", key="busca_gab", placeholder="ex.: improbidade administrativa")
        if termo:
            try:
                achados = adm.buscar_gabaritos(termo, n=5)
            except Exception as e:  # noqa: BLE001
                return _erro(e)
            if not achados:
                st.caption("Nada encontrado. A base de gabaritos pode estar vazia.")
            for t in achados:
                st.markdown(f'<div class="spo-card"><p class="spo-muted">{t}</p></div>', unsafe_allow_html=True)
    with material_tab:
        _material(concursos)


def _material(concursos: list[dict]) -> None:
    esq, dir_ = st.columns([1, 1.1])
    with esq:
        with st.container(border=True):
            st.markdown("### Enviar material")
            st.caption("PDF, TXT ou MD. Você pode selecionar vários arquivos de uma vez. O conteúdo é dividido em trechos e é o que a banca consulta ao avaliar as respostas (RAG).")
            concurso_id = st.selectbox("Vincular a um concurso (opcional)", [""] + [c["id"] for c in concursos], format_func=lambda i: "Todos os concursos" if not i else next(c["nome"] for c in concursos if c["id"] == i))
            arquivos = st.file_uploader("Arquivos", type=["pdf", "txt", "md"], accept_multiple_files=True, key="doc_arquivos")
            if st.button("Indexar arquivos", type="primary", disabled=not arquivos):
                ok, falhas = 0, []
                barra = st.progress(0)
                for i, f in enumerate(arquivos):
                    try:
                        texto = _extrair_texto(f)
                        if len(texto.strip()) < 20:
                            falhas.append(f"{f.name}: sem texto legível")
                            continue
                        adm.indexar_documento(f.name, texto, concurso_id or None)
                        ok += 1
                    except Exception as e:  # noqa: BLE001
                        falhas.append(f"{f.name}: {e}")
                    barra.progress((i + 1) / len(arquivos), text=f"{i + 1} de {len(arquivos)}: {f.name}")
                if ok:
                    st.success(f"{ok} de {len(arquivos)} arquivo(s) indexado(s).")
                for fl in falhas:
                    st.error(fl)
    with dir_:
        try:
            docs = adm.listar_documentos()
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        if not docs:
            st.caption("Nenhum material enviado ainda. Sem material, o Verificador da banca avalia sem trechos de apoio.")
        for d in docs[:200]:
            with st.container(border=True):
                a, b = st.columns([5, 1])
                a.markdown(f"**{d['nome']}**  \n<span class='spo-muted'>{d['total_chunks']} trechos · {d['status']} · {d['concurso']}</span>", unsafe_allow_html=True)
                if d.get("erro"):
                    a.caption(f"Erro: {d['erro']}")
                if b.button("🗑️", key=f"doc_{d['id']}"):
                    adm.excluir_documento(d["id"])
                    st.rerun()


# ---------- página ----------


def render() -> None:
    cabecalho()
    user_id = S.get("admin_user_id")
    if not user_id:
        ir("auth")
    try:
        admin_ok = sou_admin(user_id)
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível verificar suas permissões: {e}")
        return
    if not admin_ok:
        st.markdown("# Acesso restrito")
        st.markdown("Sua conta não tem permissão de administrador neste simulador.")
        if st.button("Sair"):
            S.pop("admin_user_id", None)
            ir("auth")
        link("home", "Voltar ao início")
        return

    a, b = st.columns([6, 1])
    with a:
        st.markdown('<p class="spo-kicker">Administração</p>', unsafe_allow_html=True)
        st.markdown("## Painel do simulador")
    with b:
        if st.button("Sair", use_container_width=True):
            S.pop("admin_user_id", None)
            ir("auth")

    abas = st.tabs(["Estatísticas", "Sessões", "Custos", "Avaliador", "Banca", "Agentes", "Chaves de API", "Concursos", "Perguntas", "Importar", "Bases de conhecimento"])
    with abas[0]:
        _estatisticas()
    with abas[1]:
        _sessoes()
    with abas[2]:
        _custos()
    with abas[3]:
        _avaliador()
    with abas[4]:
        _banca()
    with abas[5]:
        _agentes()
    with abas[6]:
        _chaves()
    with abas[7]:
        _concursos()
    with abas[8]:
        _perguntas()
    with abas[9]:
        _importar()
    with abas[10]:
        _bases()
