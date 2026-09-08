"""Orquestração da banca (Agno) com o modelo simulado: avaliadores em paralelo, juiz com
ferramenta de esclarecimento e ata completa. Não chama nenhuma API externa."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHAVES_CRIPTO_SECRET", "segredo-de-teste")

import pytest  # noqa: E402

from simulador import agentes  # noqa: E402
from simulador.banca import AVALIADORES, Dossie, Esclarecimento, ParecerAvaliador, Veredito  # noqa: E402
from simulador.config_app import ConfigBanca  # noqa: E402


class _Saida(SimpleNamespace):
    pass


def _saida(conteudo):
    return _Saida(content=conteudo, metrics=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def banca_simulada(monkeypatch):
    """Substitui Agent.run por respostas determinísticas e desliga banco/segredos."""
    monkeypatch.setattr(agentes, "obter_config_banca", lambda: ConfigBanca("openai:gpt-4o-mini", "openai:gpt-4o"))
    monkeypatch.setattr(agentes, "obter_segredo", lambda _id: "sk-teste")
    monkeypatch.setattr(agentes, "registrar_uso", lambda **kw: None)

    notas = {"critico": 3.0, "tranquilo": 8.0, "verificador": 6.0, "independente": 7.0}
    chamadas = {"juiz": 0}

    def run(self, entrada, **kwargs):
        schema = self.output_schema
        if schema is ParecerAvaliador:
            agente = next(a for a in AVALIADORES if a.persona in (self.instructions or ""))
            return _saida(ParecerAvaliador(nota=notas[agente.id], parecer=f"parecer {agente.id}", pontos_cobertos=["x"], pontos_faltantes=[], alertas=[]))
        if schema is Esclarecimento:
            return _saida(Esclarecimento(esclarecimento="mantenho", nota_revisada=None))
        if schema is Veredito:
            chamadas["juiz"] += 1
            # O juiz usa a ferramenta quando ela está disponível.
            if self.tools:
                r = self.tools[0]("critico", "O candidato citou o art. 18 — isso não atende ao ponto?")
                assert "mantenho" in r
                r2 = self.tools[0]("critico", "de novo?")
                assert "Limite" in r2  # uma pergunta por avaliador
            return _saida(Veredito(nota=6.5, justificativa="ok", pontos_cobertos=["x"], pontos_faltantes=["y"]))
        raise AssertionError(f"schema inesperado: {schema}")

    monkeypatch.setattr(agentes.Agent, "run", run)
    return chamadas


def _dossie() -> Dossie:
    return Dossie(
        pergunta="O que é tutela provisória?",
        resposta_padrao="Gabarito.",
        transcricao="Resposta do candidato.",
        contexto=["trecho 1"],
        pontos_chave=["a", "b"],
        fundamentos_legais=["art. 300 CPC"],
        materia="Processo Civil",
        tema="Tutela",
        sessao_id=None,
    )


def test_banca_com_divergencia_delibera(banca_simulada):
    veredito, ata = agentes.avaliar_com_banca(_dossie())
    assert veredito.nota == 6.5
    assert len(ata.avaliadores) == 4
    assert ata.divergencia == 5.0
    assert [e["tipo"] for e in ata.deliberacao] == ["pergunta", "esclarecimento"]
    assert ata.juiz == {"modelo": "openai:gpt-4o", "nota": 6.5}
    assert banca_simulada["juiz"] == 1


def test_dossie_respeita_visao_do_avaliador():
    d = _dossie()
    independente = next(a for a in AVALIADORES if a.id == "independente")
    texto = agentes._dossie_do_avaliador(independente.ve, d)
    assert "RESPOSTA PADRÃO" not in texto and "BASE DE CONHECIMENTO" not in texto
    critico = next(a for a in AVALIADORES if a.id == "critico")
    texto = agentes._dossie_do_avaliador(critico.ve, d)
    assert "RESPOSTA PADRÃO" in texto and "FUNDAMENTOS LEGAIS" in texto and "BASE DE CONHECIMENTO" not in texto


def test_resolver_modelo_temperatura(monkeypatch):
    monkeypatch.setattr(agentes, "obter_segredo", lambda _id: "k")
    assert agentes.resolver_modelo("openai:gpt-4o").instancia.temperature == 0.2
    assert agentes.resolver_modelo("openai:gpt-5-mini").instancia.temperature is None
    assert agentes.resolver_modelo("anthropic:claude-sonnet-5").instancia.temperature is None
    assert agentes.resolver_modelo("google:gemini-2.5-flash").instancia.temperature == 0.2
    with pytest.raises(agentes.IntegracaoError):
        agentes.resolver_modelo("invalido")
