"""Camada ChromaDB e fluxo completo da simulação (com agentes simulados), num banco temporário."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHAVES_CRIPTO_SECRET", "segredo-de-teste")


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    os.environ["CHROMA_PATH"] = str(tmp_path_factory.mktemp("chroma"))
    from simulador import db

    db.cliente.cache_clear()
    from simulador.esquema import inicializar

    inicializar(db.cliente())
    return db


def test_tabela_crud_e_filtros(banco):
    t = banco.T("concursos")
    a = t.inserir({"nome": "B", "descricao": None, "quantidade_perguntas": 5, "ativo": True})
    b = t.inserir({"nome": "A", "descricao": "x", "quantidade_perguntas": 10, "ativo": False})
    assert t.obter(a["id"])["nome"] == "B"
    assert [c["nome"] for c in t.listar(ordenar="nome")] == ["A", "B"]
    assert t.contar(banco.onde(ativo=True)) == 1
    t.atualizar(b["id"], {"ativo": True})
    assert t.contar(banco.onde(ativo=True)) == 2
    assert set(t.obter_varios([a["id"], b["id"], "nao-existe"])) == {a["id"], b["id"]}
    t.remover(a["id"])
    assert t.obter(a["id"]) is None
    t.remover_onde(banco.onde(ativo=True))
    assert t.contar() == 0


def test_vetores_busca_por_concurso(banco):
    v = banco.material()
    v.adicionar(
        [
            {"id": "d1:0", "documento_id": "d1", "concurso_id": "c1", "indice": 0},
            {"id": "d2:0", "documento_id": "d2", "concurso_id": "", "indice": 0},
            {"id": "d3:0", "documento_id": "d3", "concurso_id": "c2", "indice": 0},
        ],
        [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [1.0, 0.0, 0.1]],
        ["do c1", "geral", "do c2"],
    )
    achados = v.buscar([1.0, 0.0, 0.0], where={"$or": [{"concurso_id": "c1"}, {"concurso_id": ""}]}, n=5)
    assert set(achados) == {"do c1", "geral"}
    v.remover_onde(banco.onde(documento_id="d3"))
    assert v.col.count() == 2


def test_bases_sao_isoladas(banco, monkeypatch):
    """O gabarito de uma pergunta nunca pode voltar na busca de contexto da prova."""
    from simulador import simulacao

    banco.gabaritos().adicionar(
        [{"id": "p1:0", "pergunta_id": "p1", "concurso_id": "iso", "indice": 0}],
        [[1.0, 0.0, 0.0]],
        ["Resposta padrão: o prazo prescricional é de cinco anos."],
    )
    banco.material().adicionar(
        [{"id": "dm:0", "documento_id": "dm", "concurso_id": "iso", "indice": 0}],
        [[1.0, 0.0, 0.0]],
        ["Trecho de doutrina sobre prescrição."],
    )
    # Mesmo com embeddings idênticos, o contexto da prova só enxerga a base de material.
    monkeypatch.setattr(simulacao, "gerar_embeddings", lambda textos, s=None: [[1.0, 0.0, 0.0]])
    contexto = simulacao._contexto_relevante("Qual o prazo?", "cinco anos", "iso", "sessao")
    assert "Trecho de doutrina sobre prescrição." in contexto
    assert not any("Resposta padrão" in c for c in contexto)
    banco.gabaritos().remover_onde(banco.onde(pergunta_id="p1"))
    banco.material().remover_onde(banco.onde(documento_id="dm"))


def test_configuracoes_e_segredos(banco):
    from simulador import segredos
    from simulador.config_app import ConfigBanca, _cache, obter_config_banca, salvar_config_banca

    salvar_config_banca(ConfigBanca("openai:gpt-4o-mini", "anthropic:claude-sonnet-5"))
    _cache.clear()
    assert obter_config_banca().modelo_juiz == "anthropic:claude-sonnet-5"

    segredos.salvar_segredo("OPENAI_API_KEY", "sk-teste-1234")
    assert segredos.obter_segredo("OPENAI_API_KEY") == "sk-teste-1234"
    f = segredos.fonte_segredo("OPENAI_API_KEY")
    assert f.fonte == "painel" and f.sufixo == "1234"
    segredos.remover_segredo("OPENAI_API_KEY")
    assert segredos.fonte_segredo("OPENAI_API_KEY").fonte in (None, "servidor")


def test_fluxo_completo_da_prova(banco, monkeypatch):
    from simulador import admin, agentes, simulacao
    from simulador.banca import AtaBanca, Veredito

    # Agentes e embeddings simulados: nada sai para a internet.
    monkeypatch.setattr(simulacao, "interpretar_turno", lambda p, t, s=None: agentes.TurnoCandidato(intencao="repetir" if "repetir" in t else "resposta", fala=""))
    monkeypatch.setattr(simulacao, "avaliar_com_banca", lambda d: (Veredito(nota=7.5, justificativa="ok", pontos_cobertos=["a"], pontos_faltantes=[]), AtaBanca([{"agenteId": "critico", "nome": "Crítico", "modelo": "m", "nota": 7, "parecer": "p", "pontos_cobertos": [], "pontos_faltantes": [], "alertas": []}], [], {"modelo": "m", "nota": 7.5}, 0.0)))
    monkeypatch.setattr(simulacao, "analisar_postura", lambda *a, **k: None)
    monkeypatch.setattr(simulacao, "gerar_embeddings", lambda textos, s=None: [[1.0, 0.0, 0.0]])
    monkeypatch.setattr(admin, "gerar_embeddings", lambda textos, s=None: [[1.0, 0.0, 0.0] for _ in textos])

    cid = admin.salvar_concurso(nome="MP Teste", descricao=None, quantidade_perguntas=5, ativo=True)
    for i, seq in enumerate(["inicio", "meio", "fim"], start=1):
        admin.salvar_pergunta(concurso_id=cid, grupo=1, sequencia=seq, pergunta=f"P{i}?", resposta_padrao=f"R{i}", ordem=i)
    assert admin.listar_perguntas(cid)[0]["pergunta"] == "P1?"
    assert simulacao.listar_concursos_publicos()[0]["nome"] == "MP Teste"

    sid = simulacao.iniciar_simulacao(cid, "Ana", 5, "127.0.0.1")
    estado = simulacao.obter_estado(sid)
    assert estado.total == 3 and estado.pergunta_atual.texto == "P1?" and estado.grupo == 1

    r = simulacao.responder(sid, "pode repetir?")
    assert r.fala and r.estado.indice == 0  # repetição não avança

    for _ in range(3):
        r = simulacao.responder(sid, "Minha resposta sobre o tema com fundamento.")
    assert r.estado.status == "finalizada" and r.estado.nota_final == 7.5

    estado, respostas = simulacao.obter_resultado(sid)
    assert len(respostas) == 3 and respostas[0]["pergunta"] == "P1?" and respostas[0]["ata"]

    m = admin.metricas_uso()
    assert m["total_sessoes"] == 1 and m["total_candidatos"] == 1
    det = admin.detalhe_sessao(sid)
    assert det["nota"] == 7.5 and len(det["respostas"]) == 3

    # Cascata: excluir o concurso limpa perguntas, sessões, respostas, documentos e trechos.
    admin.excluir_concurso(cid)
    assert banco.T("perguntas").contar() == 0 and banco.T("sessoes").contar() == 0 and banco.T("respostas").contar() == 0
    assert banco.T("documentos").contar() == 0


def test_importacao_idempotente(banco, monkeypatch):
    from simulador import admin
    from simulador.banco_questoes import ItemImportacao

    monkeypatch.setattr(admin, "gerar_embeddings", lambda textos, s=None: [[1.0, 0.0, 0.0] for _ in textos])
    cid, _ = admin.preparar_importacao(novo={"nome": "Importado", "quantidade_perguntas": 10})
    itens = [ItemImportacao(origem_uid=f"p/q{i}", grupo=1, ordem=i, sequencia="meio", pergunta=f"Q{i}", resposta_padrao="R") for i in range(1, 4)]
    r1 = admin.importar_lote(cid, itens)
    r2 = admin.importar_lote(cid, itens)
    assert (r1["inseridas"], r1["atualizadas"]) == (3, 0)
    assert (r2["inseridas"], r2["atualizadas"]) == (0, 3)
    assert banco.T("perguntas").contar(banco.onde(concurso_id=cid)) == 3
    admin.excluir_concurso(cid)


def test_prompts_editaveis(banco):
    """Editar a persona no painel muda a instrução que o agente recebe; restaurar volta ao padrão."""
    import pytest

    from simulador.agentes import instrucoes_do_avaliador, instrucoes_do_juiz
    from simulador.banca import JUIZ_ID, PERSONAS_PADRAO
    from simulador.config_app import (
        ConfigPrompts,
        _cache,
        obter_config_prompts,
        redefinir_prompts,
        salvar_config_prompts,
    )

    _cache.clear()
    assert instrucoes_do_avaliador("critico").startswith(PERSONAS_PADRAO["critico"])
    assert not obter_config_prompts().editado("critico")

    nova = "Você é um examinador de teste. Avalie apenas se a resposta cita a lei correta e nada mais."
    salvar_config_prompts(ConfigPrompts(personas={"critico": nova, JUIZ_ID: ""}, regras_saida="Responda em português."))
    _cache.clear()
    c = obter_config_prompts()
    assert c.editado("critico") and not c.editado(JUIZ_ID)
    assert instrucoes_do_avaliador("critico") == nova + "Responda em português."
    assert instrucoes_do_juiz() == PERSONAS_PADRAO[JUIZ_ID]  # não editado = padrão do código
    # Os outros avaliadores seguem no padrão.
    assert instrucoes_do_avaliador("tranquilo").startswith(PERSONAS_PADRAO["tranquilo"])

    with pytest.raises(ValueError):
        salvar_config_prompts(ConfigPrompts(personas={"critico": "curto"}, regras_saida=""))
    with pytest.raises(ValueError):
        salvar_config_prompts(ConfigPrompts(personas={"inexistente": nova}, regras_saida=""))

    redefinir_prompts()
    _cache.clear()
    assert instrucoes_do_avaliador("critico").startswith(PERSONAS_PADRAO["critico"])


def test_previa_dos_prompts_mostra_o_que_cada_agente_ve(banco):
    from simulador.agentes import previa_dos_prompts
    from simulador.banca import Dossie

    d = Dossie(
        pergunta="Pergunta?", resposta_padrao="GABARITO SECRETO", transcricao="resposta do candidato",
        contexto=["TRECHO DO MATERIAL"], pontos_chave=["ponto"], fundamentos_legais=["art. 1"],
        materia="M", tema="T",
    )
    por_id = {i["id"]: i for i in previa_dos_prompts(d)}
    assert set(por_id) == {"turno", "postura", "critico", "tranquilo", "verificador", "independente", "juiz"}
    # Os agentes da prova nunca recebem gabarito nem material.
    for aux in ("turno", "postura"):
        assert "GABARITO SECRETO" not in por_id[aux]["prompt"]
        assert "TRECHO DO MATERIAL" not in por_id[aux]["prompt"]
    # O jurista independente não pode ver gabarito nem material.
    ind = por_id["independente"]["prompt"]
    assert "GABARITO SECRETO" not in ind and "TRECHO DO MATERIAL" not in ind
    # O verificador vê os dois.
    ver = por_id["verificador"]["prompt"]
    assert "GABARITO SECRETO" in ver and "TRECHO DO MATERIAL" in ver
    # Toda prévia traz as instruções de sistema.
    assert all(i["instrucoes"] for i in por_id.values())


def test_catalogo_cobre_todos_os_agentes(banco):
    from simulador.agentes import previa_dos_prompts
    from simulador.banca import Dossie
    from simulador.catalogo import CATALOGO, IDS
    from simulador.personas import PADRAO

    assert set(IDS) == set(PADRAO), "catálogo e personas padrão precisam ter os mesmos agentes"
    d = Dossie(pergunta="P", resposta_padrao="R", transcricao="T", contexto=[], pontos_chave=[], fundamentos_legais=[])
    assert {i["id"] for i in previa_dos_prompts(d)} == set(IDS)
    for info in CATALOGO:
        assert info.nome and info.quando and info.saida and info.entrada
        assert info.modelo in {"auxiliar", "avaliadores", "juiz"}


def test_prompt_do_turno_e_editavel(banco):
    """O classificador de turno passou a ser editável pelo painel."""
    from simulador.agentes import instrucoes_do_turno
    from simulador.config_app import ConfigPrompts, _cache, redefinir_prompts, salvar_config_prompts
    from simulador.personas import TURNO

    _cache.clear()
    assert instrucoes_do_turno() == TURNO
    novo = "Classifique a fala do candidato. Só considere desistência quando ele pedir para pular de forma explícita."
    salvar_config_prompts(ConfigPrompts(personas={"turno": novo}, regras_saida=""))
    _cache.clear()
    assert instrucoes_do_turno() == novo
    redefinir_prompts()
    _cache.clear()
    assert instrucoes_do_turno() == TURNO
