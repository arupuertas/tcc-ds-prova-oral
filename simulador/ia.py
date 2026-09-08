"""Integrações diretas com a OpenAI (embeddings, Whisper e voz). A banca e os demais agentes
ficam em `simulador.agentes` (Agno)."""

from __future__ import annotations

from functools import lru_cache

from openai import APIStatusError, OpenAI

from .custos import custo_tokens, custo_tts, custo_whisper
from .segredos import obter_segredo
from .uso import registrar_uso

EMBEDDING_MODEL = "text-embedding-3-small"
TTS_MODEL = "gpt-4o-mini-tts"
WHISPER_MODEL = "whisper-1"

INSTRUCAO_VOZ = (
    "Fale em português do Brasil, com tom formal, pausado e institucional, "
    "como um examinador de banca de concurso público."
)


class IntegracaoError(Exception):
    """Erro de integração com mensagem pronta para o usuário (nunca inventa nota)."""


def chave_openai() -> str:
    key = obter_segredo("OPENAI_API_KEY")
    if not key:
        raise IntegracaoError("A chave da OpenAI ainda não foi configurada. Cadastre-a na aba Chaves de API do painel.")
    return key


@lru_cache(maxsize=4)
def _cliente(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def cliente() -> OpenAI:
    return _cliente(chave_openai())


def traduzir_erro(e: Exception) -> IntegracaoError:
    if isinstance(e, IntegracaoError):
        return e
    status = getattr(e, "status_code", None) if isinstance(e, APIStatusError) else getattr(e, "status_code", None)
    print(f"[ia] erro do provedor: {e}")
    if status == 401:
        return IntegracaoError("A chave da OpenAI foi recusada (401). Verifique a chave cadastrada.")
    if status == 429:
        return IntegracaoError("A OpenAI retornou limite de uso / cota excedida (429). Verifique o saldo da sua conta.")
    if status:
        return IntegracaoError(f"A OpenAI retornou erro {status}. Tente novamente em instantes.")
    return IntegracaoError("Falha na comunicação com a OpenAI. Tente novamente em instantes.")


def gerar_embeddings(textos: list[str], sessao_id: str | None = None) -> list[list[float]]:
    try:
        res = cliente().embeddings.create(model=EMBEDDING_MODEL, input=textos)
    except Exception as e:
        raise traduzir_erro(e) from e
    tokens = getattr(res.usage, "prompt_tokens", 0) or 0
    registrar_uso(
        provedor="openai",
        operacao="embeddings",
        modelo=EMBEDDING_MODEL,
        unidade="tokens",
        quantidade=tokens,
        tokens_entrada=tokens,
        custo_usd=custo_tokens(EMBEDDING_MODEL, tokens, 0),
        sessao_id=sessao_id,
    )
    return [d.embedding for d in res.data]


def transcrever_audio(dados: bytes, nome_arquivo: str = "resposta.wav", sessao_id: str | None = None) -> str:
    try:
        res = cliente().audio.transcriptions.create(
            file=(nome_arquivo, dados),
            model=WHISPER_MODEL,
            language="pt",
            response_format="verbose_json",
        )
    except Exception as e:
        raise traduzir_erro(e) from e
    segundos = float(getattr(res, "duration", 0) or 0)
    registrar_uso(
        provedor="openai",
        operacao="transcricao",
        modelo=WHISPER_MODEL,
        unidade="segundos",
        quantidade=round(segundos, 2),
        custo_usd=custo_whisper(segundos),
        sessao_id=sessao_id,
    )
    return (getattr(res, "text", "") or "").strip()


def sintetizar_voz(texto: str, voz: str, sessao_id: str | None = None) -> bytes:
    """Voz do avaliador em MP3."""
    try:
        res = cliente().audio.speech.create(
            model=TTS_MODEL,
            voice=voz,
            input=texto,
            instructions=INSTRUCAO_VOZ,
            response_format="mp3",
        )
        dados = res.content
    except Exception as e:
        raise traduzir_erro(e) from e
    registrar_uso(
        provedor="openai",
        operacao="voz_avaliador",
        modelo=TTS_MODEL,
        unidade="caracteres",
        quantidade=len(texto),
        custo_usd=custo_tts(len(texto)),
        sessao_id=sessao_id,
    )
    return dados
