"""A banca examinadora: avaliadores independentes com personas distintas e um juiz.

Só dados e tipos. A execução com Agno está em `simulador.agentes`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from . import personas


@dataclass(frozen=True)
class VisaoAvaliador:
    """O que cada avaliador enxerga do dossiê. A independência começa aqui."""

    gabarito: bool
    base_conhecimento: bool
    pontos_chave: bool
    fundamentos: bool


@dataclass(frozen=True)
class AgenteAvaliador:
    id: str
    nome: str
    descricao: str
    persona: str
    ve: VisaoAvaliador
    peso: float = 1.0


class ParecerAvaliador(BaseModel):
    """Saída estruturada de um avaliador (rodada 1)."""

    nota: float = Field(ge=0, le=10)
    parecer: str = Field(min_length=1)
    pontos_cobertos: list[str]
    pontos_faltantes: list[str]
    alertas: list[str]


class Esclarecimento(BaseModel):
    esclarecimento: str = Field(min_length=1)
    nota_revisada: float | None = Field(default=None, ge=0, le=10)


class Veredito(BaseModel):
    nota: float = Field(ge=0, le=10)
    justificativa: str = Field(min_length=1)
    pontos_cobertos: list[str]
    pontos_faltantes: list[str]


@dataclass
class Dossie:
    pergunta: str
    resposta_padrao: str
    transcricao: str
    contexto: list[str]
    pontos_chave: list[str]
    fundamentos_legais: list[str]
    materia: str | None = None
    tema: str | None = None
    sessao_id: str | None = None


@dataclass
class AtaBanca:
    """Registro completo da deliberação, guardado em `respostas.pareceres`."""

    avaliadores: list[dict]
    deliberacao: list[dict]
    juiz: dict
    divergencia: float

    def para_json(self) -> dict:
        return {
            "avaliadores": self.avaliadores,
            "deliberacao": self.deliberacao,
            "juiz": self.juiz,
            "divergencia": self.divergencia,
        }


LIMIAR_DIVERGENCIA = 1.5
MAX_ESCLARECIMENTOS = 3

AVALIADORES: list[AgenteAvaliador] = [
    AgenteAvaliador(
        id="critico",
        nome="Avaliador crítico",
        descricao="Rigoroso: cobra precisão técnica e fundamentação.",
        persona=personas.CRITICO,
        ve=VisaoAvaliador(gabarito=True, base_conhecimento=False, pontos_chave=True, fundamentos=True),
    ),
    AgenteAvaliador(
        id="tranquilo",
        nome="Avaliador tranquilo",
        descricao="Valoriza raciocínio e clareza; distingue lacuna de erro.",
        persona=personas.TRANQUILO,
        ve=VisaoAvaliador(gabarito=True, base_conhecimento=False, pontos_chave=True, fundamentos=False),
    ),
    AgenteAvaliador(
        id="verificador",
        nome="Verificador da base",
        descricao="Compara afirmação por afirmação com a base de conhecimento.",
        persona=personas.VERIFICADOR,
        ve=VisaoAvaliador(gabarito=True, base_conhecimento=True, pontos_chave=False, fundamentos=True),
    ),
    AgenteAvaliador(
        id="independente",
        nome="Jurista independente",
        descricao="Não vê gabarito nem base: julga só com o próprio conhecimento.",
        persona=personas.INDEPENDENTE,
        ve=VisaoAvaliador(gabarito=False, base_conhecimento=False, pontos_chave=False, fundamentos=False),
    ),
]

JUIZ_ID = "juiz"
JUIZ_NOME = "Juiz da banca"
JUIZ_PERSONA = personas.JUIZ


REGRAS_SAIDA_AVALIADOR = personas.REGRAS_SAIDA_AVALIADOR

# Personas padrão, por id. O painel pode sobrescrever cada uma (coleção `configuracoes`, chave
# `prompts`); `simulador.config_app.obter_config_prompts()` devolve o texto em vigor.
# Todos os agentes editáveis pelo painel (banca + agentes da prova).
PERSONAS_PADRAO: dict[str, str] = dict(personas.PADRAO)
REGRAS_PADRAO = REGRAS_SAIDA_AVALIADOR


def nome_agente(id: str) -> str:
    if id == JUIZ_ID:
        return JUIZ_NOME
    return next((a.nome for a in AVALIADORES if a.id == id), id)


def agente_por_id(id: str) -> AgenteAvaliador | None:
    return next((a for a in AVALIADORES if a.id == id), None)
