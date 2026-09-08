"""Catálogo de modelos de linguagem que a banca pode usar.

Preços em US$ por 1 milhão de tokens — estimativas para a aba Custos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .chaves import ChaveId

ProvedorLlm = Literal["openai", "anthropic", "google"]


@dataclass(frozen=True)
class ModeloLlm:
    id: str  # `provedor:modelo`
    provedor: ProvedorLlm
    modelo: str
    nome: str
    descricao: str
    preco_entrada: float
    preco_saida: float


PROVEDORES_LLM: dict[str, dict[str, str]] = {
    "openai": {"nome": "OpenAI", "chave": "OPENAI_API_KEY"},
    "anthropic": {"nome": "Anthropic", "chave": "ANTHROPIC_API_KEY"},
    "google": {"nome": "Google", "chave": "GOOGLE_GENERATIVE_AI_API_KEY"},
}


def _m(provedor: ProvedorLlm, modelo: str, nome: str, descricao: str, pe: float, ps: float) -> ModeloLlm:
    return ModeloLlm(f"{provedor}:{modelo}", provedor, modelo, nome, descricao, pe, ps)


MODELOS: list[ModeloLlm] = [
    _m("openai", "gpt-4o-mini", "GPT-4o mini", "Rápido e barato; bom para os avaliadores.", 0.15, 0.6),
    _m("openai", "gpt-4o", "GPT-4o", "Equilíbrio entre qualidade e custo.", 2.5, 10),
    _m("openai", "gpt-4.1-mini", "GPT-4.1 mini", "Sucessor do 4o mini, mais preciso.", 0.4, 1.6),
    _m("openai", "gpt-4.1", "GPT-4.1", "Forte em instruções longas.", 2, 8),
    _m("openai", "gpt-5-mini", "GPT-5 mini", "Raciocínio bom a baixo custo.", 0.25, 2),
    _m("openai", "gpt-5", "GPT-5", "Raciocínio forte; ótimo para o juiz.", 1.25, 10),
    _m("anthropic", "claude-haiku-4-5", "Claude Haiku 4.5", "Rápido e barato.", 1, 5),
    _m("anthropic", "claude-sonnet-5", "Claude Sonnet 5", "Excelente custo-benefício.", 2, 10),
    _m("anthropic", "claude-opus-5", "Claude Opus 5", "Máxima qualidade de raciocínio.", 5, 25),
    _m("google", "gemini-2.5-flash", "Gemini 2.5 Flash", "Rápido e barato.", 0.3, 2.5),
    _m("google", "gemini-2.5-pro", "Gemini 2.5 Pro", "Raciocínio forte.", 1.25, 10),
]

MODELO_PADRAO_AVALIADORES = "openai:gpt-4o-mini"
MODELO_PADRAO_JUIZ = "openai:gpt-4o"
# Agentes da prova: precisa enxergar imagem (leitor de postura).
MODELO_PADRAO_AUXILIAR = "openai:gpt-4o"


def separar_modelo(id: str) -> tuple[ProvedorLlm, str] | None:
    """Aceita `provedor:modelo` (inclusive IDs fora do catálogo)."""
    if not isinstance(id, str):
        return None
    i = id.find(":")
    if i <= 0:
        return None
    provedor, modelo = id[:i], id[i + 1 :].strip()
    if provedor in PROVEDORES_LLM and modelo:
        return provedor, modelo  # type: ignore[return-value]
    return None


def buscar_modelo(id: str) -> ModeloLlm | None:
    return next((m for m in MODELOS if m.id == id), None)


def nome_modelo(id: str) -> str:
    m = buscar_modelo(id)
    if m:
        return m.nome
    partes = separar_modelo(id)
    return partes[1] if partes else id


def chave_do_provedor(provedor: str) -> ChaveId:
    return PROVEDORES_LLM[provedor]["chave"]  # type: ignore[return-value]
