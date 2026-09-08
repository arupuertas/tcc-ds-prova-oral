"""Formatos de avaliador e vozes disponíveis para o candidato/admin."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Formato:
    id: str
    nome: str
    descricao: str


FORMATOS: list[Formato] = [
    Formato("foto", "Foto estática de um juiz", "Retrato fixo do avaliador com a voz da banca. Leve e estável em qualquer máquina."),
    Formato("bola", "Bola falante", "Esfera animada que pulsa com a voz, no estilo do assistente do ChatGPT."),
    Formato("video", "Juiz em vídeo", "Clipes reais do avaliador ouvindo e falando, com a voz da banca."),
]


def formato_valido(valor: str | None) -> str | None:
    return valor if any(f.id == valor for f in FORMATOS) else None


@dataclass(frozen=True)
class Voz:
    id: str
    nome: str
    descricao: str
    foto: str  # arquivo em assets/vozes


VOZES: list[Voz] = [
    Voz("onyx", "Onyx", "Masculina, grave e institucional.", "vozes/onyx.jpg"),
    Voz("echo", "Echo", "Masculina, clara e objetiva.", "vozes/echo.jpg"),
    Voz("fable", "Fable", "Masculina, tom mais narrativo.", "vozes/fable.jpg"),
    Voz("alloy", "Alloy", "Neutra, ritmo equilibrado.", "vozes/alloy.jpg"),
    Voz("nova", "Nova", "Feminina, firme e articulada.", "vozes/nova.jpg"),
    Voz("shimmer", "Shimmer", "Feminina, tom mais suave.", "vozes/shimmer.jpg"),
]

FRASE_TESTE = "Bom dia. Sou o avaliador desta banca. Vamos iniciar a sua arguição oral."
