"""Camada de acesso ao ChromaDB.

Cliente (escolhido pelos secrets):
- `CHROMA_API_KEY` + `CHROMA_TENANT` + `CHROMA_DATABASE` → Chroma Cloud (recomendado no Streamlit Cloud,
  cujo disco é efêmero);
- `CHROMA_HOST` (+ `CHROMA_PORT`, `CHROMA_SSL`) → servidor Chroma próprio;
- senão → `PersistentClient` local em `CHROMA_PATH` (padrão `./dados/chroma`).

`Tabela` trata uma coleção como uma tabela de registros JSON com filtros por metadata;
`Vetores` é uma coleção de embeddings reais. São duas, isoladas de propósito: `material()`
(arquivos de estudo, lida na prova) e `gabaritos()` (perguntas e respostas padrão, nunca lida
na prova). Manter a separação é o que impede o gabarito de uma pergunta vazar na avaliação de outra.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import chromadb

from .config import segredo_ambiente
from .esquema import DIMENSAO_REGISTRO, ESQUEMA, Colecao, configuracao_colecao

Registro = dict[str, Any]
Where = dict[str, Any]

_EMBED_REGISTRO = [1.0] * DIMENSAO_REGISTRO


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def para_ts(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def novo_id() -> str:
    return str(uuid.uuid4())


@lru_cache(maxsize=1)
def cliente():
    api_key = segredo_ambiente("CHROMA_API_KEY")
    if api_key:
        return chromadb.CloudClient(
            tenant=segredo_ambiente("CHROMA_TENANT"),
            database=segredo_ambiente("CHROMA_DATABASE") or "simulador",
            api_key=api_key,
        )
    host = segredo_ambiente("CHROMA_HOST")
    if host:
        return chromadb.HttpClient(
            host=host,
            port=int(segredo_ambiente("CHROMA_PORT") or 8000),
            ssl=(segredo_ambiente("CHROMA_SSL") or "false").lower() == "true",
            headers={"X-Chroma-Token": t} if (t := segredo_ambiente("CHROMA_TOKEN")) else None,
        )
    return chromadb.PersistentClient(path=segredo_ambiente("CHROMA_PATH") or "./dados/chroma")


def onde_esta_o_banco() -> tuple[str, str, bool]:
    """(tipo, descrição, os dados sobrevivem a um reinício?).

    No Streamlit Community Cloud o disco é apagado a cada reinício: sem Chroma Cloud ou servidor
    próprio, o banco local se perde junto com concursos, perguntas e resultados.
    """
    if segredo_ambiente("CHROMA_API_KEY"):
        base = segredo_ambiente("CHROMA_DATABASE") or "simulador"
        return "cloud", f"Chroma Cloud · base {base}", True
    if host := segredo_ambiente("CHROMA_HOST"):
        return "servidor", f"Servidor Chroma em {host}", True
    caminho = segredo_ambiente("CHROMA_PATH") or "./dados/chroma"
    return "local", f"Pasta local {caminho}", False


def onde(*condicoes: Where | None, **iguais) -> Where | None:
    """Monta um filtro Chroma: igualdades por kwargs e/ou condições prontas, combinadas com $and."""
    partes: list[Where] = [c for c in condicoes if c]
    for k, v in iguais.items():
        partes.append({k: "" if v is None else v})
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else {"$and": partes}


class Tabela:
    """Coleção de registros JSON (document) com metadata filtrável definida no esquema."""

    def __init__(self, nome: str):
        self.definicao: Colecao = ESQUEMA[nome]
        self._col = None

    @property
    def col(self):
        if self._col is None:
            self._col = cliente().get_or_create_collection(self.definicao.nome, configuration=configuracao_colecao(self.definicao))
        return self._col

    # ---------- conversões ----------

    def _metadata(self, registro: Registro) -> dict:
        meta: dict = {}
        for campo, tipo in self.definicao.metadados.items():
            if campo.endswith("_ts") and campo not in registro:
                valor = para_ts(registro.get(campo[:-3] if campo[:-3] in registro else campo.replace("_ts", "_at")))
            else:
                valor = registro.get(campo)
            if valor is None:
                if tipo == "str":
                    meta[campo] = ""
                continue
            if tipo == "str":
                meta[campo] = str(valor)
            elif tipo == "int":
                meta[campo] = int(valor)
            elif tipo == "float":
                meta[campo] = float(valor)
            elif tipo == "bool":
                meta[campo] = bool(valor)
        if not meta:
            meta["_"] = 1  # o Chroma exige metadata não vazia quando informada
        return meta

    @staticmethod
    def _documento(registro: Registro) -> str:
        return json.dumps(registro, ensure_ascii=False, default=str)

    @staticmethod
    def _registro(documento: str | None) -> Registro:
        return json.loads(documento) if documento else {}

    # ---------- escrita ----------

    def inserir(self, registro: Registro, id: str | None = None) -> Registro:
        r = dict(registro)
        r["id"] = id or r.get("id") or novo_id()
        r.setdefault("created_at", agora_iso())
        self.col.add(ids=[r["id"]], embeddings=[_EMBED_REGISTRO], documents=[self._documento(r)], metadatas=[self._metadata(r)])
        return r

    def salvar(self, registro: Registro) -> Registro:
        """Upsert pelo id (cria ou substitui o registro inteiro)."""
        r = dict(registro)
        if not r.get("id"):
            raise ValueError("Registro sem id.")
        r.setdefault("created_at", agora_iso())
        self.col.upsert(ids=[r["id"]], embeddings=[_EMBED_REGISTRO], documents=[self._documento(r)], metadatas=[self._metadata(r)])
        return r

    def salvar_varios(self, registros: list[Registro]) -> list[Registro]:
        if not registros:
            return []
        rs = []
        for reg in registros:
            r = dict(reg)
            r["id"] = r.get("id") or novo_id()
            r.setdefault("created_at", agora_iso())
            rs.append(r)
        for i in range(0, len(rs), 500):
            lote = rs[i : i + 500]
            self.col.upsert(
                ids=[r["id"] for r in lote],
                embeddings=[_EMBED_REGISTRO] * len(lote),
                documents=[self._documento(r) for r in lote],
                metadatas=[self._metadata(r) for r in lote],
            )
        return rs

    def atualizar(self, id: str, campos: Registro) -> Registro | None:
        atual = self.obter(id)
        if atual is None:
            return None
        atual.update(campos)
        return self.salvar(atual)

    def atualizar_onde(self, where: Where | None, campos: Registro) -> int:
        itens = self.listar(where)
        for r in itens:
            r.update(campos)
        self.salvar_varios(itens)
        return len(itens)

    def remover(self, ids: list[str] | str) -> None:
        ids = [ids] if isinstance(ids, str) else list(ids)
        if ids:
            self.col.delete(ids=ids)

    def remover_onde(self, where: Where | None) -> None:
        if where is None:
            ids = self.col.get(include=[])["ids"]
            if ids:
                self.col.delete(ids=ids)
        else:
            self.col.delete(where=where)

    # ---------- leitura ----------

    def obter(self, id: str) -> Registro | None:
        res = self.col.get(ids=[id], include=["documents"])
        docs = res.get("documents") or []
        return self._registro(docs[0]) if docs else None

    def obter_varios(self, ids: list[str]) -> dict[str, Registro]:
        ids = [i for i in dict.fromkeys(ids) if i]
        if not ids:
            return {}
        saida: dict[str, Registro] = {}
        for i in range(0, len(ids), 500):
            res = self.col.get(ids=ids[i : i + 500], include=["documents"])
            for doc in res.get("documents") or []:
                r = self._registro(doc)
                saida[r["id"]] = r
        return saida

    def listar(self, where: Where | None = None, *, ordenar: str | None = None, desc: bool = False, limite: int | None = None) -> list[Registro]:
        res = self.col.get(where=where, include=["documents"]) if where else self.col.get(include=["documents"])
        itens = [self._registro(d) for d in (res.get("documents") or [])]
        if ordenar:
            itens.sort(key=lambda r: (r.get(ordenar) is None, r.get(ordenar) if r.get(ordenar) is not None else ""), reverse=desc)
        return itens[:limite] if limite else itens

    def contar(self, where: Where | None = None) -> int:
        if where is None:
            return self.col.count()
        return len(self.col.get(where=where, include=[])["ids"])


class Vetores(Tabela):
    """Coleção com embeddings reais (base de conhecimento)."""

    def adicionar(self, registros: list[Registro], embeddings: list[list[float]], textos: list[str]) -> None:
        if not registros:
            return
        for i in range(0, len(registros), 200):
            fatia = slice(i, i + 200)
            self.col.upsert(
                ids=[r["id"] for r in registros[fatia]],
                embeddings=embeddings[fatia],
                documents=textos[fatia],
                metadatas=[self._metadata(r) for r in registros[fatia]],
            )

    def buscar(self, embedding: list[float], where: Where | None = None, n: int = 5) -> list[str]:
        """Trechos mais próximos (distância cosseno)."""
        if self.col.count() == 0:
            return []
        n = max(1, min(n, self.col.count()))
        kwargs = {"query_embeddings": [embedding], "n_results": n, "include": ["documents"]}
        if where:
            kwargs["where"] = where
        res = self.col.query(**kwargs)
        docs = res.get("documents") or [[]]
        return list(docs[0])


def T(nome: str) -> Tabela:
    return Tabela(nome)


def material() -> Vetores:
    """BASE 1 — material de estudo enviado no painel. É a única base lida durante a prova."""
    return Vetores("material_chunks")


def gabaritos() -> Vetores:
    """BASE 2 — perguntas e respostas padrão. Nunca é lida durante a prova."""
    return Vetores("gabarito_chunks")
