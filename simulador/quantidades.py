"""Quantidades de perguntas que o candidato pode escolher para a arguição."""

QUANTIDADES_PERGUNTAS: tuple[int, ...] = (5, 10, 15, 20, 30)


def quantidade_valida(valor) -> bool:
    return isinstance(valor, int) and valor in QUANTIDADES_PERGUNTAS


def quantidade_padrao(sugerida) -> int:
    """Usa a quantidade padrão do concurso quando ela é uma das opções; senão, 10."""
    return sugerida if quantidade_valida(sugerida) else 10
