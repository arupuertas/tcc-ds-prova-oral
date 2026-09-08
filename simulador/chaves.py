"""Catálogo das chaves de API que o painel permite cadastrar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChaveId = Literal["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"]


@dataclass(frozen=True)
class ChaveInfo:
    id: ChaveId
    nome: str
    descricao: str
    grupo: str
    secreta: bool = True
    testavel: bool = True


CHAVES: list[ChaveInfo] = [
    ChaveInfo(
        "OPENAI_API_KEY",
        "OpenAI",
        "Transcrição (Whisper), voz do avaliador (TTS), embeddings da base, visão e modelos GPT da banca.",
        "Modelos de linguagem",
    ),
    ChaveInfo(
        "ANTHROPIC_API_KEY",
        "Anthropic",
        "Modelos Claude para os avaliadores e/ou o juiz.",
        "Modelos de linguagem",
    ),
    ChaveInfo(
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "Google AI",
        "Modelos Gemini para os avaliadores e/ou o juiz.",
        "Modelos de linguagem",
    ),
]

CHAVE_IDS: list[ChaveId] = [c.id for c in CHAVES]
