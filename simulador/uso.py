"""Registro do consumo de cada API externa (coleção `api_uso`)."""

from __future__ import annotations

from .db import T


def registrar_uso(
    *,
    provedor: str,
    operacao: str,
    unidade: str,
    quantidade: float,
    custo_usd: float,
    modelo: str | None = None,
    tokens_entrada: int = 0,
    tokens_saida: int = 0,
    sessao_id: str | None = None,
) -> None:
    """Nunca quebra o fluxo do usuário: falhas de telemetria só são logadas."""
    try:
        T("api_uso").inserir(
            {
                "sessao_id": sessao_id,
                "provedor": provedor,
                "operacao": operacao,
                "modelo": modelo,
                "unidade": unidade,
                "quantidade": quantidade,
                "tokens_entrada": tokens_entrada,
                "tokens_saida": tokens_saida,
                "custo_usd": round(custo_usd, 6),
            }
        )
    except Exception as e:
        print(f"[uso] falha ao registrar uso de API: {e}")
