"""Conversão do banco de questões (JSON exportado do pipeline de provas orais reais)
para o formato de importação do app. Puro: roda antes de enviar os lotes ao banco."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

Sequencia = str  # "inicio" | "meio" | "fim"

TAMANHO_LOTE_IMPORTACAO = 25


@dataclass
class ItemImportacao:
    origem_uid: str
    grupo: int
    ordem: int
    sequencia: Sequencia
    pergunta: str
    resposta_padrao: str
    materia: str | None = None
    tema: str | None = None
    subtema: str | None = None
    dificuldade: str | None = None
    tipo: str | None = None
    cadeia: str | None = None
    pontos_chave: list[str] = field(default_factory=list)
    fundamentos_legais: list[str] = field(default_factory=list)
    metadados: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResumoImportacao:
    total: int
    grupos: list[dict]
    materias: list[dict]
    momentos: dict[str, int]
    ignoradas: list[dict]


def _objeto(v) -> dict | None:
    return v if isinstance(v, dict) else None


def _texto(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _inteiro(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n


def _sem_acentos(v: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", v) if unicodedata.category(c) != "Mn").lower().strip()


def _sequencia(v) -> Sequencia | None:
    s = _texto(v)
    if not s:
        return None
    n = _sem_acentos(s)
    return n if n in ("inicio", "meio", "fim") else None


def _dificuldade(v) -> str | None:
    s = _texto(v)
    if not s:
        return None
    n = _sem_acentos(s)
    return n if n in ("facil", "media", "dificil") else None


def _tipo(v) -> str | None:
    s = _texto(v)
    return s if s in ("principal", "desdobramento") else None


def _lista_textos(v, max_itens: int, limite: int = 300) -> list[str]:
    if not isinstance(v, list):
        return []
    saida = []
    for item in v:
        t = _texto(item if isinstance(item, str) else (_objeto(item) or {}).get("ref"))
        if t:
            saida.append(t[:limite])
    return saida[:max_itens]


def converter_banco_questoes(raw) -> tuple[list[ItemImportacao], ResumoImportacao]:
    """Aceita o `banco_final.json` (lista) ou um objeto com a lista em `questoes`."""
    if isinstance(raw, list):
        lista = raw
    elif isinstance(raw, dict) and isinstance(raw.get("questoes"), list):
        lista = raw["questoes"]
    else:
        raise ValueError("O arquivo deve conter uma lista de perguntas (ex.: banco_final.json).")

    provas = sorted({p for p in (_texto((_objeto(q) or {}).get("prova_id")) for q in lista) if p})
    grupo_da_prova = {p: i + 1 for i, p in enumerate(provas)}

    itens: list[ItemImportacao] = []
    ignoradas: list[dict] = []
    por_grupo: dict[str, int] = {}
    por_materia: dict[str, int] = {}
    momentos = {"inicio": 0, "meio": 0, "fim": 0}

    for i, bruto in enumerate(lista):
        q = _objeto(bruto)
        uid = _texto((q or {}).get("uid")) or f"item {i + 1}"
        if not q:
            ignoradas.append({"uid": uid, "motivo": "não é um objeto"})
            continue

        prova_id = _texto(q.get("prova_id"))
        pergunta = _texto(q.get("pergunta"))
        resposta = _texto(q.get("resposta")) or _texto(q.get("resposta_padrao"))
        sequencia = _sequencia(q.get("momento") if q.get("momento") is not None else q.get("sequencia"))
        ordem = _inteiro(q.get("ordem"))
        grupo = grupo_da_prova.get(prova_id) if prova_id else _inteiro(q.get("grupo"))

        faltando = [
            n
            for n, ok in (
                ("prova_id/grupo", bool(prova_id or grupo)),
                ("pergunta", bool(pergunta)),
                ("resposta", bool(resposta)),
                ("momento", bool(sequencia)),
                ("ordem", bool(ordem)),
            )
            if not ok
        ]
        if faltando or not grupo or not pergunta or not resposta or not sequencia or not ordem:
            ignoradas.append({"uid": uid, "motivo": f"faltando {', '.join(faltando)}"})
            continue

        meta = _objeto(q.get("_meta")) or {}
        origem = _objeto(meta.get("origem")) or {}
        selecao = _objeto(q.get("_selecao")) or {}
        materia = _texto(q.get("materia"))
        ano = re.search(r"(\d{4})", prova_id or "")

        itens.append(
            ItemImportacao(
                origem_uid=uid[:120],
                grupo=grupo,
                ordem=ordem,
                sequencia=sequencia,
                pergunta=pergunta[:4000],
                resposta_padrao=resposta[:20000],
                materia=materia[:120] if materia else None,
                tema=(_texto(q.get("tema")) or "")[:200] or None,
                subtema=(_texto(meta.get("subtema")) or "")[:200] or None,
                dificuldade=_dificuldade(q.get("dificuldade")),
                tipo=_tipo(meta.get("tipo") if meta.get("tipo") is not None else q.get("tipo")),
                cadeia=(_texto(origem.get("bloco_id") if origem.get("bloco_id") is not None else q.get("cadeia")) or "")[:120]
                or None,
                pontos_chave=_lista_textos(meta.get("pontos_chave"), 30),
                fundamentos_legais=_lista_textos(meta.get("fundamentos_legais"), 30),
                # Sem dado pessoal do candidato real: transcrição da fala, colocação no concurso,
                # reação do examinador e referência ao vídeo ficam de fora de propósito, mesmo que
                # apareçam no arquivo importado. Ver `db/anonimizar_banco.py`.
                metadados={
                    "uid": uid,
                    "prova_id": prova_id,
                    "ano": int(ano.group(1)) if ano else None,
                    "confianca": meta.get("confianca") if isinstance(meta.get("confianca"), (int, float)) else None,
                    "score": selecao.get("score") if isinstance(selecao.get("score"), (int, float)) else None,
                    "revisao_necessaria": meta.get("revisao_necessaria") is True,
                },
            )
        )

        chave_grupo = prova_id or f"grupo {grupo}"
        por_grupo[chave_grupo] = por_grupo.get(chave_grupo, 0) + 1
        if materia:
            por_materia[materia] = por_materia.get(materia, 0) + 1
        momentos[sequencia] += 1

    itens.sort(key=lambda x: (x.grupo, x.ordem))

    grupos = sorted(
        (
            {
                "grupo": grupo_da_prova.get(p, int(re.sub(r"\D", "", p) or 0)),
                "provaId": p,
                "perguntas": n,
            }
            for p, n in por_grupo.items()
        ),
        key=lambda g: g["grupo"],
    )
    materias = sorted(({"nome": n, "total": t} for n, t in por_materia.items()), key=lambda m: -m["total"])

    return itens, ResumoImportacao(len(itens), grupos, materias, momentos, ignoradas)
