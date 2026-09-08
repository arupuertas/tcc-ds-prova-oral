# Simulador de Prova Oral para Concursos

Aplicação 100% Python: interface em **Streamlit**, agentes da banca examinadora com **Agno**,
banco em **ChromaDB** (registros + busca vetorial da base de conhecimento) e integrações
**OpenAI** (Whisper, TTS, embeddings e visão).

## Como funciona

1. **Home → Concursos**: o candidato escolhe o certame.
2. **Sala de espera**: testa o microfone, informa o nome, escolhe a quantidade de perguntas (5 a 30) e o
   formato do avaliador (foto, bola falante ou juiz em vídeo). Câmera é opcional.
3. **Prova oral**: o simulador sorteia um **grupo** de perguntas e monta a arguição na ordem
   início → meio → fim, respeitando cadeias (pergunta principal + desdobramentos). O avaliador fala cada
   pergunta (voz sintetizada), o candidato grava a resposta, o áudio é transcrito (Whisper) e:
   - um agente classifica o turno (resposta, pedido de repetição/reformulação, pular, conversa);
   - respostas de mérito vão para a **banca**: 4 avaliadores independentes (Agno) com personas e visões
     distintas do dossiê + 1 juiz que pode pedir esclarecimentos por ferramenta antes do veredito;
     só o "Verificador da base" recebe trechos da base de material (RAG);
   - um agente de visão lê a foto da webcam (nervosismo, confiança, indícios de leitura);
   - vícios de linguagem são contados na transcrição.
4. **Resultado**: nota final, postura, gráfico de vícios e, por pergunta, nota, justificativa, pontos
   cobertos/faltantes e a ata completa da banca.

**Painel admin** (`/auth` → `/admin`): estatísticas, sessões e limites de capacidade, custos por
provedor, voz e clipes do avaliador, modelos da banca (OpenAI, Anthropic, Google), chaves de API cifradas,
concursos, perguntas, importação do banco de questões reais (`banco de questoes finais/banco_final.json`)
e as duas bases de conhecimento. A aba **Agentes** mostra como cada um dos 7 agentes do Agno está
montado (quando roda, modelo, temperatura, entrada, saída estruturada e ferramentas) e permite
editar o prompt de cada um, com a prévia do prompt completo que vai ao modelo.

## Estrutura

```
app.py                  # entrada do Streamlit (navegação)
paginas/                # páginas: home, concursos, sala, prova, resultado, auth, admin
simulador/                # núcleo (sem Streamlit)
  esquema.py            # esquema do banco: coleções do ChromaDB e campos filtráveis
  db.py                 # cliente Chroma (local, servidor ou Chroma Cloud) e camada de acesso
  agentes.py            # agentes Agno: turno, postura e banca (avaliadores + juiz)
  personas.py           # textos padrão de todos os prompts (editáveis no painel)
  catalogo.py           # ficha de cada agente: quando roda, modelo, entrada, saída, ferramentas
  banca.py              # personas padrão, schemas Pydantic e regras da deliberação
  simulacao.py          # sorteio, sequência, resposta, finalização, resultado
  admin.py              # estatísticas, CRUDs, importação, RAG, métricas
  ia.py                 # OpenAI: embeddings, Whisper, TTS
  segredos.py           # chaves de API cifradas (AES-GCM) na coleção `segredos`
  config_app.py         # configurações (avaliador, banca, prompts, limites)
  limites.py            # capacidade e sessões órfãs
  ui/                   # cabeçalho, navegação, componente do avatar
assets/                 # imagens (juiz, vozes, logo)
db/ESQUEMA.md           # documentação do esquema; db/inicializar.py cria as coleções
db/importar_banco.py    # importa e indexa o banco de questões
db/migrar_bases.py      # separa a base antiga em material_chunks + gabarito_chunks
db/anonimizar_banco.py  # remove do banco os dados pessoais dos candidatos reais
db/amostra_banco.py     # gera uma amostra menor do banco (padrão: 40 questões)
tests/                  # pytest: núcleo, banca (Agno simulado), banco Chroma, páginas
banco de questoes finais/  # 292 perguntas de provas orais reais do MP-SP (anonimizado)
  banco_final.json         # banco completo
  banco_amostra.json       # amostra de 40 questões (4 provas x 10)
```

