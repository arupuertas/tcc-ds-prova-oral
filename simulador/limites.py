"""Limites de capacidade.

O simulador consome recursos escassos por sessão (LLMs, transcrição, voz). Para atender várias
pessoas ao mesmo tempo controlamos quantas provas podem estar em andamento, quantas a mesma
origem (IP) pode abrir e liberamos sessões órfãs. Todo o estado vive no banco.
"""

from __future__ import annotations

import hashlib
import time

from .config_app import obter_config_limites
from .db import T, agora_iso, onde


class CapacidadeError(Exception):
    pass


def hash_da_origem(ip: str | None) -> str | None:
    """Identificador estável e anônimo da origem do candidato."""
    if not ip:
        return None
    return hashlib.sha256(f"simulador:{ip}".encode()).hexdigest()[:32]


def sessoes_em_andamento() -> int:
    return T("sessoes").contar(onde(status="em_andamento"))


def liberar_sessoes_orfas() -> None:
    """Fecha sessões em andamento sem sinal de vida. Roda antes de cada nova prova."""
    try:
        minutos = obter_config_limites().minutos_sem_sinal
        limite = time.time() - minutos * 60
        T("sessoes").atualizar_onde(
            onde({"ultimo_sinal_ts": {"$lt": limite}}, status="em_andamento"),
            {"status": "abandonada", "finalizada_em": agora_iso()},
        )
    except Exception as e:
        print(f"[limites] falha ao liberar sessões órfãs: {e}")


def registrar_sinal(sessao_id: str) -> None:
    """Marca atividade da sessão. Falhas aqui nunca interrompem a prova."""
    try:
        t = T("sessoes")
        sessao = t.obter(sessao_id)
        if sessao and sessao.get("status") == "em_andamento":
            sessao["ultimo_sinal"] = agora_iso()
            t.salvar(sessao)
    except Exception as e:
        print(f"[limites] falha ao registrar sinal: {e}")


def autorizar_nova_sessao(ip_hash: str | None) -> None:
    """Lança `CapacidadeError` com mensagem pronta para o candidato quando não há vaga."""
    liberar_sessoes_orfas()
    limites = obter_config_limites()
    t = T("sessoes")

    if sessoes_em_andamento() >= limites.max_sessoes:
        raise CapacidadeError("Todas as bancas estão ocupadas neste momento. Tente novamente em alguns minutos.")

    if not ip_hash:
        return

    uma_hora_atras = time.time() - 3600
    ativas_do_ip = t.contar(onde(ip_hash=ip_hash, status="em_andamento"))
    inicios_do_ip = t.contar(onde({"created_ts": {"$gte": uma_hora_atras}}, ip_hash=ip_hash))
    if ativas_do_ip >= limites.max_sessoes_por_ip:
        raise CapacidadeError(
            "Há muitas provas em andamento a partir da sua rede. Aguarde alguém concluir ou tente de outra conexão."
        )
    if inicios_do_ip >= limites.max_inicios_por_hora:
        raise CapacidadeError("Você iniciou muitas provas na última hora. Aguarde um pouco antes de tentar de novo.")
