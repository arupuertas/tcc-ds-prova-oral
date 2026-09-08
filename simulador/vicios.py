"""Detecção de vícios de linguagem em transcrições de prova oral (puro, sem I/O)."""

from __future__ import annotations

import re

ViciosContagem = dict[str, int]

_VICIOS: list[tuple[str, list[str]]] = [
    ("né", ["né", r"né\?"]),
    ("tipo", ["tipo assim", "tipo"]),
    ("então", ["então"]),
    ("assim", ["assim"]),
    ("aí", ["aí"]),
    ("éé / hum", ["é{2,}", "e{3,}", "hum+", "ahn+", "hã+", "uhm+", "ééh"]),
    ("ok", ["ok", "okay"]),
    ("certo?", ["certo"]),
    ("entende?", ["entende", "entendeu", "sabe"]),
    ("digamos", ["digamos", "vamos dizer"]),
    ("na verdade", ["na verdade"]),
    ("basicamente", ["basicamente"]),
    ("meio que", ["meio que"]),
    ("quer dizer", ["quer dizer", "ou seja"]),
    ("cara", ["cara"]),
    ("olha", ["olha", "olhe"]),
    ("bom...", ["bom"]),
    ("pra ser sincero", ["pra ser sincero", "para ser sincero", "sinceramente"]),
]

_LETRA = r"[^\W\d_]"


def detectar_vicios(transcricao: str) -> ViciosContagem:
    texto = (transcricao or "").lower()
    if not texto.strip():
        return {}
    contagem: ViciosContagem = {}
    for rotulo, padroes in _VICIOS:
        total = 0
        for padrao in padroes:
            re_ = re.compile(rf"(?<!{_LETRA})(?:{padrao})(?!{_LETRA})", re.IGNORECASE | re.UNICODE)
            total += len(re_.findall(texto))
        if total > 0:
            contagem[rotulo] = total
    return contagem


def somar_vicios(lista: list[ViciosContagem | None]) -> ViciosContagem:
    total: ViciosContagem = {}
    for item in lista:
        for k, v in (item or {}).items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                total[k] = total.get(k, 0) + n
    return total


def ranquear_vicios(contagem: ViciosContagem) -> list[dict]:
    itens = [{"termo": k, "total": int(v)} for k, v in contagem.items() if int(v) > 0]
    return sorted(itens, key=lambda x: (-x["total"], x["termo"]))


def resumir_vicios(contagem: ViciosContagem) -> str | None:
    ranking = ranquear_vicios(contagem)
    if not ranking:
        return None
    total = sum(v["total"] for v in ranking)
    top = ", ".join(f'"{v["termo"]}" ({v["total"]}x)' for v in ranking[:3])
    if total >= 8:
        return (
            f"Foram detectados {total} vícios de linguagem na sua arguição, com destaque para {top}. "
            "Pausar em silêncio no lugar dessas muletas deixa a fala mais firme."
        )
    return (
        f"Poucos vícios de linguagem: {total} no total ({top}). "
        "Sua fala está bem controlada — mantenha a atenção nessas expressões."
    )
