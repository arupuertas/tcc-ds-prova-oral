"""Esquema do banco do Simulador de Prova Oral em ChromaDB.

O Chroma é um banco de vetores: cada coleção guarda registros com `id`, um `document`, um
`embedding` e `metadata` (só valores escalares). Usamos assim:

- **Coleções de registros** (concursos, sessões, respostas…): o registro completo vai em
  `document` como JSON; os campos usados em filtros vão em `metadata`; o embedding é um vetor
  fixo de 1 dimensão (`[1.0]`), nunca consultado por similaridade.
- **Coleções vetoriais**: embeddings reais (OpenAI text-embedding-3-small, 1536 dimensões,
  distância cosseno). São duas, deliberadamente separadas para não haver vazamento entre elas:
  `material_chunks` (arquivos de estudo enviados no painel, a única base consultada durante a
  prova) e `gabarito_chunks` (perguntas e respostas padrão, usada só na busca do painel).

Este módulo é a fonte da verdade do esquema: nomes das coleções, campos indexados em metadata
(com tipo) e configuração vetorial. `db/inicializar.py` cria as coleções a partir daqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIMENSAO_EMBEDDING = 1536
DIMENSAO_REGISTRO = 1  # embedding fictício das coleções de registros

Tipo = str  # "str" | "int" | "float" | "bool"


@dataclass(frozen=True)
class Colecao:
    nome: str
    descricao: str
    campos: dict[str, str]  # documentação dos campos do JSON (nome → descrição)
    metadados: dict[str, Tipo] = field(default_factory=dict)  # campos copiados para metadata (filtráveis)
    vetorial: bool = False
    chave_natural: str | None = None  # quando o id é um valor de negócio (ex.: nome da configuração)


ESQUEMA: dict[str, Colecao] = {
    "concursos": Colecao(
        nome="concursos",
        descricao="Certames disponíveis para simulação.",
        campos={
            "id": "uuid",
            "nome": "texto",
            "descricao": "texto ou null",
            "quantidade_perguntas": "inteiro (padrão de perguntas por simulação)",
            "ativo": "booleano (visível ao candidato)",
            "created_at": "ISO 8601",
            "updated_at": "ISO 8601",
        },
        metadados={"nome": "str", "ativo": "bool", "created_ts": "float"},
    ),
    "perguntas": Colecao(
        nome="perguntas",
        descricao="Banco de perguntas por concurso (grupo, momento, ordem, cadeia, rubrica).",
        campos={
            "id": "uuid (uuid5 de concurso_id+origem_uid quando importada)",
            "concurso_id": "uuid do concurso",
            "grupo": "inteiro (sorteável)",
            "sequencia": "inicio | meio | fim",
            "ordem": "inteiro",
            "pergunta": "texto",
            "resposta_padrao": "texto (gabarito nota 10)",
            "materia": "texto ou null",
            "tema": "texto ou null",
            "subtema": "texto ou null",
            "dificuldade": "facil | media | dificil | null",
            "tipo": "principal | desdobramento | null",
            "cadeia": "texto ou null (pergunta principal + desdobramentos)",
            "pontos_chave": "lista de textos",
            "fundamentos_legais": "lista de textos",
            "origem_uid": "texto ou null (uid no banco de questões)",
            "metadados": "objeto livre",
            "created_at": "ISO 8601",
            "updated_at": "ISO 8601",
        },
        metadados={"concurso_id": "str", "grupo": "int", "sequencia": "str", "ordem": "int", "origem_uid": "str", "materia": "str"},
    ),
    "sessoes": Colecao(
        nome="sessoes",
        descricao="Uma prova oral simulada (sessão do candidato).",
        campos={
            "id": "uuid",
            "concurso_id": "uuid",
            "nome_candidato": "texto ou null",
            "grupo": "inteiro sorteado",
            "quantidade_perguntas": "inteiro",
            "pergunta_ids": "lista de uuids na ordem da arguição",
            "indice_atual": "inteiro (próxima pergunta)",
            "status": "em_andamento | finalizada | abandonada",
            "nota_final": "número ou null",
            "resumo": "texto ou null",
            "postura_resumo": "texto ou null",
            "vicios_resumo": "{contagem: {termo: n}, texto: string|null}",
            "duracao_segundos": "inteiro ou null",
            "ip_hash": "texto ou null",
            "ultimo_sinal": "ISO 8601 (heartbeat)",
            "created_at": "ISO 8601",
            "finalizada_em": "ISO 8601 ou null",
        },
        metadados={"concurso_id": "str", "status": "str", "ip_hash": "str", "grupo": "int", "created_ts": "float", "ultimo_sinal_ts": "float"},
    ),
    "respostas": Colecao(
        nome="respostas",
        descricao="Resposta avaliada de uma pergunta da sessão (id = `<sessao_id>:<ordem>`).",
        campos={
            "id": "<sessao_id>:<ordem>",
            "sessao_id": "uuid",
            "pergunta_id": "uuid",
            "ordem": "inteiro",
            "transcricao": "texto",
            "nota": "número ou null",
            "justificativa": "texto ou null",
            "pontos_cobertos": "lista de textos",
            "pontos_faltantes": "lista de textos",
            "pareceres": "ata da banca (objeto) ou {}",
            "nervosismo": "0-10 ou null",
            "confianca": "0-10 ou null",
            "lendo": "booleano ou null",
            "postura_observacao": "texto ou null",
            "vicios": "{termo: n}",
            "created_at": "ISO 8601",
        },
        metadados={"sessao_id": "str", "pergunta_id": "str", "ordem": "int"},
        chave_natural="sessao_id:ordem",
    ),
    "documentos": Colecao(
        nome="documentos",
        descricao="Arquivos enviados no painel (doutrina, legislação, jurisprudência). Só material de estudo.",
        campos={
            "id": "uuid",
            "concurso_id": "uuid ou null (null = vale para todos os concursos)",
            "nome": "nome do arquivo enviado",
            "status": "processando | indexado | erro",
            "erro": "texto ou null",
            "total_chunks": "inteiro",
            "created_at": "ISO 8601",
        },
        metadados={"concurso_id": "str", "nome": "str", "status": "str", "created_ts": "float"},
    ),
    "material_chunks": Colecao(
        nome="material_chunks",
        descricao=(
            "BASE 1 — material de estudo. Trechos vetorizados dos arquivos enviados no painel. "
            "É a única base lida durante a prova: alimenta o 'Verificador da base'."
        ),
        campos={
            "id": "<documento_id>:<indice>",
            "document": "texto do trecho",
            "embedding": f"vetor de {DIMENSAO_EMBEDDING} dimensões (text-embedding-3-small)",
        },
        metadados={"documento_id": "str", "concurso_id": "str", "indice": "int"},
        vetorial=True,
    ),
    "gabarito_chunks": Colecao(
        nome="gabarito_chunks",
        descricao=(
            "BASE 2 — gabaritos. Trechos vetorizados das perguntas e respostas padrão do banco. "
            "Nunca é lida durante a prova (evita vazar a resposta de uma pergunta na avaliação de outra); "
            "serve à busca semântica do painel."
        ),
        campos={
            "id": "<pergunta_id>:<indice>",
            "document": "texto do trecho (matéria, tema, pergunta e resposta padrão)",
            "embedding": f"vetor de {DIMENSAO_EMBEDDING} dimensões (text-embedding-3-small)",
        },
        metadados={"pergunta_id": "str", "concurso_id": "str", "indice": "int"},
        vetorial=True,
    ),
    "configuracoes": Colecao(
        nome="configuracoes",
        descricao="Configurações do painel (id = chave: avaliador, banca, limites).",
        campos={"id": "chave", "valor": "objeto", "updated_at": "ISO 8601"},
        chave_natural="chave",
    ),
    "segredos": Colecao(
        nome="segredos",
        descricao="Chaves de API cadastradas no painel, cifradas com AES-256-GCM (id = nome da chave).",
        campos={"id": "nome da chave (ex.: OPENAI_API_KEY)", "valor_cifrado": "v1:<iv>:<dados>", "atualizado_em": "ISO 8601"},
        chave_natural="chave",
    ),
    "api_uso": Colecao(
        nome="api_uso",
        descricao="Consumo de cada chamada a provedores externos (custos).",
        campos={
            "id": "uuid",
            "sessao_id": "uuid ou null",
            "provedor": "openai | anthropic | google | …",
            "operacao": "texto (embeddings, transcricao, banca_critico, …)",
            "modelo": "texto ou null",
            "unidade": "tokens | segundos | caracteres | requisicoes",
            "quantidade": "número",
            "tokens_entrada": "inteiro",
            "tokens_saida": "inteiro",
            "custo_usd": "número",
            "created_at": "ISO 8601",
        },
        metadados={"provedor": "str", "operacao": "str", "sessao_id": "str", "created_ts": "float"},
    ),
}


def configuracao_colecao(colecao: Colecao) -> dict:
    """Configuração HNSW passada ao Chroma na criação."""
    return {"hnsw": {"space": "cosine"}}


def inicializar(cliente) -> list[str]:
    """Cria (se preciso) todas as coleções do esquema e devolve os nomes."""
    nomes = []
    for c in ESQUEMA.values():
        cliente.get_or_create_collection(c.nome, configuration=configuracao_colecao(c))
        nomes.append(c.nome)
    return nomes
