"""Catálogo dos agentes do simulador: o que cada um faz e como está configurado.

É a fonte que a aba **Agentes** do painel usa para descrever a montagem de cada `Agent` do Agno.
Mantenha em dia quando mudar `simulador/agentes.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgenteInfo:
    id: str
    nome: str
    grupo: str  # "Prova" ou "Banca"
    descricao: str
    quando: str  # em que momento da prova ele roda
    modelo: str  # de onde sai o modelo (chave da configuração)
    temperatura: float
    saida: str  # schema Pydantic de saída estruturada
    entrada: str  # o que recebe como mensagem de usuário
    ferramentas: list[str] = field(default_factory=list)
    observacao: str = ""


MODELO_AUXILIAR = "auxiliar"  # agentes da prova (turno e postura)
MODELO_AVALIADORES = "avaliadores"
MODELO_JUIZ = "juiz"

CATALOGO: list[AgenteInfo] = [
    AgenteInfo(
        id="turno",
        nome="Classificador de turno",
        grupo="Prova",
        descricao="Lê a fala do candidato e decide se é resposta, pedido de repetição, reformulação, conversa ou desistência.",
        quando="A cada gravação enviada, antes de qualquer avaliação.",
        modelo=MODELO_AUXILIAR,
        temperatura=0.4,
        saida="TurnoCandidato (intencao, fala)",
        entrada="A pergunta atual e a transcrição da fala do candidato.",
        observacao=(
            "É o agente que decide se a resposta vai para a banca. Classificada como 'pular', a pergunta "
            "recebe nota zero e a banca nem é chamada. Se ele estiver zerando respostas em que o candidato "
            "apenas admite uma lacuna, é aqui que se corrige."
        ),
    ),
    AgenteInfo(
        id="postura",
        nome="Leitor de postura",
        grupo="Prova",
        descricao="Analisa os quadros da webcam: nervosismo, confiança e indícios de leitura.",
        quando="Junto com a avaliação, apenas quando o candidato tira foto. Sem foto, não roda.",
        modelo=MODELO_AUXILIAR,
        temperatura=0.2,
        saida="PosturaCandidato (nervosismo, confianca, lendo, observacao)",
        entrada="A pergunta, a transcrição e até 3 imagens da webcam.",
        observacao="Nunca bloqueia a nota: se falhar, a avaliação segue sem análise de postura.",
    ),
    AgenteInfo(
        id="critico",
        nome="Avaliador crítico",
        grupo="Banca",
        descricao="Rigoroso: cobra precisão técnica e fundamentação.",
        quando="Rodada 1, em paralelo com os outros três avaliadores.",
        modelo=MODELO_AVALIADORES,
        temperatura=0.2,
        saida="ParecerAvaliador (nota, parecer, pontos, alertas)",
        entrada="Dossiê com gabarito, pontos-chave e fundamentos legais.",
    ),
    AgenteInfo(
        id="tranquilo",
        nome="Avaliador tranquilo",
        grupo="Banca",
        descricao="Valoriza raciocínio e clareza; distingue lacuna de erro.",
        quando="Rodada 1, em paralelo com os outros três avaliadores.",
        modelo=MODELO_AVALIADORES,
        temperatura=0.2,
        saida="ParecerAvaliador (nota, parecer, pontos, alertas)",
        entrada="Dossiê com gabarito e pontos-chave, sem fundamentos legais.",
    ),
    AgenteInfo(
        id="verificador",
        nome="Verificador da base",
        grupo="Banca",
        descricao="Compara afirmação por afirmação com a base de material.",
        quando="Rodada 1, em paralelo com os outros três avaliadores.",
        modelo=MODELO_AVALIADORES,
        temperatura=0.2,
        saida="ParecerAvaliador (nota, parecer, pontos, alertas)",
        entrada="Dossiê com gabarito, fundamentos legais e os trechos do material de estudo.",
        observacao="É o único que recebe a base de material. Sem material enviado, avalia sem trechos de apoio.",
    ),
    AgenteInfo(
        id="independente",
        nome="Jurista independente",
        grupo="Banca",
        descricao="Não vê gabarito nem material: julga só com o próprio conhecimento.",
        quando="Rodada 1, em paralelo com os outros três avaliadores.",
        modelo=MODELO_AVALIADORES,
        temperatura=0.2,
        saida="ParecerAvaliador (nota, parecer, pontos, alertas)",
        entrada="Só a pergunta e a resposta do candidato.",
        observacao="Serve de controle contra erro do próprio gabarito. O que ele enxerga é fixo no código.",
    ),
    AgenteInfo(
        id="juiz",
        nome="Juiz da banca",
        grupo="Banca",
        descricao="Pondera os quatro pareceres e fixa a nota final.",
        quando="Rodada 2, depois dos quatro pareceres.",
        modelo=MODELO_JUIZ,
        temperatura=0.2,
        saida="Veredito (nota, justificativa, pontos cobertos e faltantes)",
        entrada="Dossiê completo mais os quatro pareceres independentes.",
        ferramentas=["perguntar_ao_avaliador"],
        observacao=(
            "A ferramenta só é entregue quando a divergência entre a maior e a menor nota atinge o limiar; "
            "sem divergência ele decide direto, sem custo extra."
        ),
    ),
]


def por_id(agente_id: str) -> AgenteInfo | None:
    return next((a for a in CATALOGO if a.id == agente_id), None)


IDS = [a.id for a in CATALOGO]
