"""Importa o banco de questões (banco_final.json) para o ChromaDB pela linha de comando.

Uso:
  python db/importar_banco.py                      # importa (ou atualiza) as perguntas
  python db/importar_banco.py --vetorizar          # importa e indexa na base de conhecimento (precisa da OPENAI_API_KEY)
  python db/importar_banco.py --so-vetorizar       # só (re)indexa as perguntas já importadas
  python db/importar_banco.py --arquivo outro.json --nome "Outro concurso"

Idempotente: rodar de novo atualiza as perguntas pelo uid de origem, sem duplicar.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from simulador import admin  # noqa: E402
from simulador.banco_questoes import TAMANHO_LOTE_IMPORTACAO, converter_banco_questoes  # noqa: E402
from simulador.db import T, onde  # noqa: E402
from simulador.segredos import obter_segredo  # noqa: E402

ARQUIVO_PADRAO = RAIZ / "banco de questoes finais" / "banco_final.json"
NOME_PADRAO = "MP-SP — Promotor de Justiça"
DESCRICAO_PADRAO = "Banco de perguntas extraído de arguições orais reais do concurso de Promotor de Justiça do MP-SP."


def concurso_por_nome(nome: str) -> dict | None:
    return next((c for c in T("concursos").listar(onde(nome=nome))), None)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arquivo", default=str(ARQUIVO_PADRAO))
    p.add_argument("--nome", default=NOME_PADRAO, help="nome do concurso de destino (criado se não existir)")
    p.add_argument("--quantidade", type=int, default=10, help="perguntas por simulação (padrão do concurso)")
    p.add_argument("--vetorizar", action="store_true", help="indexar na base de conhecimento após importar")
    p.add_argument("--so-vetorizar", action="store_true", help="não importar; só (re)indexar o concurso")
    args = p.parse_args()

    concurso = concurso_por_nome(args.nome)
    if concurso:
        cid = concurso["id"]
        print(f"Concurso existente: {args.nome} ({cid})")
    else:
        cid, _ = admin.preparar_importacao(novo={"nome": args.nome, "descricao": DESCRICAO_PADRAO, "quantidade_perguntas": args.quantidade})
        print(f"Concurso criado: {args.nome} ({cid})")

    if not args.so_vetorizar:
        raw = json.loads(Path(args.arquivo).read_text(encoding="utf-8"))
        itens, resumo = converter_banco_questoes(raw)
        print(f"{resumo.total} perguntas lidas · {len(resumo.grupos)} grupos · {len(resumo.materias)} matérias · momentos {resumo.momentos}")
        if resumo.ignoradas:
            print(f"Ignoradas ({len(resumo.ignoradas)}):", "; ".join(f"{i['uid']} ({i['motivo']})" for i in resumo.ignoradas[:10]))
        inseridas = atualizadas = 0
        for i in range(0, len(itens), TAMANHO_LOTE_IMPORTACAO):
            r = admin.importar_lote(cid, itens[i : i + TAMANHO_LOTE_IMPORTACAO], vetorizar=False)
            inseridas += r["inseridas"]
            atualizadas += r["atualizadas"]
            print(f"  {min(len(itens), i + TAMANHO_LOTE_IMPORTACAO)}/{len(itens)}", end="\r")
        print(f"\nImportação concluída: {inseridas} novas, {atualizadas} atualizadas. Total no concurso: {T('perguntas').contar(onde(concurso_id=cid))}")

    if args.vetorizar or args.so_vetorizar:
        if not obter_segredo("OPENAI_API_KEY"):
            print("OPENAI_API_KEY não configurada: pulei a vetorização. Cadastre a chave e rode com --so-vetorizar.")
            return
        print("Vetorizando na base de conhecimento…")
        r = admin.vetorizar_concurso(cid)
        print(f"Vetorizadas {r['vetorizadas']} de {r['perguntas']} perguntas." + (f" Erros: {r['erros']}" if r["erros"] else ""))
    else:
        print("Base de conhecimento (RAG) não indexada. Quando tiver a chave da OpenAI: python db/importar_banco.py --so-vetorizar")


if __name__ == "__main__":
    main()
