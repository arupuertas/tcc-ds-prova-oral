"""Agentes do simulador, construídos com Agno.

- `interpretar_turno`: classifica a fala do candidato (resposta, repetir, reformular, pular, conversa).
- `analisar_postura`: lê quadros da webcam (nervosismo, confiança, indícios de leitura).
- `avaliar_com_banca`: quatro avaliadores independentes em paralelo e um juiz que pode pedir
  esclarecimentos (ferramenta) antes do veredito estruturado.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from agno.agent import Agent
from agno.media import Image
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from .banca import (
    AVALIADORES,
    JUIZ_ID,
    JUIZ_NOME,
    LIMIAR_DIVERGENCIA,
    MAX_ESCLARECIMENTOS,
    AgenteAvaliador,
    AtaBanca,
    Dossie,
    Esclarecimento,
    ParecerAvaliador,
    Veredito,
)
from .config_app import obter_config_banca, obter_config_prompts
from .custos import custo_tokens
from .ia import IntegracaoError
from .modelos import PROVEDORES_LLM, chave_do_provedor, separar_modelo
from .segredos import obter_segredo
from .uso import registrar_uso



# ---------- modelos ----------


@dataclass
class ModeloResolvido:
    id: str
    provedor: str
    modelo: str
    instancia: object


def _aceita_temperatura(provedor: str, modelo: str) -> bool:
    # Claude 5 e a família GPT-5 / o-series rejeitam `temperature`.
    if provedor == "anthropic":
        return False
    if provedor == "openai" and (modelo.startswith("gpt-5") or modelo[:1] == "o"):
        return False
    return True


def resolver_modelo(id: str, temperatura: float = 0.2) -> ModeloResolvido:
    partes = separar_modelo(id)
    if not partes:
        raise IntegracaoError(f'Modelo inválido na configuração da banca: "{id}".')
    provedor, modelo = partes
    api_key = obter_segredo(chave_do_provedor(provedor))
    if not api_key:
        nome = PROVEDORES_LLM[provedor]["nome"]
        raise IntegracaoError(
            f"A chave da {nome} ({chave_do_provedor(provedor)}) não está configurada. Cadastre-a na aba Chaves de API."
        )
    extra = {"temperature": temperatura} if _aceita_temperatura(provedor, modelo) else {}
    if provedor == "openai":
        instancia = OpenAIChat(id=modelo, api_key=api_key, **extra)
    elif provedor == "anthropic":
        instancia = Claude(id=modelo, api_key=api_key, **extra)
    else:
        instancia = Gemini(id=modelo, api_key=api_key, **extra)
    return ModeloResolvido(id=id, provedor=provedor, modelo=modelo, instancia=instancia)


def provedor_configurado(provedor: str) -> bool:
    return bool(obter_segredo(chave_do_provedor(provedor)))


def status_provedores() -> dict[str, bool]:
    return {p: provedor_configurado(p) for p in PROVEDORES_LLM}


def _registrar(operacao: str, m: ModeloResolvido, saida, sessao_id: str | None) -> None:
    metrics = getattr(saida, "metrics", None)
    entrada = int(getattr(metrics, "input_tokens", 0) or 0)
    saida_t = int(getattr(metrics, "output_tokens", 0) or 0)
    registrar_uso(
        provedor=m.provedor,
        operacao=operacao,
        modelo=m.modelo,
        unidade="tokens",
        quantidade=entrada + saida_t,
        tokens_entrada=entrada,
        tokens_saida=saida_t,
        custo_usd=custo_tokens(m.modelo, entrada, saida_t),
        sessao_id=sessao_id,
    )


def _traduzir(e: Exception) -> IntegracaoError:
    if isinstance(e, IntegracaoError):
        return e
    status = getattr(e, "status_code", None)
    print(f"[agentes] erro: {e!r}")
    if status == 401:
        return IntegracaoError("A chave do provedor foi recusada (401). Verifique a chave cadastrada.")
    if status == 429:
        return IntegracaoError("O provedor retornou limite de uso / cota excedida (429). Verifique o saldo da conta.")
    if status:
        return IntegracaoError(f"O provedor retornou erro {status}. Tente novamente em instantes.")
    return IntegracaoError("A banca não conseguiu processar a resposta. Tente novamente em instantes.")


def _executar(agent: Agent, entrada, **kwargs):
    try:
        return agent.run(entrada, **kwargs)
    except Exception as e:  # noqa: BLE001
        raise _traduzir(e) from e


def _conteudo(saida, schema: type[BaseModel]) -> BaseModel:
    c = saida.content
    if isinstance(c, schema):
        return c
    if isinstance(c, BaseModel):
        return schema.model_validate(c.model_dump())
    if isinstance(c, dict):
        return schema.model_validate(c)
    if isinstance(c, str):
        try:
            return schema.model_validate_json(c)
        except Exception as e:  # noqa: BLE001
            raise IntegracaoError("Não foi possível interpretar a resposta estruturada da IA.") from e
    raise IntegracaoError("A IA não retornou uma resposta estruturada.")


# ---------- turno conversacional ----------


class TurnoCandidato(BaseModel):
    intencao: Literal["resposta", "repetir", "reformular", "conversa", "pular"] = "resposta"
    fala: str = ""


def instrucoes_do_turno() -> str:
    """Instruções (system) em vigor para o classificador de turno."""
    return obter_config_prompts().texto("turno")


def interpretar_turno(pergunta: str, transcricao: str, sessao_id: str | None = None) -> TurnoCandidato:
    m = resolver_modelo(obter_config_banca().modelo_auxiliar, temperatura=0.4)
    agent = Agent(model=m.instancia, instructions=instrucoes_do_turno(), output_schema=TurnoCandidato, markdown=False)
    try:
        saida = _executar(agent, f"PERGUNTA ATUAL:\n{pergunta}\n\nFALA DO CANDIDATO:\n{transcricao or '(silêncio)'}")
        _registrar("conversacao", m, saida, sessao_id)
        turno = _conteudo(saida, TurnoCandidato)
        return TurnoCandidato(intencao=turno.intencao, fala=(turno.fala or "").strip())
    except IntegracaoError:
        raise
    except Exception:  # em caso de dúvida, trata como resposta para não travar a arguição
        return TurnoCandidato(intencao="resposta", fala="")


# ---------- postura ----------


class PosturaCandidato(BaseModel):
    nervosismo: int = Field(ge=0, le=10)
    confianca: int = Field(ge=0, le=10)
    lendo: bool
    observacao: str = ""


def instrucoes_da_postura() -> str:
    """Instruções (system) em vigor para o leitor de postura."""
    return obter_config_prompts().texto("postura")


def analisar_postura(
    pergunta: str, transcricao: str, quadros: list[bytes], sessao_id: str | None = None
) -> PosturaCandidato | None:
    quadros = [q for q in quadros if q][:3]
    if not quadros:
        return None
    m = resolver_modelo(obter_config_banca().modelo_auxiliar, temperatura=0.2)
    agent = Agent(model=m.instancia, instructions=instrucoes_da_postura(), output_schema=PosturaCandidato, markdown=False)
    saida = _executar(
        agent,
        f"PERGUNTA:\n{pergunta}\n\nRESPOSTA FALADA (transcrição):\n{transcricao or '(sem fala)'}\n\n"
        "Quadros da webcam durante a resposta em anexo.",
        images=[Image(content=q, format="png" if q[:4] == b"\x89PNG" else "jpeg") for q in quadros],
    )
    _registrar("analise_postura", m, saida, sessao_id)
    try:
        p = _conteudo(saida, PosturaCandidato)
    except IntegracaoError:
        return None
    return PosturaCandidato(
        nervosismo=max(0, min(10, int(p.nervosismo))),
        confianca=max(0, min(10, int(p.confianca))),
        lendo=bool(p.lendo),
        observacao=(p.observacao or "").strip(),
    )


# ---------- banca ----------

def _lista(itens: list[str]) -> str:
    return "\n".join(f"- {i}" for i in itens)


def _dossie_do_avaliador(agente_ve, d: Dossie) -> str:
    """Monta o dossiê que UM avaliador enxerga — e nada além disso."""
    blocos = [
        f"MATÉRIA / TEMA:\n{' — '.join(x for x in (d.materia, d.tema) if x)}" if (d.materia or d.tema) else None,
        f"PERGUNTA DA BANCA:\n{d.pergunta}",
        f"RESPOSTA PADRÃO (NOTA 10):\n{d.resposta_padrao}" if agente_ve.gabarito else None,
        f"PONTOS-CHAVE ESPERADOS:\n{_lista(d.pontos_chave)}" if agente_ve.pontos_chave and d.pontos_chave else None,
        f"FUNDAMENTOS LEGAIS DE REFERÊNCIA:\n{_lista(d.fundamentos_legais)}"
        if agente_ve.fundamentos and d.fundamentos_legais
        else None,
        (
            "BASE DE CONHECIMENTO:\n"
            + ("\n\n".join(f"[Trecho {i + 1}]\n{c}" for i, c in enumerate(d.contexto)) if d.contexto else "Nenhum trecho disponível.")
        )
        if agente_ve.base_conhecimento
        else None,
        f"RESPOSTA TRANSCRITA DO CANDIDATO:\n{d.transcricao or '(o candidato não respondeu)'}",
    ]
    return "\n\n".join(b for b in blocos if b)


def instrucoes_do_avaliador(agente_id: str) -> str:
    """Instruções (system) em vigor para um avaliador: persona do painel + regras de saída."""
    c = obter_config_prompts()
    return c.texto(agente_id) + c.regras_saida


def instrucoes_do_juiz() -> str:
    """Instruções (system) em vigor para o juiz."""
    return obter_config_prompts().texto(JUIZ_ID)


@dataclass
class _Opiniao:
    agente: AgenteAvaliador
    parecer: ParecerAvaliador
    prompt: str


def _opinar(agente: AgenteAvaliador, d: Dossie, m: ModeloResolvido) -> _Opiniao:
    """Rodada 1: o avaliador opina sozinho."""
    prompt = _dossie_do_avaliador(agente.ve, d)
    agent = Agent(model=m.instancia, instructions=instrucoes_do_avaliador(agente.id), output_schema=ParecerAvaliador, markdown=False)
    saida = _executar(agent, prompt)
    _registrar(f"banca_{agente.id}", m, saida, d.sessao_id)
    return _Opiniao(agente=agente, parecer=_conteudo(saida, ParecerAvaliador), prompt=prompt)


def _esclarecer(op: _Opiniao, pergunta_do_juiz: str, d: Dossie, m: ModeloResolvido) -> Esclarecimento:
    """O avaliador responde ao juiz a partir do que ELE já analisou — sem ver os outros."""
    agent = Agent(model=m.instancia, instructions=instrucoes_do_avaliador(op.agente.id), output_schema=Esclarecimento, markdown=False)
    mensagens = [
        Message(role="user", content=op.prompt),
        Message(role="assistant", content=op.parecer.model_dump_json()),
        Message(
            role="user",
            content=(
                f'O juiz da banca pede um esclarecimento sobre a SUA avaliação:\n"{pergunta_do_juiz}"\n\n'
                "Responda com base no que você já analisou. Revise a nota apenas se o juiz apontou um fato "
                "concreto da resposta que você deixou de considerar; caso contrário, mantenha sua posição "
                "(nota_revisada = null). Não mude de opinião por pressão."
            ),
        ),
    ]
    saida = _executar(agent, mensagens)
    _registrar(f"banca_{op.agente.id}_esclarecimento", m, saida, d.sessao_id)
    return _conteudo(saida, Esclarecimento)


class _VeTudo:
    gabarito = True
    base_conhecimento = True
    pontos_chave = True
    fundamentos = True


def _dossie_do_juiz(d: Dossie, opinioes: list[_Opiniao]) -> str:
    pareceres = "\n\n".join(
        f"### {o.agente.nome} (id: {o.agente.id}, peso {o.agente.peso})\n"
        f"Nota: {o.parecer.nota}\nParecer: {o.parecer.parecer}\n"
        f"Pontos cobertos: {'; '.join(o.parecer.pontos_cobertos) or '—'}\n"
        f"Pontos faltantes: {'; '.join(o.parecer.pontos_faltantes) or '—'}\n"
        f"Alertas: {'; '.join(o.parecer.alertas) or 'nenhum'}"
        for o in opinioes
    )
    return _dossie_do_avaliador(_VeTudo, d) + f"\n\nPARECERES INDEPENDENTES DA BANCA:\n\n{pareceres}"


def previa_dos_prompts(d: Dossie) -> list[dict]:
    """O que CADA agente receberia para este dossiê, sem chamar modelo nenhum.

    Cobre os sete: classificador de turno, leitor de postura, os 4 avaliadores e o juiz. De cada um
    devolve as instruções (system), a mensagem de usuário e o que ele enxerga do dossiê. Usado pela
    aba Agentes do painel.
    """
    itens = [
        {
            "id": "turno",
            "nome": "Classificador de turno",
            "descricao": "Decide se a fala é resposta, pedido de repetição, reformulação, conversa ou desistência.",
            "instrucoes": instrucoes_do_turno(),
            "prompt": f"PERGUNTA ATUAL:\n{d.pergunta}\n\nFALA DO CANDIDATO:\n{d.transcricao or '(silêncio)'}",
            "ve": {"gabarito": False, "base_conhecimento": False, "pontos_chave": False, "fundamentos": False},
        },
        {
            "id": "postura",
            "nome": "Leitor de postura",
            "descricao": "Lê os quadros da webcam: nervosismo, confiança e indícios de leitura.",
            "instrucoes": instrucoes_da_postura(),
            "prompt": (
                f"PERGUNTA:\n{d.pergunta}\n\nRESPOSTA FALADA (transcrição):\n{d.transcricao or '(sem fala)'}\n\n"
                "Quadros da webcam durante a resposta em anexo."
            ),
            "ve": {"gabarito": False, "base_conhecimento": False, "pontos_chave": False, "fundamentos": False},
        },
    ] + [
        {
            "id": a.id,
            "nome": a.nome,
            "descricao": a.descricao,
            "instrucoes": instrucoes_do_avaliador(a.id),
            "prompt": _dossie_do_avaliador(a.ve, d),
            "ve": {
                "gabarito": a.ve.gabarito,
                "base_conhecimento": a.ve.base_conhecimento,
                "pontos_chave": a.ve.pontos_chave,
                "fundamentos": a.ve.fundamentos,
            },
        }
        for a in AVALIADORES
    ]
    exemplo = [
        _Opiniao(
            agente=a,
            parecer=ParecerAvaliador(
                nota=7.0,
                parecer="(parecer deste avaliador entra aqui)",
                pontos_cobertos=["(ponto coberto)"],
                pontos_faltantes=["(ponto faltante)"],
                alertas=[],
            ),
            prompt="",
        )
        for a in AVALIADORES
    ]
    itens.append(
        {
            "id": JUIZ_ID,
            "nome": JUIZ_NOME,
            "descricao": "Preside a banca, pode pedir esclarecimentos e fixa a nota final.",
            "instrucoes": instrucoes_do_juiz(),
            "prompt": _dossie_do_juiz(d, exemplo),
            "ve": {"gabarito": True, "base_conhecimento": True, "pontos_chave": True, "fundamentos": True},
        }
    )
    return itens


def avaliar_com_banca(d: Dossie) -> tuple[Veredito, AtaBanca]:
    """Avalia uma resposta com a banca completa e devolve o veredito e a ata da deliberação."""
    config = obter_config_banca()
    m_avaliadores = resolver_modelo(config.modelo_avaliadores)
    m_juiz = resolver_modelo(config.modelo_juiz)

    # Rodada 1 — independentes e em paralelo: nenhum vê o parecer do outro.
    with ThreadPoolExecutor(max_workers=len(AVALIADORES)) as pool:
        opinioes = list(pool.map(lambda a: _opinar(a, d, m_avaliadores), AVALIADORES))

    notas = [o.parecer.nota for o in opinioes]
    divergencia = round(max(notas) - min(notas), 1)
    pode_perguntar = divergencia >= LIMIAR_DIVERGENCIA

    deliberacao: list[dict] = []
    perguntas_por_avaliador: dict[str, int] = {}
    ids = ", ".join(o.agente.id for o in opinioes)

    def perguntar_ao_avaliador(agente_id: str, pergunta: str) -> str:
        """Pede a um avaliador da banca um esclarecimento sobre um fato concreto da resposta do candidato.
        Não revele notas nem opiniões de outros avaliadores. No máximo uma pergunta por avaliador.

        Args:
            agente_id: id do avaliador (um de: critico, tranquilo, verificador, independente).
            pergunta: a pergunta objetiva ao avaliador (5 a 600 caracteres).
        """
        total = sum(1 for e in deliberacao if e["tipo"] == "pergunta")
        if total >= MAX_ESCLARECIMENTOS or perguntas_por_avaliador.get(agente_id, 0) >= 1:
            return json.dumps({"erro": "Limite de esclarecimentos atingido. Emita o veredito agora."})
        op = next((o for o in opinioes if o.agente.id == agente_id), None)
        if not op:
            return json.dumps({"erro": f"Avaliador desconhecido. Use um de: {ids}."})
        perguntas_por_avaliador[agente_id] = 1
        deliberacao.append({"tipo": "pergunta", "para": agente_id, "texto": pergunta[:600]})
        e = _esclarecer(op, pergunta, d, m_avaliadores)
        deliberacao.append(
            {"tipo": "esclarecimento", "de": agente_id, "texto": e.esclarecimento, "notaRevisada": e.nota_revisada}
        )
        return e.model_dump_json()

    prompt_juiz = _dossie_do_juiz(d, opinioes)
    # Sem divergência relevante, o juiz nem recebe a ferramenta de perguntar (custo zero).
    juiz = Agent(
        model=m_juiz.instancia,
        instructions=instrucoes_do_juiz(),
        tools=[perguntar_ao_avaliador] if pode_perguntar else None,
        tool_call_limit=MAX_ESCLARECIMENTOS if pode_perguntar else None,
        output_schema=Veredito,
        markdown=False,
    )
    saida = _executar(juiz, prompt_juiz)
    _registrar("banca_juiz", m_juiz, saida, d.sessao_id)

    try:
        v = _conteudo(saida, Veredito)
    except IntegracaoError:
        # Rede de segurança: o juiz encerrou sem veredito estruturado. Forçamos a decisão.
        resumo = "\n".join(
            f"Juiz → {e['para']}: {e['texto']}"
            if e["tipo"] == "pergunta"
            else f"{e['de']}: {e['texto']}" + (f" (nota revisada: {e['notaRevisada']})" if e.get("notaRevisada") is not None else "")
            for e in deliberacao
        )
        forcado = Agent(model=m_juiz.instancia, instructions=instrucoes_do_juiz(), output_schema=Veredito, markdown=False)
        saida2 = _executar(
            forcado, f"{prompt_juiz}\n\nDELIBERAÇÃO REALIZADA:\n{resumo or '(nenhuma)'}\n\nEmita agora o veredito final."
        )
        _registrar("banca_juiz_veredito", m_juiz, saida2, d.sessao_id)
        v = _conteudo(saida2, Veredito)

    nota = max(0.0, min(10.0, round(v.nota, 1)))
    veredito = Veredito(nota=nota, justificativa=v.justificativa, pontos_cobertos=v.pontos_cobertos, pontos_faltantes=v.pontos_faltantes)
    ata = AtaBanca(
        avaliadores=[
            {"agenteId": o.agente.id, "nome": o.agente.nome, "modelo": m_avaliadores.id, **o.parecer.model_dump()}
            for o in opinioes
        ],
        deliberacao=deliberacao,
        juiz={"modelo": m_juiz.id, "nota": nota},
        divergencia=divergencia,
    )
    return veredito, ata
