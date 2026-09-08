# Esquema do banco (ChromaDB)

O Simulador de Prova Oral usa o **ChromaDB** como único banco. A definição em código está em
`simulador/esquema.py`; `python db/inicializar.py` cria as coleções.

## Como as coleções são usadas

| Tipo | Coleções | `document` | `embedding` | `metadata` |
|---|---|---|---|---|
| Registros | concursos, perguntas, sessoes, respostas, documentos, configuracoes, segredos, api_uso | JSON completo do registro | vetor fixo `[1.0]` (nunca consultado) | campos filtráveis (escalares) |
| Vetorial | material_chunks | texto do trecho | `text-embedding-3-small` (1536, cosseno) | documento_id, concurso_id, indice |
| Vetorial | gabarito_chunks | texto do trecho | `text-embedding-3-small` (1536, cosseno) | pergunta_id, concurso_id, indice |

Regras:
- Metadata só aceita `str`, `int`, `float`, `bool`; `null` vira `""` em campos de texto.
- Datas ficam em ISO 8601 no JSON; para filtros numéricos há espelhos `*_ts` (epoch) na metadata.
- Chaves compostas viram ids determinísticos: `respostas` = `<sessao_id>:<ordem>`,
  `material_chunks` = `<documento_id>:<indice>`, `gabarito_chunks` = `<pergunta_id>:<indice>`,
  perguntas importadas = `uuid5(concurso_id:origem_uid)`.
- Não há cascata no Chroma: `simulador.admin.excluir_concurso/excluir_pergunta/excluir_documento` removem os dependentes.

## Coleções

### concursos
`id, nome, descricao, quantidade_perguntas, ativo, created_at, updated_at`
metadata: `nome, ativo, created_ts`

### perguntas
`id, concurso_id, grupo, sequencia (inicio|meio|fim), ordem, pergunta, resposta_padrao, materia, tema,
subtema, dificuldade, tipo, cadeia, pontos_chave[], fundamentos_legais[], origem_uid, metadados{}, created_at, updated_at`
metadata: `concurso_id, grupo, sequencia, ordem, origem_uid, materia`

### sessoes
`id, concurso_id, nome_candidato, grupo, quantidade_perguntas, pergunta_ids[], indice_atual,
status (em_andamento|finalizada|abandonada), nota_final, resumo, postura_resumo,
vicios_resumo{contagem,texto}, duracao_segundos, ip_hash, ultimo_sinal, created_at, finalizada_em`
metadata: `concurso_id, status, ip_hash, grupo, created_ts, ultimo_sinal_ts`

### respostas
`id (<sessao_id>:<ordem>), sessao_id, pergunta_id, ordem, transcricao, nota, justificativa,
pontos_cobertos[], pontos_faltantes[], pareceres{ata da banca}, nervosismo, confianca, lendo,
postura_observacao, vicios{termo:n}, created_at`
metadata: `sessao_id, pergunta_id, ordem`

### documentos
`id, concurso_id (null = todos), nome do arquivo, status, erro, total_chunks, created_at`
metadata: `concurso_id, nome, status, created_ts`
Só arquivos de estudo enviados no painel. Perguntas **não** entram aqui.

### material_chunks (vetorial) — base 1
`id (<documento_id>:<indice>)`, document = trecho, embedding 1536d
metadata: `documento_id, concurso_id ("" = todos), indice`
Busca: `query_embeddings` com `where {"$or":[{"concurso_id": X},{"concurso_id": ""}]}`.
É a **única** base lida durante a prova (`simulador.simulacao._contexto_relevante`), e alimenta
apenas o avaliador "Verificador da base".

### gabarito_chunks (vetorial) — base 2
`id (<pergunta_id>:<indice>)`, document = matéria, tema, enunciado e resposta padrão, embedding 1536d
metadata: `pergunta_id, concurso_id, indice`
Índice semântico do banco de questões, usado só pelo painel (`simulador.admin.buscar_gabaritos`).
**Nunca** é consultada durante a prova: se fosse, o gabarito de uma pergunta apareceria como
contexto na avaliação de outra.

### configuracoes
`id = chave (avaliador | banca | prompts | limites), valor{}, updated_at`
`prompts` guarda só o que foi editado no painel: `{personas:{agenteId:texto}, regrasSaida}`.
Ids: turno, postura, critico, tranquilo, verificador, independente, juiz.
Persona ausente ou vazia = usa o padrão de `simulador/personas.py`.

### segredos
`id = nome da chave (OPENAI_API_KEY…), valor_cifrado (v1:iv:dados, AES-256-GCM), atualizado_em`

### api_uso
`id, sessao_id, provedor, operacao, modelo, unidade, quantidade, tokens_entrada, tokens_saida, custo_usd, created_at`
metadata: `provedor, operacao, sessao_id, created_ts`

## Onde o banco roda

| Secrets | Cliente |
|---|---|
| `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE` | Chroma Cloud (recomendado no Streamlit Community Cloud: o disco lá é efêmero) |
| `CHROMA_HOST` (+ `CHROMA_PORT`, `CHROMA_SSL`, `CHROMA_TOKEN`) | servidor Chroma próprio |
| nenhum | pasta local `CHROMA_PATH` (padrão `./dados/chroma`) |

## Administrador

Não há tabela de usuários: o painel usa `ADMIN_USUARIO` / `ADMIN_SENHA` dos secrets.
`CHAVES_CRIPTO_SECRET` cifra as chaves de API cadastradas no painel.
