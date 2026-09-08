"""Separa a base de conhecimento antiga (`documento_chunks`) em duas bases isoladas.

Antes: perguntas e arquivos de estudo dividiam a mesma coleção, então o gabarito de uma pergunta
podia aparecer como "contexto" na avaliação de outra.

Depois:
- `material_chunks`  — só arquivos enviados no painel; é a única base lida durante a prova;
- `gabarito_chunks`  — só perguntas e respostas padrão; usada apenas na busca do painel.

O que o script faz:
1. cria as coleções novas;
2. move os trechos de ARQUIVOS para `material_chunks`, reaproveitando os embeddings já pagos;
3. apaga os documentos falsos `pergunta:<id>` do registro `documentos`;
4. reindexa as perguntas em `gabarito_chunks` (gera embeddings novos: exige OPENAI_API_KEY).

Uso:
  python db/migrar_bases.py            # mostra o que será feito
  python db/migrar_bases.py --aplicar  # executa
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from simulador import admin  # noqa: E402
from simulador.db import T, cliente, gabaritos, material, onde  # noqa: E402
from simulador.esquema import inicializar  # noqa: E402
from simulador.segredos import obter_segredo  # noqa: E402

ANTIGA = "documento_chunks"
LOTE = 200


def colecao_antiga():
    try:
        return cliente().get_collection(ANTIGA)
    except Exception:
        return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aplicar", action="store_true", help="executa a migração (sem isso, só mostra o diagnóstico)")
    p.add_argument("--manter-antiga", action="store_true", help="não apagar a coleção documento_chunks ao final")
    args = p.parse_args()

    inicializar(cliente())

    docs = T("documentos").listar()
    falsos = [d for d in docs if str(d.get("nome", "")).startswith("pergunta:")]
    arquivos = [d for d in docs if not str(d.get("nome", "")).startswith("pergunta:")]
    perguntas = T("perguntas").contar()
    antiga = colecao_antiga()
    total_antigo = antiga.count() if antiga else 0

    print("Diagnóstico")
    print(f"  coleção antiga {ANTIGA}: {total_antigo} trechos")
    print(f"  registros em 'documentos': {len(docs)} ({len(falsos)} de perguntas, {len(arquivos)} de arquivos)")
    print(f"  perguntas no banco: {perguntas}")
    print(f"  material_chunks agora: {material().col.count()} · gabarito_chunks agora: {gabaritos().col.count()}")
    if not args.aplicar:
        print("\nNada foi alterado. Rode de novo com --aplicar para executar.")
        return

    # 1) trechos de arquivos: movidos com os embeddings originais (não gasta API)
    movidos = 0
    if antiga and arquivos:
        ids_arquivos = {d["id"] for d in arquivos}
        res = antiga.get(include=["embeddings", "documents", "metadatas"])
        registros, embeddings, textos = [], [], []
        for i, meta in enumerate(res.get("metadatas") or []):
            doc_id = (meta or {}).get("documento_id")
            if doc_id not in ids_arquivos:
                continue
            registros.append(
                {
                    "id": res["ids"][i],
                    "documento_id": doc_id,
                    "concurso_id": (meta or {}).get("concurso_id") or "",
                    "indice": int((meta or {}).get("indice") or 0),
                }
            )
            embeddings.append(list(res["embeddings"][i]))
            textos.append((res.get("documents") or [])[i] or "")
        if registros:
            material().adicionar(registros, embeddings, textos)
            movidos = len(registros)
    print(f"\n[1] trechos de arquivos movidos para material_chunks: {movidos}")

    # 2) documentos falsos de pergunta saem do registro de material
    for d in falsos:
        T("documentos").remover(d["id"])
    print(f"[2] registros 'pergunta:<id>' removidos de 'documentos': {len(falsos)}")

    # 3) perguntas reindexadas na base de gabaritos
    if not obter_segredo("OPENAI_API_KEY"):
        print("[3] OPENAI_API_KEY ausente: pulei a reindexação dos gabaritos.")
        print("    Cadastre a chave e rode: python db/importar_banco.py --so-vetorizar")
    else:
        gabaritos().remover_onde({"indice": {"$gte": 0}})
        total = 0
        for c in T("concursos").listar():
            r = admin.vetorizar_concurso(c["id"])
            total += r["vetorizadas"]
            print(f"[3] {c['nome']}: {r['vetorizadas']} de {r['perguntas']} perguntas"
                  + (f" · erros: {'; '.join(r['erros'])}" if r["erros"] else ""))
        print(f"[3] total indexado em gabarito_chunks: {total}")

    # 4) coleção antiga
    if antiga and not args.manter_antiga:
        cliente().delete_collection(ANTIGA)
        print(f"[4] coleção {ANTIGA} removida.")
    else:
        print(f"[4] coleção {ANTIGA} mantida.")

    print("\nEstado final")
    print(f"  material_chunks: {material().col.count()} trechos ({T('documentos').contar()} arquivos)")
    print(f"  gabarito_chunks: {gabaritos().col.count()} trechos ({T('perguntas').contar()} perguntas)")


if __name__ == "__main__":
    main()