## Rodando localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # defina ADMIN_SENHA e CHAVES_CRIPTO_SECRET
python db/inicializar.py                                     # cria as coleções em ./dados/chroma
streamlit run app.py
```

Depois entre em **Admin** com `ADMIN_USUARIO`/`ADMIN_SENHA`, cadastre a chave da OpenAI em
**Chaves de API** (obrigatória: voz, transcrição, embeddings e visão; Anthropic e Google são opcionais)
e importe o banco de questões na aba **Importar**.

### As duas bases de conhecimento

O RAG é dividido em duas coleções vetoriais isoladas, para que o gabarito de uma pergunta nunca
apareça como contexto na avaliação de outra:

| Base | Conteúdo | Quem lê |
|---|---|---|
| `material_chunks` | arquivos enviados no painel (PDF, TXT, MD) | a banca, durante a prova |
| `gabarito_chunks` | perguntas e respostas padrão do banco de questões | só a busca do painel |

Sem material enviado, o avaliador "Verificador da base" trabalha sem trechos de apoio: os outros
três avaliadores e o juiz seguem funcionando com gabarito, pontos-chave e fundamentos legais.

Quem vem de uma versão anterior, com a coleção única `documento_chunks`, roda uma vez:

```bash
python db/migrar_bases.py            # diagnóstico
python db/migrar_bases.py --aplicar  # executa
```

### Banco (ChromaDB)

O esquema está em `simulador/esquema.py` e documentado em `db/ESQUEMA.md`. Sem configuração o app usa
uma pasta local (`CHROMA_PATH`, padrão `./dados/chroma`). Para produção use o
[Chroma Cloud](https://www.trychroma.com) (`CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE`) ou um
servidor Chroma próprio (`CHROMA_HOST`).

## Deploy no Streamlit Community Cloud

O disco do Community Cloud é apagado a cada reinício, então o banco **precisa** ser o
[Chroma Cloud](https://www.trychroma.com) (plano gratuito serve). Sem ele o app sobe, mas perde
concursos, perguntas e resultados no primeiro restart. O painel avisa quando está nessa situação.

1. Crie a base no Chroma Cloud e anote `CHROMA_API_KEY`, `CHROMA_TENANT` e `CHROMA_DATABASE`.
2. Popule essa base a partir da sua máquina, apontando o script para ela:

   ```bash
   CHROMA_API_KEY=... CHROMA_TENANT=... CHROMA_DATABASE=... \
     python db/importar_banco.py --vetorizar
   ```

3. Em [share.streamlit.io](https://share.streamlit.io) crie o app a partir deste repositório,
   arquivo principal `app.py`, Python 3.12 ou 3.13 em *Advanced settings*.
4. Ainda em *Advanced settings*, cole os segredos:

   ```toml
   ADMIN_USUARIO = "..."
   ADMIN_SENHA = "..."
   CHAVES_CRIPTO_SECRET = "uma-frase-longa-e-aleatoria"
   OPENAI_API_KEY = "sk-..."
   CHROMA_API_KEY = "..."
   CHROMA_TENANT = "..."
   CHROMA_DATABASE = "..."
   ```

5. Depois do deploy, entre em `/auth` e confira na aba **Bases de conhecimento** se o banco
   aparece como Chroma Cloud.

Troque `ADMIN_SENHA` e `CHAVES_CRIPTO_SECRET` por valores reais antes de publicar. O segredo de
cifra protege as chaves de API guardadas no painel: mudá-lo depois invalida as já salvas.

## Testes

```bash
python -m pytest tests -q
```

## Observações

- Câmera e microfone usam os widgets nativos do Streamlit (`st.audio_input` e `st.camera_input`):
  o candidato grava a resposta e para a gravação; a foto para leitura de postura é opcional.
- **Navegador**: recomende Chrome ou Edge ao candidato. O gravador do Streamlit depende da API MediaRecorder
  e, em outros navegadores, pode exibir "An error has occurred, please try again" ao parar a gravação.
  O microfone só é liberado em `localhost` ou em HTTPS; pelo IP da rede sem HTTPS o navegador bloqueia.
- O avatar em vídeo do HeyGen e o avatar 3D (TalkingHead) da versão anterior dependiam de SDKs
  JavaScript e não existem nesta versão; os formatos disponíveis são foto, bola falante e juiz em vídeo (clipes).
- Sessões abandonadas são liberadas automaticamente após `minutos_sem_sinal` (configurável no painel).

## Sobre o banco de questões

As 292 perguntas vêm de arguições orais reais do concurso de Promotor de Justiça do MP-SP, que são
públicas. O arquivo distribuído aqui é **anonimizado**: ficam a pergunta, o gabarito, os pontos-chave,
os fundamentos legais, a matéria, o tema e o encadeamento entre pergunta principal e desdobramentos.

Não ficam a transcrição literal da fala dos candidatos, a colocação de cada um no concurso, a reação
do examinador nem a referência ao vídeo e ao instante da gravação. O identificador de cadeia é opaco,
o que preserva o agrupamento sem apontar para a gravação de origem. O conversor (`simulador/banco_questoes.py`)
descarta esses campos mesmo que apareçam num arquivo importado pelo painel. Ver `db/anonimizar_banco.py`.

### Amostra do banco

Para testes rápidos, demonstrações ou uma carga menor no Chroma Cloud, há uma amostra pronta em
`banco de questoes finais/banco_amostra.json`: 40 questões, 4 provas de 10, com a mesma proporção
início/meio/fim e as cadeias preservadas. Uma prova de 10 perguntas sai idêntica à do banco completo.

```bash
python db/amostra_banco.py                    # regenera a amostra (reproduzível pela semente)
python db/amostra_banco.py --questoes 60 --provas 6
python db/importar_banco.py --arquivo "banco de questoes finais/banco_amostra.json" \
  --nome "MP-SP — amostra" --vetorizar
```

O banco completo continua intacto em `banco_final.json`.
