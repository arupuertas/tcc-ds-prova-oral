"""Cria as coleções do Simulador de Prova Oral no ChromaDB e imprime o esquema.

Uso: `python db/inicializar.py` (lê os secrets/variáveis de ambiente para escolher o cliente:
Chroma Cloud, servidor HTTP ou pasta local `CHROMA_PATH`, padrão ./dados/chroma).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulador.db import cliente  # noqa: E402
from simulador.esquema import ESQUEMA, inicializar  # noqa: E402


def main() -> None:
    nomes = inicializar(cliente())
    print("Coleções prontas:", ", ".join(nomes))
    for c in ESQUEMA.values():
        print(f"\n[{c.nome}] {'(vetorial) ' if c.vetorial else ''}{c.descricao}")
        if c.metadados:
            print("  metadata filtrável:", ", ".join(f"{k}:{t}" for k, t in c.metadados.items()))


if __name__ == "__main__":
    main()
