"""Motor da simulação: sorteio de grupo, sequência das perguntas, turno conversacional,
avaliação pela banca e resultado."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .agentes import analisar_postura, avaliar_com_banca, interpretar_turno
from .banca import Dossie
from .db import T, agora_iso, material, onde
from .ia import IntegracaoError, gerar_embeddings
from .limites import autorizar_nova_sessao, hash_da_origem, registrar_sinal
from .vicios import detectar_vicios, ranquear_vicios, resumir_vicios, somar_vicios

MOMENTOS = ("inicio", "meio", "fim")


@dataclass
class PerguntaAtual:
    id: str
    texto: str
    ordem: int
    materia: str | None
    tema: str | None


@dataclass
class EstadoSessao:
    sessao_id: str
    concurso_nome: str
    grupo: int
    indice: int
    total: int
    status: str
    pergunta_atual: PerguntaAtual | None
    nota_final: float | None
    resumo: str | None
    postura_resumo: str | None
    vicios_resumo: str | None
    vicios: list[dict] = field(default_factory=list)


@dataclass
class RetornoResposta:
    estado: EstadoSessao
    fala: str | None  # fala conversacional (repetição/reformulação/comentário)
    transicao_fala: str | None  # fala curta antes da próxima pergunta (ex.: pulou)


# ---------- sequência ----------


def _tomar_cadeias(lista: list[dict], n: int) -> list[dict]:
    """Toma perguntas de um momento em cadeias inteiras, na ordem em que aparecem.
    A última cadeia pode ser truncada no fim (nunca no início)."""
    cadeias: list[list[dict]] = []
    for p in lista:
        ultima = cadeias[-1] if cadeias else None
        if ultima and p.get("cadeia") and ultima[0].get("cadeia") == p.get("cadeia"):
            ultima.append(p)
        else:
            cadeias.append([p])
    escolhidas: list[dict] = []
    for cadeia in cadeias:
        if len(escolhidas) >= n:
            break
        escolhidas.extend(cadeia[: n - len(escolhidas)])
    return escolhidas


def montar_sequencia(perguntas: list[dict], total: int) -> list[dict]:
    """Início, depois meio, depois fim (~25/50/25), respeitando as cadeias de cada momento.
    Se um momento não tiver perguntas suficientes, o excedente vai para os outros."""
    por_seq: dict[str, list[dict]] = {m: [] for m in MOMENTOS}
    for p in perguntas:
        if p.get("sequencia") in por_seq:
            por_seq[p["sequencia"]].append(p)
    for m in MOMENTOS:
        por_seq[m].sort(key=lambda p: p.get("ordem", 0))

    alvo = min(max(0, int(total)), len(perguntas))
    if alvo == 0:
        return []

    cota = {
        "inicio": max(1, round(alvo * 0.25)) if alvo >= 3 else 1,
        "fim": (max(1, round(alvo * 0.25)) if alvo >= 3 else (1 if alvo > 1 else 0)),
        "meio": 0,
    }
    cota["meio"] = max(0, alvo - cota["inicio"] - cota["fim"])

    excedente = 0
    for m in MOMENTOS:
        disponivel = len(por_seq[m])
        if cota[m] > disponivel:
            excedente += cota[m] - disponivel
            cota[m] = disponivel
    for m in ("meio", "fim", "inicio"):
        if excedente <= 0:
            break
        livre = len(por_seq[m]) - cota[m]
        extra = min(livre, excedente)
        cota[m] += extra
        excedente -= extra

    saida: list[dict] = []
    for m in MOMENTOS:
        saida.extend(_tomar_cadeias(por_seq[m], cota[m]))
    return saida[:alvo]


# ---------- concursos e sessão ----------


def listar_concursos_publicos() -> list[dict]:
    return [
        {k: c.get(k) for k in ("id", "nome", "descricao", "quantidade_perguntas")}
        for c in T("concursos").listar(onde(ativo=True), ordenar="nome")
    ]


def iniciar_simulacao(concurso_id: str, nome_candidato: str | None, quantidade: int | None, ip: str | None) -> str:
    ip_hash = hash_da_origem(ip)
    autorizar_nova_sessao(ip_hash)

    concurso = T("concursos").obter(concurso_id)
    if not concurso or not concurso.get("ativo"):
        raise ValueError("Concurso não encontrado ou inativo.")

    perguntas = T("perguntas").listar(onde(concurso_id=concurso_id))
    if not perguntas:
        raise ValueError("Este concurso ainda não possui perguntas cadastradas.")

    grupos = sorted({int(p["grupo"]) for p in perguntas})
    grupo = random.choice(grupos)
    do_grupo = [p for p in perguntas if int(p["grupo"]) == grupo]
    total = quantidade if quantidade and quantidade > 0 else int(concurso.get("quantidade_perguntas") or 10)
    sequencia = montar_sequencia(do_grupo, total)
    if not sequencia:
        raise ValueError("Não há perguntas suficientes no grupo sorteado.")

    sessao = T("sessoes").inserir(
        {
            "concurso_id": concurso_id,
            "nome_candidato": (nome_candidato or "").strip() or None,
            "grupo": grupo,
            "quantidade_perguntas": len(sequencia),
            "pergunta_ids": [p["id"] for p in sequencia],
            "indice_atual": 0,
            "status": "em_andamento",
            "nota_final": None,
            "resumo": None,
            "postura_resumo": None,
            "vicios_resumo": {},
            "duracao_segundos": None,
            "ip_hash": ip_hash,
            "ultimo_sinal": agora_iso(),
            "finalizada_em": None,
        }
    )
    return sessao["id"]


def obter_estado(sessao_id: str) -> EstadoSessao:
    sessao = T("sessoes").obter(sessao_id)
    if not sessao:
        raise ValueError("Simulação não encontrada.")

    ids: list[str] = sessao.get("pergunta_ids") or []
    indice = int(sessao.get("indice_atual") or 0)
    pergunta_atual = None
    if sessao["status"] == "em_andamento" and indice < len(ids):
        p = T("perguntas").obter(ids[indice])
        if p:
            pergunta_atual = PerguntaAtual(id=p["id"], texto=p["pergunta"], ordem=indice + 1, materia=p.get("materia"), tema=p.get("tema"))

    concurso = T("concursos").obter(sessao["concurso_id"]) or {}
    vicios_resumo = sessao.get("vicios_resumo") if isinstance(sessao.get("vicios_resumo"), dict) else {}
    return EstadoSessao(
        sessao_id=sessao["id"],
        concurso_nome=concurso.get("nome") or "Concurso",
        grupo=int(sessao["grupo"]),
        indice=indice,
        total=int(sessao["quantidade_perguntas"]),
        status=sessao["status"],
        pergunta_atual=pergunta_atual,
        nota_final=float(sessao["nota_final"]) if sessao.get("nota_final") is not None else None,
        resumo=sessao.get("resumo"),
        postura_resumo=sessao.get("postura_resumo"),
        vicios_resumo=vicios_resumo.get("texto"),
        vicios=ranquear_vicios(vicios_resumo.get("contagem") or {}),
    )


# ---------- resposta ----------


def _contexto_relevante(pergunta: str, transcricao: str, concurso_id: str, sessao_id: str) -> list[str]:
    """Trechos do material de estudo que a banca pode ver.

    Lê SÓ a base de material (`material()`). A base de gabaritos fica de fora de propósito: se
    entrasse aqui, a resposta padrão de uma pergunta apareceria como 'contexto' na avaliação de
    outra, entregando o gabarito ao avaliador que não deveria vê-lo.
    """
    try:
        embeddings = gerar_embeddings([f"{pergunta}\n{transcricao}"[:6000]], sessao_id)
        if not embeddings:
            return []
        # Trechos do concurso ou válidos para todos (concurso_id vazio).
        return material().buscar(embeddings[0], where={"$or": [{"concurso_id": concurso_id}, {"concurso_id": ""}]}, n=5)
    except IntegracaoError:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[simulacao] falha ao buscar contexto: {e}")
        return []


def responder(sessao_id: str, transcricao: str, quadros: list[bytes] | None = None) -> RetornoResposta:
    quadros = quadros or []
    sessoes = T("sessoes")
    sessao = sessoes.obter(sessao_id)
    if not sessao:
        raise ValueError("Simulação não encontrada.")
    if sessao["status"] != "em_andamento":
        return RetornoResposta(obter_estado(sessao_id), None, None)

    registrar_sinal(sessao_id)

    ids: list[str] = sessao.get("pergunta_ids") or []
    indice = int(sessao.get("indice_atual") or 0)
    if indice >= len(ids):
        raise ValueError("Não há pergunta pendente nesta simulação.")

    pergunta = T("perguntas").obter(ids[indice])
    if not pergunta:
        raise ValueError("Pergunta não encontrada.")

    # Turno conversacional: pedidos de repetição/reformulação não são avaliados.
    turno = interpretar_turno(pergunta["pergunta"], transcricao, sessao_id)
    pulou = turno.intencao == "pular"
    if turno.intencao != "resposta" and not pulou:
        fala = turno.fala or (
            f"Sem problema, vou perguntar de outra forma. {pergunta['pergunta']}"
            if turno.intencao == "reformular"
            else f"Claro, vou repetir. {pergunta['pergunta']}"
        )
        return RetornoResposta(obter_estado(sessao_id), fala, None)

    transicao_fala = (turno.fala or "Sem problema, vamos seguir para a próxima pergunta.") if pulou else None

    veredito = ata = None
    if not pulou:
        contexto = _contexto_relevante(pergunta["pergunta"], transcricao, sessao["concurso_id"], sessao_id)
        veredito, ata = avaliar_com_banca(
            Dossie(
                pergunta=pergunta["pergunta"],
                resposta_padrao=pergunta["resposta_padrao"],
                transcricao=transcricao,
                contexto=contexto,
                pontos_chave=pergunta.get("pontos_chave") or [],
                fundamentos_legais=pergunta.get("fundamentos_legais") or [],
                materia=pergunta.get("materia"),
                tema=pergunta.get("tema"),
                sessao_id=sessao_id,
            )
        )

    postura = None
    try:
        postura = analisar_postura(pergunta["pergunta"], transcricao, quadros, sessao_id)
    except Exception as e:  # noqa: BLE001 — a postura nunca bloqueia a nota
        print(f"[simulacao] falha ao analisar a postura: {e}")

    # Uma resposta por (sessão, ordem): um envio repetido não cria resposta duplicada.
    respostas = T("respostas")
    id_resposta = f"{sessao_id}:{indice + 1}"
    if respostas.obter(id_resposta) is None:
        respostas.inserir(
            {
                "sessao_id": sessao_id,
                "pergunta_id": pergunta["id"],
                "ordem": indice + 1,
                "transcricao": transcricao,
                "nota": veredito.nota if veredito else 0,
                "justificativa": veredito.justificativa
                if veredito
                else "O candidato não respondeu ao mérito da pergunta (pediu para pular, disse não saber ou não abordou o assunto).",
                "pontos_cobertos": veredito.pontos_cobertos if veredito else [],
                "pontos_faltantes": veredito.pontos_faltantes if veredito else (pergunta.get("pontos_chave") or []),
                "pareceres": ata.para_json() if ata else {},
                "nervosismo": postura.nervosismo if postura else None,
                "confianca": postura.confianca if postura else None,
                "lendo": postura.lendo if postura else None,
                "postura_observacao": (postura.observacao or None) if postura else None,
                "vicios": detectar_vicios(transcricao),
            },
            id=id_resposta,
        )

    proximo = indice + 1
    terminou = proximo >= len(ids)

    # Avanço condicionado ao índice lido: dois envios concorrentes não pulam pergunta.
    atual = sessoes.obter(sessao_id) or {}
    if atual.get("status") != "em_andamento" or int(atual.get("indice_atual") or 0) != indice:
        return RetornoResposta(obter_estado(sessao_id), None, None)
    atual["indice_atual"] = proximo
    atual["ultimo_sinal"] = agora_iso()
    sessoes.salvar(atual)

    if terminou:
        _finalizar(sessao_id)

    return RetornoResposta(obter_estado(sessao_id), None, transicao_fala)


def _finalizar(sessao_id: str) -> None:
    sessoes = T("sessoes")
    sessao = sessoes.obter(sessao_id)
    if not sessao:
        return
    respostas = T("respostas").listar(onde(sessao_id=sessao_id))
    notas = [float(r.get("nota") or 0) for r in respostas]
    media = sum(notas) / len(notas) if notas else 0.0
    contagem = somar_vicios([r.get("vicios") for r in respostas])
    sessao.update(
        {
            "status": "finalizada",
            "nota_final": round(media, 2),
            "finalizada_em": agora_iso(),
            "postura_resumo": resumir_postura(respostas),
            "vicios_resumo": {"contagem": contagem, "texto": resumir_vicios(contagem)},
            "duracao_segundos": _duracao(sessao.get("created_at")),
        }
    )
    sessoes.salvar(sessao)


def _duracao(created_at: str | None) -> int:
    try:
        inicio = datetime.fromisoformat((created_at or "").replace("Z", "+00:00"))
    except ValueError:
        return 1
    return max(1, int(round((datetime.now(timezone.utc) - inicio).total_seconds())))


def resumir_postura(linhas: list[dict]) -> str | None:
    """Consolida a leitura de comportamento das respostas em uma frase para o candidato."""
    nervos = [float(l["nervosismo"]) for l in linhas if isinstance(l.get("nervosismo"), (int, float))]
    confs = [float(l["confianca"]) for l in linhas if isinstance(l.get("confianca"), (int, float))]
    if not nervos and not confs:
        return None
    lendo = sum(1 for l in linhas if l.get("lendo") is True)
    partes = []
    if nervos:
        n = sum(nervos) / len(nervos)
        partes.append(
            "Você demonstrou nervosismo acentuado durante a arguição: respire, fale mais devagar e sustente o olhar."
            if n >= 7
            else "Você demonstrou algum nervosismo, mas manteve o controle na maior parte das respostas."
            if n >= 4
            else "Você se manteve tranquilo diante da banca."
        )
    if confs:
        c = sum(confs) / len(confs)
        partes.append(
            "Sua postura transmitiu confiança nas respostas."
            if c >= 7
            else "Sua confiança oscilou: em alguns momentos faltou firmeza ao responder."
            if c >= 4
            else "Faltou confiança e firmeza na apresentação das respostas."
        )
    if lendo > 0:
        partes.append(f"Em {lendo} de {len(linhas)} respostas houve indícios de leitura de texto — na prova real isso é penalizado.")
    return " ".join(partes)


# ---------- resultado ----------


def _ata_valida(valor) -> dict | None:
    if isinstance(valor, dict) and isinstance(valor.get("avaliadores"), list) and valor["avaliadores"]:
        return valor
    return None


def obter_resultado(sessao_id: str) -> tuple[EstadoSessao, list[dict]]:
    estado = obter_estado(sessao_id)
    data = T("respostas").listar(onde(sessao_id=sessao_id), ordenar="ordem")
    perguntas = T("perguntas").obter_varios([r["pergunta_id"] for r in data])
    respostas = [
        {
            "ordem": r["ordem"],
            "pergunta": (perguntas.get(r["pergunta_id"]) or {}).get("pergunta", ""),
            "transcricao": r["transcricao"],
            "nota": float(r["nota"]) if r.get("nota") is not None else None,
            "justificativa": r.get("justificativa"),
            "pontos_cobertos": r.get("pontos_cobertos") or [],
            "pontos_faltantes": r.get("pontos_faltantes") or [],
            "nervosismo": r.get("nervosismo"),
            "confianca": r.get("confianca"),
            "lendo": r.get("lendo"),
            "postura_observacao": r.get("postura_observacao"),
            "vicios": ranquear_vicios(r.get("vicios") or {}),
            "ata": _ata_valida(r.get("pareceres")),
        }
        for r in data
    ]
    return estado, respostas


# ---------- encerramento ----------


def encerrar_sessao_candidato(sessao_id: str, motivo: str | None = None) -> None:
    """Fecha uma prova em andamento (saída, desistência, queda). Provas concluídas mantêm o resultado."""
    sessoes = T("sessoes")
    sessao = sessoes.obter(sessao_id)
    if not sessao or sessao["status"] != "em_andamento":
        return
    sessao.update(
        {
            "status": "finalizada" if motivo == "finalizada" else "abandonada",
            "finalizada_em": agora_iso(),
            "duracao_segundos": _duracao(sessao.get("created_at")),
        }
    )
    sessoes.salvar(sessao)
