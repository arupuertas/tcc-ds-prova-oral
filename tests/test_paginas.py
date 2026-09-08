"""Teste de fumaça: cada página renderiza sem exceção, mesmo sem banco configurado.

Rode com `python -m pytest tests -q` (ou `python tests/test_paginas.py` para ver o relatório).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

SCRIPT = str(Path(__file__).resolve().parent / "_pagina.py")
# Banco Chroma temporário para os testes (não suja ./dados/chroma).
os.environ.setdefault("CHROMA_PATH", tempfile.mkdtemp(prefix="simulador-chroma-"))
os.environ.setdefault("CHAVES_CRIPTO_SECRET", "segredo-de-teste")
SESSAO_FAKE = "00000000-0000-0000-0000-000000000000"

CASOS: list[tuple[str, dict]] = [
    ("home", {}),
    ("concursos", {}),
    ("sala", {"concurso_id": "x"}),
    ("sala", {"concurso_id": "x", "concurso": {"id": "x", "nome": "Teste", "quantidade_perguntas": 10}}),
    ("prova", {}),
    ("prova", {"sessao_id": SESSAO_FAKE}),
    ("resultado", {"sessao_id": SESSAO_FAKE}),
    ("auth", {}),
    ("admin", {"admin_user_id": "u"}),
]


def _rodar(pagina: str, estado: dict) -> AppTest:
    os.environ["QS_PAGINA"] = pagina
    os.environ["QS_ESTADO"] = json.dumps(estado)
    at = AppTest.from_file(SCRIPT, default_timeout=120)
    at.run()
    return at


def test_paginas_renderizam_sem_excecao():
    falhas = []
    for pagina, estado in CASOS:
        at = _rodar(pagina, estado)
        if at.exception:
            falhas.append((pagina, [str(e.value)[:300] for e in at.exception]))
    assert not falhas, falhas


if __name__ == "__main__":
    for pagina, estado in CASOS:
        at = _rodar(pagina, estado)
        exc = [str(e.value)[:250] for e in at.exception]
        err = [e.value[:150] for e in at.error][:3]
        warn = [w.value[:120] for w in at.warning][:2]
        print(f"{pagina:10} exceptions={exc} errors={err} warnings={warn}")
