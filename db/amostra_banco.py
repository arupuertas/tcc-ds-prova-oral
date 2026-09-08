"""Gera uma amostra menor do banco de questões, sem tocar no arquivo original.

A amostra não é um sorteio solto: ela precisa continuar rodando uma prova de verdade. O simulador
sorteia um **grupo** (uma prova real) e monta a arguição na ordem início → meio → fim, respeitando
as cadeias (pergunta principal + desdobramentos). Por isso a amostra:

- escolhe provas inteiras, em vez de espalhar poucas questões por todas as 10;
- dentro de cada prova, mantém a proporção início/meio/fim do original;
- nunca parte uma cadeia ao meio: ou leva o encadeamento todo, ou não leva nenhum.

Assim uma prova de 10 perguntas na amostra sai igual à do banco completo.

Uso:
  python db/amostra_banco.py                          # 4 provas x 10 questões = 40
  python db/amostra_banco.py --questoes 60 --provas 6
  python db/amostra_banco.py --saida outro.json --semente 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "banco de questoes finais"
ORIGEM = PASTA / "banco_final.json"
SAIDA = PASTA / "banco_amostra.json"
MOMENTOS = ("inicio", "meio", "fim")


def cadeia_de(q: dict) -> str:
    """Identificador do encadeamento; sem ele, a questão é uma cadeia de um item só."""
    selecao = q.get("_selecao") or {}
    origem = (q.get("_meta") or {}).get("origem") or {}
    return str(selecao.get("bloco_origem") or origem.get("bloco_id") or q.get("uid") or id(q))


def cotas(total: int, disponivel: dict[str, int]) -> dict[str, int]:
    """Divide o total em ~25/50/25, devolvendo o que não couber para os outros momentos."""
    c = {"inicio": max(1, round(total * 0.25)), "fim": max(1, round(total * 0.25))}
    c["meio"] = max(0, total - c["inicio"] - c["fim"])
    sobra = 0
    for m in MOMENTOS:
        if c[m] > disponivel.get(m, 0):
            sobra += c[m] - disponivel[m]
            c[m] = disponivel.get(m, 0)
    for m in ("meio", "fim", "inicio"):
        if sobra <= 0:
            break
        livre = disponivel.get(m, 0) - c[m]
        usa = min(livre, sobra)
        c[m] += usa
        sobra -= usa
    return c


def amostra_da_prova(questoes: list[dict], alvo: int, rnd: random.Random) -> list[dict]:
    por_momento: dict[str, list[dict]] = defaultdict(list)
    for q in questoes:
        por_momento[q.get("momento", "meio")].append(q)

    escolhidas: list[dict] = []
    cota = cotas(alvo, {m: len(v) for m, v in por_momento.items()})
    for momento in MOMENTOS:
        itens = por_momento.get(momento, [])
        if not itens or cota[momento] <= 0:
            continue
        cadeias: dict[str, list[dict]] = defaultdict(list)
        for q in itens:
            cadeias[cadeia_de(q)].append(q)
        ordem = sorted(cadeias.values(), key=lambda c: min(x.get("ordem", 0) for x in c))
        rnd.shuffle(ordem)
        pegos: list[dict] = []
        sobraram: list[list[dict]] = []
        for grupo in ordem:
            if len(pegos) + len(grupo) > cota[momento]:
                sobraram.append(grupo)
                continue  # cadeia não cabe inteira: guarda para o desempate
            pegos.extend(grupo)
            if len(pegos) == cota[momento]:
                break
        # Último recurso: completa a cota com o começo de uma cadeia que não coube inteira.
        # Sempre a partir da pergunta principal, para nunca sobrar um desdobramento órfão.
        for grupo in sobraram:
            if len(pegos) >= cota[momento]:
                break
            falta = cota[momento] - len(pegos)
            pegos.extend(sorted(grupo, key=lambda q: q.get("ordem", 0))[:falta])
        escolhidas.extend(pegos)
    escolhidas.sort(key=lambda q: q.get("ordem", 0))
    return escolhidas


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--questoes", type=int, default=40, help="tamanho da amostra (padrão 40)")
    p.add_argument("--provas", type=int, default=4, help="quantas provas inteiras entram (padrão 4)")
    p.add_argument("--origem", default=str(ORIGEM))
    p.add_argument("--saida", default=str(SAIDA))
    p.add_argument("--semente", type=int, default=42, help="deixa a amostra reproduzível")
    args = p.parse_args()

    itens = json.loads(Path(args.origem).read_text(encoding="utf-8"))
    if not isinstance(itens, list):
        sys.exit("Esperava uma lista de questões no arquivo de origem.")

    por_prova: dict[str, list[dict]] = defaultdict(list)
    for q in itens:
        por_prova[q.get("prova_id", "sem_prova")].append(q)

    rnd = random.Random(args.semente)
    # Provas maiores primeiro: sobra folga para respeitar as cadeias sem cortar.
    candidatas = sorted(por_prova.items(), key=lambda kv: -len(kv[1]))[: max(1, args.provas)]
    por_prova_alvo = max(1, args.questoes // len(candidatas))

    # Reparte o total entre as provas; o resto vai para as primeiras, uma questão cada.
    alvos = {pid: por_prova_alvo for pid, _ in candidatas}
    for i in range(args.questoes - por_prova_alvo * len(candidatas)):
        alvos[candidatas[i % len(candidatas)][0]] += 1

    amostra: list[dict] = []
    for prova_id, questoes in candidatas:
        amostra.extend(amostra_da_prova(questoes, min(alvos[prova_id], len(questoes)), rnd))

    amostra.sort(key=lambda q: (q.get("prova_id", ""), q.get("ordem", 0)))
    Path(args.saida).write_text(json.dumps(amostra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    provas = Counter(q["prova_id"] for q in amostra)
    momentos = Counter(q.get("momento") for q in amostra)
    materias = {q.get("materia") for q in amostra if q.get("materia")}
    print(f"Amostra gravada em {args.saida}")
    print(f"  {len(amostra)} questões · {len(provas)} grupos · {len(materias)} matérias")
    print(f"  momentos: {dict(momentos)}")
    for prova_id, n in sorted(provas.items()):
        m = Counter(q.get("momento") for q in amostra if q["prova_id"] == prova_id)
        print(f"    {prova_id}: {n} questões {dict(m)}")
    print(f"\nO original segue intacto em {args.origem} ({len(itens)} questões).")
    print(f"Para importar só a amostra: python db/importar_banco.py --arquivo \"{args.saida}\" --nome \"MP-SP — amostra\"")


if __name__ == "__main__":
    main()
