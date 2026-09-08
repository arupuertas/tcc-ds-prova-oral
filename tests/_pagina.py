"""Script auxiliar do AppTest: renderiza uma página isolada com estado pré-definido.

Uso interno de `tests/test_paginas.py` (variáveis QS_PAGINA e QS_ESTADO).
"""

import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

for k, v in json.loads(os.environ.get("QS_ESTADO", "{}")).items():
    st.session_state[k] = v

importlib.import_module(f"paginas.{os.environ['QS_PAGINA']}").render()
