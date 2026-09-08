"""Operações do painel administrativo (estatísticas, concursos, perguntas, importação,
base de conhecimento, métricas de uso)."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict

from .banco_questoes import ItemImportacao
from .db import T, agora_iso, gabaritos, material, onde
from .ia import gerar_embeddings

NAMESPACE_PERGUNTAS = uuid.UUID("7f2b9a0c-6d1e-4c1f-9b5a-3e8e6f0a1c42")


def _nomes_concursos(ids: list[str]) -> dict[str, str]:
    return {i: c.get("nome") or "—" for i, c in T("concursos").obter_varios(ids).items()}


# ---------- estatísticas ----------


def estatisticas() -> dict:
    sessoes = T("sessoes").listar(ordenar="created_at", desc=True, limite=200)
    concursos = T("concursos").listar()
    total_perguntas = T("perguntas").contar()
    total_docs = T("documentos").contar()
    nomes = {c["id"]: c["nome"] for c in concursos}

    finalizadas = [s for s in sessoes if s["status"] == "finalizada" and s.get("nota_final") is not None]
    media = sum(float(s["nota_final"]) for s in finalizadas) / len(finalizadas) if finalizadas else None

    por_concurso: dict[str, int] = {}
    for s in sessoes:
        nome = nomes.get(s["concurso_id"], "—")
        por_concurso[nome] = por_concurso.get(nome, 0) + 1
    por_grupo: dict[int, list[float]] = {}
    for s in finalizadas:
        por_grupo.setdefault(int(s["grupo"]), []).append(float(s["nota_final"]))

    return {
        "total_simulacoes": len(sessoes),
        "total_finalizadas": len(finalizadas),
        "media_geral": round(media, 2) if media is not None else None,
        "total_concursos": len(concursos),
        "concursos_ativos": sum(1 for c in concursos if c.get("ativo")),
        "total_perguntas": total_perguntas,
        "total_documentos": total_docs,
        "por_concurso": [{"nome": n, "qtd": q} for n, q in por_concurso.items()],
        "por_grupo": sorted(({"grupo": g, "media": round(sum(v) / len(v), 2)} for g, v in por_grupo.items()), key=lambda x: x["grupo"]),
        "ultimas": [
            {
                "id": s["id"],
                "concurso": nomes.get(s["concurso_id"], "—"),
                "grupo": s["grupo"],
                "status": s["status"],
                "nota": float(s["nota_final"]) if s.get("nota_final") is not None else None,
                "criada_em": s["created_at"],
            }
            for s in sessoes[:10]
        ],
    }


# ---------- concursos ----------


def listar_concursos_admin() -> list[dict]:
    return T("concursos").listar(ordenar="created_at", desc=True)


def salvar_concurso(*, nome: str, descricao: str | None, quantidade_perguntas: int, ativo: bool, id: str | None = None) -> str:
    t = T("concursos")
    payload = {"nome": nome, "descricao": descricao or None, "quantidade_perguntas": quantidade_perguntas, "ativo": ativo, "updated_at": agora_iso()}
    if id:
        if t.atualizar(id, payload) is None:
            raise ValueError("Concurso não encontrado.")
        return id
    return t.inserir(payload)["id"]


def excluir_concurso(id: str) -> None:
    """Remove o concurso e tudo que depende dele (perguntas, sessões, respostas, documentos, trechos)."""
    for s in T("sessoes").listar(onde(concurso_id=id)):
        T("respostas").remover_onde(onde(sessao_id=s["id"]))
    T("sessoes").remover_onde(onde(concurso_id=id))
    T("perguntas").remover_onde(onde(concurso_id=id))
    gabaritos().remover_onde(onde(concurso_id=id))
    material().remover_onde(onde(concurso_id=id))
    T("documentos").remover_onde(onde(concurso_id=id))
    T("concursos").remover(id)


# ---------- perguntas ----------


def listar_perguntas(concurso_id: str | None = None) -> list[dict]:
    itens = T("perguntas").listar(onde(concurso_id=concurso_id) if concurso_id else None)
    ordem_seq = {"inicio": 0, "meio": 1, "fim": 2}
    itens.sort(key=lambda p: (int(p.get("grupo") or 0), ordem_seq.get(p.get("sequencia"), 9), int(p.get("ordem") or 0)))
    return itens


def salvar_pergunta(
    *, concurso_id: str, grupo: int, sequencia: str, pergunta: str, resposta_padrao: str, ordem: int, id: str | None = None
) -> dict:
    t = T("perguntas")
    payload = {
        "concurso_id": concurso_id,
        "grupo": grupo,
        "sequencia": sequencia,
        "pergunta": pergunta,
        "resposta_padrao": resposta_padrao,
        "ordem": ordem,
        "updated_at": agora_iso(),
    }
    if id:
        salva = t.atualizar(id, payload)
        if salva is None:
            raise ValueError("Pergunta não encontrada.")
    else:
        salva = t.inserir({**payload, "materia": None, "tema": None, "pontos_chave": [], "fundamentos_legais": [], "metadados": {}})
    # Revetoriza a pergunta/resposta salva na base de gabaritos (nunca na base de material).
    resultado = vetorizar_perguntas(concurso_id, [salva])
    return {"id": salva["id"], **resultado}


def excluir_pergunta(id: str) -> None:
    gabaritos().remover_onde(onde(pergunta_id=id))
    T("perguntas").remover(id)


def _dividir_texto(texto: str, tamanho: int = 1200, sobreposicao: int = 150) -> list[str]:
    limpo = " ".join(texto.split())
    partes = []
    inicio = 0
    while inicio < len(limpo):
        partes.append(limpo[inicio : inicio + tamanho])
        inicio += tamanho - sobreposicao
    return [p for p in partes if len(p.strip()) > 40]


def texto_do_gabarito(p: dict) -> str:
    """Texto indexado de uma pergunta: matéria, tema, enunciado e resposta padrão."""
    return "\n".join(
        x
        for x in (
            f"Matéria: {p['materia']}" if p.get("materia") else None,
            f"Tema: {p['tema']}" if p.get("tema") else None,
            f"Pergunta (grupo {p['grupo']}, ordem {p['ordem']}): {p['pergunta']}",
            f"Resposta padrão: {p['resposta_padrao']}",
        )
        if x
    )


def vetorizar_perguntas(concurso_id: str, lista: list[dict]) -> dict:
    """(Re)indexa perguntas na BASE DE GABARITOS (`gabarito_chunks`).

    Essa base é isolada da base de material e nunca é consultada durante a prova: serve à busca
    semântica do painel. Nunca lança; falhas voltam no retorno.
    """
    if not lista:
        return {"vetorizadas": 0}
    vet = gabaritos()
    try:
        pedacos: list[tuple[str, int, str]] = []
        for p in lista:
            vet.remover_onde(onde(pergunta_id=p["id"]))
            texto = texto_do_gabarito(p)
            for i, conteudo in enumerate(_dividir_texto(texto) or [texto]):
                pedacos.append((p["id"], i, conteudo))

        embeddings = gerar_embeddings([c for _, _, c in pedacos])
        vet.adicionar(
            [
                {"id": f"{pid}:{indice}", "pergunta_id": pid, "concurso_id": concurso_id, "indice": indice}
                for pid, indice, _ in pedacos
            ],
            embeddings,
            [c for _, _, c in pedacos],
        )
        return {"vetorizadas": len(lista)}
    except Exception as e:  # noqa: BLE001
        return {"vetorizadas": 0, "erro": str(e) or "Falha ao vetorizar as perguntas."}


# ---------- importação ----------


def preparar_importacao(concurso_id: str | None = None, novo: dict | None = None) -> tuple[str, str]:
    if concurso_id:
        c = T("concursos").obter(concurso_id)
        if not c:
            raise ValueError("Concurso não encontrado.")
        return c["id"], c["nome"]
    if not novo:
        raise ValueError("Informe o concurso de destino.")
    c = T("concursos").inserir(
        {
            "nome": novo["nome"],
            "descricao": novo.get("descricao") or None,
            "quantidade_perguntas": novo["quantidade_perguntas"],
            "ativo": True,
            "updated_at": agora_iso(),
        }
    )
    return c["id"], c["nome"]


def id_pergunta_importada(concurso_id: str, origem_uid: str) -> str:
    return str(uuid.uuid5(NAMESPACE_PERGUNTAS, f"{concurso_id}:{origem_uid}"))


def importar_lote(concurso_id: str, itens: list[ItemImportacao], vetorizar: bool = True) -> dict:
    """Idempotente: reimportar o mesmo arquivo atualiza as perguntas pelo `origem_uid`.
    Com `vetorizar=False` só grava as perguntas (útil sem chave da OpenAI); indexe depois com
    `vetorizar_concurso`."""
    t = T("perguntas")
    ids = [id_pergunta_importada(concurso_id, i.origem_uid) for i in itens]
    existentes = t.obter_varios(ids)
    rows = []
    for i, pid in zip(itens, ids):
        r = {"id": pid, "concurso_id": concurso_id, **asdict(i), "updated_at": agora_iso()}
        if pid in existentes:
            r["created_at"] = existentes[pid].get("created_at")
        rows.append(r)
    salvas = t.salvar_varios(rows)
    vetorizacao = vetorizar_perguntas(concurso_id, salvas) if vetorizar else {"vetorizadas": 0}
    return {
        "inseridas": sum(1 for p in salvas if p["id"] not in existentes),
        "atualizadas": sum(1 for p in salvas if p["id"] in existentes),
        "vetorizadas": vetorizacao.get("vetorizadas", 0),
        **({"erro_vetorizacao": vetorizacao["erro"]} if vetorizacao.get("erro") else {}),
    }


def vetorizar_concurso(concurso_id: str, lote: int = 25) -> dict:
    """(Re)indexa todas as perguntas de um concurso na base de conhecimento."""
    perguntas = T("perguntas").listar(onde(concurso_id=concurso_id))
    total, erros = 0, []
    for i in range(0, len(perguntas), lote):
        r = vetorizar_perguntas(concurso_id, perguntas[i : i + lote])
        total += r.get("vetorizadas", 0)
        if r.get("erro") and r["erro"] not in erros:
            erros.append(r["erro"])
    return {"perguntas": len(perguntas), "vetorizadas": total, "erros": erros}


# ---------- base de conhecimento ----------


def listar_documentos() -> list[dict]:
    docs = T("documentos").listar(ordenar="created_at", desc=True)
    nomes = _nomes_concursos([d["concurso_id"] for d in docs if d.get("concurso_id")])
    return [
        {
            "id": d["id"],
            "nome": d["nome"],
            "status": d["status"],
            "erro": d.get("erro"),
            "total_chunks": d.get("total_chunks", 0),
            "concurso_id": d.get("concurso_id"),
            "concurso": nomes.get(d.get("concurso_id") or "", "Todos os concursos"),
            "criado_em": d["created_at"],
        }
        for d in docs
    ]


def indexar_documento(nome: str, texto: str, concurso_id: str | None) -> int:
    """Indexa um arquivo de estudo na BASE DE MATERIAL (`material_chunks`), a única lida na prova."""
    docs_t, vet = T("documentos"), material()
    doc = docs_t.inserir({"nome": nome, "concurso_id": concurso_id, "status": "processando", "erro": None, "total_chunks": 0})
    try:
        partes = _dividir_texto(texto)
        if not partes:
            raise ValueError("Nenhum texto legível foi encontrado no arquivo.")
        total = 0
        for i in range(0, len(partes), 32):
            lote = partes[i : i + 32]
            embeddings = gerar_embeddings(lote)
            vet.adicionar(
                [{"id": f"{doc['id']}:{i + j}", "documento_id": doc["id"], "concurso_id": concurso_id, "indice": i + j} for j in range(len(lote))],
                embeddings,
                lote,
            )
            total += len(lote)
        doc.update({"status": "indexado", "total_chunks": total, "erro": None})
        docs_t.salvar(doc)
        return total
    except Exception as e:
        mensagem = str(e) or "Falha ao indexar o arquivo."
        doc.update({"status": "erro", "erro": mensagem})
        docs_t.salvar(doc)
        raise RuntimeError(mensagem) from e


def excluir_documento(id: str) -> None:
    material().remover_onde(onde(documento_id=id))
    T("documentos").remover(id)


# ---------- estado das duas bases ----------


def estado_das_bases(concurso_id: str | None = None) -> dict:
    """Resumo das duas bases vetoriais, para o painel mostrar que estão separadas."""
    filtro_conc = onde(concurso_id=concurso_id) if concurso_id else None
    docs = T("documentos").listar(filtro_conc)
    perguntas = T("perguntas").contar(filtro_conc) if concurso_id else T("perguntas").contar()
    vet_g = gabaritos()
    ids_g = vet_g.col.get(where=filtro_conc, include=["metadatas"]) if filtro_conc else vet_g.col.get(include=["metadatas"])
    indexadas = {m.get("pergunta_id") for m in (ids_g.get("metadatas") or []) if m.get("pergunta_id")}
    return {
        "material": {
            "documentos": len(docs),
            "indexados": sum(1 for d in docs if d.get("status") == "indexado"),
            "erros": sum(1 for d in docs if d.get("status") == "erro"),
            "trechos": len((material().col.get(where=filtro_conc, include=[]) if filtro_conc else material().col.get(include=[]))["ids"]),
        },
        "gabaritos": {
            "perguntas": perguntas,
            "indexadas": len(indexadas),
            "trechos": len(ids_g.get("ids") or []),
        },
    }


def buscar_gabaritos(texto: str, concurso_id: str | None = None, n: int = 5) -> list[str]:
    """Busca semântica na base de gabaritos. Uso exclusivo do painel, nunca da prova."""
    if not texto.strip():
        return []
    emb = gerar_embeddings([texto[:6000]])
    if not emb:
        return []
    return gabaritos().buscar(emb[0], where=onde(concurso_id=concurso_id) if concurso_id else None, n=n)


def buscar_material(texto: str, concurso_id: str | None = None, n: int = 5) -> list[str]:
    """Busca semântica na base de material: mostra no painel o que a banca enxergaria."""
    if not texto.strip():
        return []
    emb = gerar_embeddings([texto[:6000]])
    if not emb:
        return []
    filtro = {"$or": [{"concurso_id": concurso_id or ""}, {"concurso_id": ""}]} if concurso_id else None
    return material().buscar(emb[0], where=filtro, n=n)


# ---------- métricas de uso e custos ----------


def metricas_uso() -> dict:
    sessoes = T("sessoes").listar(ordenar="created_at", desc=True, limite=500)
    nomes = _nomes_concursos([s["concurso_id"] for s in sessoes])
    uso = T("api_uso").listar({"created_ts": {"$gte": time.time() - 90 * 86400}}, ordenar="created_at", desc=True, limite=20000)

    finalizadas = [s for s in sessoes if s["status"] == "finalizada" and s.get("nota_final") is not None]
    com_duracao = [s for s in sessoes if s["status"] == "finalizada" and 0 < (s.get("duracao_segundos") or 0) <= 7200]
    candidatos = {(s.get("nome_candidato") or "").strip().lower() for s in sessoes} - {""}

    por_provedor: dict[str, dict] = {}
    custo_total = 0.0
    custo_hoje = 0.0
    hoje = time.strftime("%Y-%m-%d", time.gmtime())
    for r in uso:
        custo = float(r.get("custo_usd") or 0)
        custo_total += custo
        if (r.get("created_at") or "")[:10] == hoje:
            custo_hoje += custo
        prov = por_provedor.setdefault(r["provedor"], {"custo": 0.0, "operacoes": {}})
        prov["custo"] += custo
        op = prov["operacoes"].setdefault(r["operacao"], {"quantidade": 0.0, "unidade": r["unidade"], "custo": 0.0, "chamadas": 0, "modelo": r.get("modelo")})
        op["quantidade"] += float(r.get("quantidade") or 0)
        op["custo"] += custo
        op["chamadas"] += 1

    return {
        "total_sessoes": len(sessoes),
        "total_candidatos": len(candidatos),
        "total_finalizadas": len(finalizadas),
        "media_nota": round(sum(float(s["nota_final"]) for s in finalizadas) / len(finalizadas), 2) if finalizadas else None,
        "media_duracao": round(sum(s["duracao_segundos"] for s in com_duracao) / len(com_duracao)) if com_duracao else None,
        "custo_total": custo_total,
        "custo_hoje": custo_hoje,
        "custo_por_sessao": custo_total / len(sessoes) if sessoes else 0.0,
        "provedores": sorted(
            (
                {"provedor": p, "custo": v["custo"], "operacoes": sorted(({"operacao": o, **d} for o, d in v["operacoes"].items()), key=lambda x: -x["custo"])}
                for p, v in por_provedor.items()
            ),
            key=lambda x: -x["custo"],
        ),
        "sessoes": [
            {
                "id": s["id"],
                "candidato": s.get("nome_candidato"),
                "concurso": nomes.get(s["concurso_id"], "—"),
                "grupo": s["grupo"],
                "status": s["status"],
                "nota": float(s["nota_final"]) if s.get("nota_final") is not None else None,
                "duracao": s.get("duracao_segundos"),
                "criada_em": s["created_at"],
            }
            for s in sessoes[:100]
        ],
    }


def detalhe_sessao(sessao_id: str) -> dict:
    sessao = T("sessoes").obter(sessao_id)
    if not sessao:
        raise ValueError("Simulação não encontrada.")
    respostas = T("respostas").listar(onde(sessao_id=sessao_id), ordenar="ordem")
    perguntas = T("perguntas").obter_varios([r["pergunta_id"] for r in respostas])
    uso = T("api_uso").listar(onde(sessao_id=sessao_id))
    concurso = T("concursos").obter(sessao["concurso_id"]) or {}
    return {
        "id": sessao["id"],
        "candidato": sessao.get("nome_candidato"),
        "concurso": concurso.get("nome") or "—",
        "grupo": sessao["grupo"],
        "status": sessao["status"],
        "nota": float(sessao["nota_final"]) if sessao.get("nota_final") is not None else None,
        "duracao": sessao.get("duracao_segundos"),
        "criada_em": sessao["created_at"],
        "custo": sum(float(r.get("custo_usd") or 0) for r in uso),
        "respostas": [
            {
                "ordem": r["ordem"],
                "pergunta": (perguntas.get(r["pergunta_id"]) or {}).get("pergunta", ""),
                "transcricao": r["transcricao"],
                "nota": float(r["nota"]) if r.get("nota") is not None else None,
                "justificativa": r.get("justificativa"),
                "pontos_cobertos": r.get("pontos_cobertos") or [],
                "pontos_faltantes": r.get("pontos_faltantes") or [],
            }
            for r in respostas
        ],
    }
