# VisionAgro — Relatório de Engenharia e Plano de Melhorias

**Versão:** 2.0 · **Data:** 01/11/2026
**Objetivo declarado:** produto real para produtores rurais
**Horizonte:** 13–17 semanas a 5–10 h/semana
**Base analisada:** repositório local `~/Documentos/VisionAgro` (commit `02fbb82`)

> **Mudanças da v1.0 para a 2.0**
> 1. Fase 0 verificada e concluída no código — removida do roadmap.
> 2. Google Gemini substituído pelo gateway de inferência do OpenCode (seção 2.4).
> 3. Nova task de validação do modelo (T2.2) antes de migrar o código.
> 4. Nova seção sobre por que "seguir o documento" não é automático.

---

## 0. Status atual

| Item | Situação |
|---|---|
| Credencial do Neon hardcoded | ✅ removida — `grep` não encontra `npg_` nem `postgresql://` |
| `JWT_SECRET` com fallback | ✅ agora falha com `RuntimeError` se ausente ou < 32 caracteres |
| `/api/v1/debug-gemini` | ✅ removido |
| Rate limit por usuário | ✅ implementado (`registrar_analise_com_limite`, 20/h e 100/dia, `Retry-After`) |
| `.env.example` | ✅ corrigido, sem Supabase, com `JWT_SECRET` documentado |

**Fase 0 encerrada.** O que resta é F1 → F8.

### Como usar este documento

1. Leia a seção 2.4 antes de qualquer coisa — é a decisão de fornecedor de IA.
2. Siga as fases em ordem. Cada task é atômica e cabe em uma sessão.
3. Para cada task, cole no seu assistente o **Prompt padrão** + o bloco **Prompt** da task.
4. Só marque concluída quando todos os critérios de aceite passarem.

### Prompt padrão (cole antes de cada task)

```
Você é engenheiro sênior de software. Repositório: VisionAgro
(FastAPI + psycopg2 + PostgreSQL Neon + deploy Vercel + Raspberry Pi).

Regras de resposta:
- Entregue o arquivo completo ou um diff unificado. Nunca use placeholders ou "TODO".
- Explique em no máximo 3 linhas o que mudou e por quê.
- Liste os comandos exatos para eu testar localmente.
- Não altere arquivos fora dos listados na task.
- Se faltar alguma informação, pergunte antes de escrever código.
- Não introduza dependência nova sem justificar em 1 linha.
```

---

## 1. Sumário executivo

O VisionAgro já é um sistema funcional de ponta a ponta: autenticação com bcrypt e JWT, painel web, captura no campo, análise por IA, persistência em PostgreSQL e deploy serverless. A Fase 0 fechou as três falhas de segurança que impediam qualquer conversa séria sobre produto.

O que resta é **endurecer para operar**. Quatro conclusões:

1. **A camada de IA precisa ser trocada, não ajustada.** O código atual fala REST direto com o Google, com campos em snake_case que a API ignora (`response_mime_type`, `max_output_tokens`), um loop de até ~48 requisições e parsing por regex. Migrar para um provider único, com SDK e saída estruturada, elimina tudo isso de uma vez.
2. **O sistema ainda inventa dados.** Quando o JSON falha, o percentual assume `45.0` fixo. Em laudo agronômico, número fabricado é o pior defeito possível.
3. **A arquitetura de dados não sustenta escala.** Imagem em base64 no Postgres, conexão aberta por query e nunca fechada, sem schema versionado. Funciona com 5 amostras, quebra com 5.000.
4. **O risco maior é regulatório, não técnico.** O sistema não pode emitir diagnóstico nem recomendar produto comercial. Precisa falar em "indícios" e saber dizer "indeterminado".

**Veredito:** não é projeto para reescrever. É projeto para endurecer, na ordem: dados → IA → segurança → campo → rubrica → avaliação → conformidade.

---

## 2. O produto

### 2.1 O que é

Ferramenta de **triagem fitossanitária assistida** para cafeicultura: o robô percorre a lavoura, captura imagens do caule, e o sistema sinaliza **indícios** de doença com severidade, evidências visuais e recomendação de verificação humana.

O valor não está em "diagnosticar". Está em **reduzir o custo de inspeção** e **priorizar onde o produtor olha primeiro**.

### 2.2 O que não pode ser (risco regulatório)

- **Não emitir diagnóstico.** Diagnóstico fitossanitário é ato de responsabilidade técnica. Use "indícios compatíveis com", "suspeita de", "requer confirmação".
- **Não recomendar produto comercial.** O prompt atual diz "manejo com fungicida registrado" — isso beira receita agronômica, que exige profissional habilitado. Remova princípio ativo. No máximo: "consulte um engenheiro agrônomo".
- **Não errar em silêncio.** Falso negativo custa safra; falso positivo custa credibilidade. O sistema precisa saber dizer **"indeterminado"**.
- **Ter termo de uso e disclaimer** visíveis no laudo e na interface.

> **Decisão de produto:** posicionar como *"apoio à decisão e priorização de inspeção"*, nunca como *"laudo"*. Reduz risco jurídico e aumenta a confiança do produtor.

### 2.3 Restrição de campo

Produtor pequeno/médio, conectividade intermitente, Raspberry Pi 4 com câmera, operação por controle remoto. A internet no campo falha: o sistema precisa funcionar offline e sincronizar depois.

---

### 2.4 Modelo e API: a decisão que substitui o Gemini

Você pediu para sair do Gemini e usar o OpenCode. A boa notícia: o OpenCode tem um gateway de inferência próprio, e ele resolve exatamente o seu caso.

#### O endpoint

O gateway fica em `https://opencode.ai/inference` e expõe três famílias de API:

| API | Endpoint | Modelos |
|---|---|---|
| OpenAI Chat Completions | `POST https://opencode.ai/inference/openai/v1/chat/completions` | Qwen, GLM, DeepSeek, MiniMax, Kimi, Mistral, free models |
| OpenAI Responses | `POST https://opencode.ai/inference/openai/v1/responses` | GPT 6.x, Grok, Muse |
| Anthropic Messages | `POST https://opencode.ai/inference/anthropic/v1/messages` | Claude, Qwen3.8 Flash |

Autenticação: `Authorization: Bearer <token>`, com chave pessoal criada no Console (`https://opencode.ai/console`).

Lista viva de modelos: `curl https://opencode.ai/inference/v1/models`

#### ⚠️ A pegadinha que quase todo mundo cai

> **Modelos gratuitos só funcionam de dentro do OpenCode.** De um cliente externo (o seu FastAPI), a resposta é **HTTP 403**, mesmo com chave válida.

Ou seja: `nemotron-3.5-super-vl-free` é excelente para testar no chat, mas **não serve para o produto**. Para o app, use modelo pago ou assinatura Go. Se você já tem OpenCode Go, o consumo conta na franquia do plano e o custo reportado vem como `0` dentro dos limites.

#### A recomendação

Seu caso exige, ao mesmo tempo: **visão** (ler a foto), **contexto longo** (a rubrica inteira), **saída estruturada** (JSON confiável) e **custo baixo** (muitas imagens).

| Papel | Modelo | Preço (in/out por 1M) | Por quê |
|---|---|---|---|
| **Principal** | `claude-haiku-5-5` | $0,10 / $0,50 (≤100K) | Melhor relação visão × custo × obediência a instrução; forte em citar fonte e admitir incerteza |
| **Fallback / comparação** | `gpt-6-luna` | $0,10 / $0,50 (≤272K) | Mesmo patamar de preço, contexto maior, ótimo em saída estruturada |
| **Econômico em escala** | `qwen3.8-flash` | $0,15 / $0,47 | Alternativa barata para testar na F6 |
| **Não usar** | modelos `-free` | — | HTTP 403 fora do OpenCode |
| **Evitar no início** | `claude-sonnet-5-5`, `gpt-6-sol`, `gemini-4-argon` | $2 / $10 | 20× mais caro; só faz sentido como escalonamento depois da F6 |

#### A conta

Uma análise típica: imagem 1024 px (~1.000 tokens) + rubrica (~2.000) + prompt (~500) + saída (~300).

- Entrada ≈ 3.500 tokens → 3.500 × $0,10/1M = **$0,00035**
- Saída ≈ 300 tokens → 300 × $0,50/1M = **$0,00015**
- **Total ≈ $0,0005 por análise** (≈ R$ 0,003)

Com 10.000 análises/mês: **≈ $5**. O custo não é o problema — o problema seria usar Sonnet por padrão sem necessidade.

#### Arquitetura de integração (sem lock-in)

Não chame o endpoint espalhado pelo código. Crie um adaptador:

```
ia/
  provider.py      # interface: analisar(imagem, rubrica, prompt) -> Resultado
  openai_compat.py # implementação OpenAI Chat Completions (padrão)
  anthropic.py     # implementação Anthropic Messages (se necessário)
  schemas.py       # Pydantic do resultado
  registry.py      # escolhe o provider/modelo por variável de ambiente
```

Variáveis:

```env
IA_PROVIDER=openai_compat
IA_BASE_URL=https://opencode.ai/inference/openai/v1
IA_API_KEY=...
IA_MODEL=claude-haiku-5-5
IA_MODEL_FALLBACK=gpt-6-luna
```

Assim você troca de modelo mudando uma variável, e a F6 pode comparar modelos sem tocar na aplicação.

> **Nota técnica:** a documentação do OpenCode diz que todo modelo de texto também funciona pelas outras APIs, com tradução do gateway. Para **imagem**, valide antes: a T2.2 existe exatamente para isso. Se a tradução não aceitar imagem no endpoint OpenAI, use o endpoint nativo da família (Anthropic para Claude, Responses para GPT).

#### Privacidade e LGPD (não ignore)

Os modelos são hospedados nos EUA e na UE. OpenAI e Anthropic **retêm requisições por 30 dias**. Você vai enviar fotos de propriedades rurais — que podem conter localização, pessoas e dados do produtor.

Isso não impede o produto, mas exige: aviso no termo de uso, base legal definida, e remoção de EXIF/GPS antes do envio (já previsto na T2.8). Se algum cliente exigir retenção zero, será preciso um provider com essa garantia ou modelo self-hosted — decisão para depois da F6.

#### Por que "a IA só vai julgar conforme o documento" não acontece sozinho

Esse é o ponto conceitual mais importante do relatório.

Dar o PDF para o modelo **não** o impede de interpretar. Ele continua decidindo, pixel a pixel, se aquela mancha corresponde ao critério "lesão necrótica com halo amarelado". O documento **restringe** o espaço de resposta; não elimina o julgamento.

Para o sistema realmente julgar "conforme o documento", são necessários quatro mecanismos, e nenhum é opcional:

1. **Rubrica operacional** — o PDF precisa virar critérios verificáveis (o que observar, em que quantidade, com qual limiar). Texto corrido de PDF não serve como régua.
2. **Citação obrigatória** — toda saída aponta `documento`, `página` e `trecho` que fundamentou a decisão. Sem citação, a saída é inválida.
3. **Abstenção obrigatória** — se nenhum critério for observável na imagem, a resposta é `indeterminado`. O modelo precisa ser explicitamente autorizado a não concluir.
4. **Avaliação contra gabarito humano** — sem comparar com o que um agrônomo disse, você não tem evidência de que o sistema segue o documento. Tem apenas a impressão de que segue.

Os quatro estão nas Fases 5 e 6. A Fase 2 apenas prepara o terreno.

---

## 3. Diagnóstico técnico (pós-Fase 0)

### 3.1 Segurança — resolvido na Fase 0

| ID | Achado | Status |
|---|---|---|
| S1 | Credencial do Neon hardcoded | ✅ resolvido |
| S2 | `JWT_SECRET` com default | ✅ resolvido |
| S3 | `/debug-gemini` público | ✅ resolvido |

Restam itens menores, tratados na Fase 3: cookie sem `Secure`, ausência de CSRF, senha mínima de 6, sem lockout de login, headers incompletos.

### 3.2 Dados — 5 problemas estruturais

| ID | Achado | Evidência | Impacto |
|---|---|---|---|
| D1 | Imagem em base64 dentro do Postgres | `pi_sync.py:106`, `main.py:343` | Banco inflado, queries lentas, backup caro |
| D2 | Conexão aberta por query e nunca fechada | `database.py` (todas as funções) | `with conn` gerencia transação, **não** fecha conexão → esgota o pool do Neon |
| D3 | Sem schema versionado nem migrations | ausência de `.sql`/Alembic | Schema só existe no Neon; impossível reproduzir |
| D4 | Sem índices e sem paginação | `database.py:119-127` | Full scan em `ORDER BY created_at`; `/amostras` devolve tudo |
| D5 | Modelo de dados raso | tabela `amostras` mistura captura, laudo e status | Sem fazenda, talhão, histórico nem versionamento |

### 3.3 IA — 6 problemas

| ID | Achado | Evidência | Impacto |
|---|---|---|---|
| A1 | Campos REST em snake_case são ignorados | `main.py:409-413` | JSON mode e limite de tokens **não funcionam** |
| A2 | Percentual fabricado no fallback | `main.py:507` e `509` | Laudo com número inventado |
| A3 | Até ~48 requisições sequenciais | `main.py:434-460` | Estoura o timeout da Vercel; custo e latência altos |
| A4 | Listagem de modelos a cada análise | `main.py:395` | Chamada de rede extra por requisição |
| A5 | Sem versão de prompt/modelo registrada | `main.py:528` | Impossível auditar por que um laudo mudou |
| A6 | Sem abstenção, confiança, evidências ou citação | `main.py:363-390` | Saída não auditável nem defensável |

### 3.4 Operação de campo — 3 problemas

| ID | Achado | Evidência | Impacto |
|---|---|---|---|
| O1 | O Pi escreve direto no banco com credencial de owner | `pi_sync.py:52-58` | Dispositivo de campo com poder total sobre o banco |
| O2 | Sem idempotência | `pi_sync.py:110-117` | Reenvio duplica amostras |
| O3 | Interface de captura não funciona | `VisionAgro-capturar/index.html:108`, `:188` | Usa `url_for('video_feed')` e POST `/capturar`; **nenhuma das duas rotas existe** |

### 3.5 Estrutura

- `api/templates/` é cópia exata de `VisionAgro/templates/`.
- Dois `requirements.txt` idênticos, sem versões fixas (exceto `Jinja2==3.0.3`, antigo).
- Sem `Dockerfile`, CI, testes ou `maxDuration` no `vercel.json`.

### 3.6 O que já está bom

- Separação `main.py` / `database.py` clara e legível.
- SQL sempre parametrizado — sem injeção.
- bcrypt para senha, JWT para sessão, rate limit funcional.
- Middleware de headers de segurança.
- Histórico de commits mostra iteração e depuração reais.
- Deploy serverless funcionando.

---

## 4. Arquitetura alvo

```
┌──────────────────────────────┐
│ Raspberry Pi 4 + câmera      │
│ - fila local (SQLite)        │
│ - retry com backoff          │
│ - token de dispositivo       │
└──────────────┬───────────────┘
               │ HTTPS (multipart, idempotente por hash)
               ▼
┌──────────────────────────────────────────────┐
│ API FastAPI (Vercel)                         │
│  /auth        login, sessão, CSRF            │
│  /amostras    upload, listagem paginada      │
│  /analises    disparo + consulta             │
│  /health      healthcheck                    │
└───────┬───────────────────────┬──────────────┘
        │                       │
        ▼                       ▼
┌───────────────┐      ┌──────────────────────┐
│ PostgreSQL    │      │ Object Storage (R2)  │
│ (Neon)        │      │ imagens + presigned  │
│ usuarios      │      └──────────────────────┘
│ fazendas      │
│ talhoes       │      ┌──────────────────────┐
│ amostras      │      │ ia/ (adaptador)      │
│ analises      │◄─────┤ OpenCode Inference   │
│ eventos       │      │ + rubrica versionada │
└───────────────┘      └──────────────────────┘
```

Princípios:

1. **O dispositivo nunca fala com o banco.** Fala com a API, autenticado, com idempotência.
2. **Imagem não mora no banco.** Banco guarda chave, hash e metadados.
3. **Toda análise é versionada e reproduzível.** Modelo, prompt e rubrica registrados.
4. **Toda saída é auditável.** Evidência, confiança e fonte — ou abstenção explícita.
5. **Nada falha em silêncio.** Erro vira status + evento, nunca número inventado.
6. **Provider de IA é trocável por variável de ambiente.**

---

## 5. Roadmap

| Fase | Nome | Tasks | Esforço | Semanas (5–10h) |
|---|---|---|---|---|
| ~~F0~~ | ~~Contenção de segurança~~ | ~~5~~ | ~~4 h~~ | ✅ concluída |
| **F1** | Fundação de dados | 7 | ~24 h | 1–3 |
| **F2** | Migração e confiabilidade da IA | 9 | ~26 h | 4–6 |
| **F3** | Segurança da aplicação | 6 | ~12 h | 6–7 |
| **F4** | Operação de campo | 5 | ~16 h | 7–9 |
| **F5** | Rubrica e citação | 4 | ~16 h | 9–11 |
| **F6** | Avaliação e métricas | 3 | ~14 h | 11–13 |
| **F7** | Conformidade e operação | 4 | ~12 h | 13–15 |
| **F8** | Documentação | 3 | ~6 h | 15–16 |

**Total restante:** 41 tasks · ~126 h · 13–17 semanas.

> Regra de ouro: **não comece a F2 antes de fechar a F1.** Trocar o provider em cima de base instável é retrabalho garantido.

---

# 6. Tasks

## FASE 1 — Fundação de dados

### T1.1 — Schema versionado e runner de migrations
**Esforço:** 4 h

**Por quê:** hoje o schema existe só no Neon. Sem migrations, você não reproduz o banco nem faz deploy seguro.

**Arquivos (novos):** `db/migrations/001_init.sql`, `db/migrate.py`, `README.md`

**Passos:**
1. Criar `schema_version (versao int primary key, aplicada_em timestamptz)`.
2. `migrate.py` lê os `.sql` em ordem, aplica pendentes em transação e registra.
3. `001_init.sql` cria o schema da seção 7.
4. Comando: `python db/migrate.py`.

**Aceite:**
- [ ] Banco vazio + `python db/migrate.py` = schema completo
- [ ] Rodar duas vezes não quebra
- [ ] `schema_version` registra a versão aplicada

**Prompt:**
```
Tarefa T1.1: crie db/migrations/001_init.sql com o schema da seção 7 do
relatório e db/migrate.py, um runner que aplica migrations em ordem, em
transação, com tabela schema_version, idempotente. Use psycopg2 e
DATABASE_URL do ambiente. Mostre os arquivos completos e os comandos.
```

---

### T1.2 — Modelo de dados completo
**Esforço:** 4 h

**Por quê:** `amostras` mistura captura, laudo e status. Isso impede histórico, reprocessamento e relatório por talhão.

**Arquivos:** `db/migrations/002_modelo.sql`, `VisionAgro/database.py`

**Passos:**
1. Criar `fazendas`, `talhoes`, `analises`, `eventos`, `dispositivos`.
2. Migrar `amostras` para o novo formato (`talhao_id`, `imagem_key`, `imagem_hash`, `capturada_em`).
3. Reescrever as funções de `database.py`.

**Aceite:**
- [ ] Existe 1:N entre `amostras` e `analises`
- [ ] Nenhuma coluna guarda base64
- [ ] Dashboard continua funcionando

**Prompt:**
```
Tarefa T1.2: crie db/migrations/002_modelo.sql com fazendas, talhoes,
analises, eventos e dispositivos conforme a seção 7, e migre amostras para
o novo formato. Depois atualize VisionAgro/database.py, mantendo os nomes
públicos das funções quando possível. Mostre migration + diff.
```

---

### T1.3 — Connection pool e correção do vazamento
**Esforço:** 3 h

**Por quê:** `with get_connection() as conn` **não fecha** a conexão em psycopg2 — gerencia só a transação. Com o tempo o Neon esgota e o app para.

**Arquivos:** `VisionAgro/database.py`

**Passos:**
1. Criar `SimpleConnectionPool` em nível de módulo (`minconn=1`, `maxconn=5`).
2. Criar `@contextmanager def conexao()` que pega do pool e devolve no `finally`.
3. Trocar todas as funções.

**Aceite:**
- [ ] Nenhum `psycopg2.connect` fora do pool
- [ ] 100 requisições seguidas não esgotam conexões
- [ ] `pg_stat_activity` volta ao baseline

**Prompt:**
```
Tarefa T1.3: em VisionAgro/database.py, substitua a abertura por query por
um SimpleConnectionPool em nível de módulo e um contextmanager que devolve
a conexão no finally. Explique por que o `with conn` atual não fecha a
conexão. Mostre o diff e um teste de 100 chamadas.
```

---

### T1.4 — Mover imagens para object storage
**Esforço:** 6 h

**Por quê:** base64 no Postgres infla o banco e encarece backup. A imagem precisa existir (auditoria e reprocessamento), mas não ali. **Atenção:** guardar a foto para auditoria é diferente de montar dataset de treino — você não quer treinar modelo, e este relatório não propõe isso.

**Arquivos:** `VisionAgro/storage.py` (novo), `main.py`, `pi_sync.py`, `requirements.txt`

**Passos:**
1. Criar bucket no Cloudflare R2 (S3-compatible, free tier).
2. `storage.py` com `upload(bytes, key) -> key` e `url_assinada(key, ttl)`.
3. Gravar `imagem_key` + `imagem_hash` (sha256).
4. Endpoint de imagem devolve URL assinada de curta duração.
5. Script de migração das imagens antigas.

**Aceite:**
- [ ] `imagem_url` não recebe mais `data:image/...`
- [ ] Dashboard exibe via URL assinada
- [ ] Banco não cresce ao adicionar 100 amostras

**Prompt:**
```
Tarefa T1.4: crie VisionAgro/storage.py usando boto3 contra Cloudflare R2,
com upload(bytes, key) e url_assinada(key, ttl_segundos). Adapte main.py e
pi_sync.py para gravar apenas imagem_key e imagem_hash (sha256). O endpoint
de imagem deve redirecionar para URL assinada de 15 min. Inclua script de
migração das imagens base64 existentes. Mostre tudo.
```

---

### T1.5 — Índices, paginação e agregação em SQL
**Esforço:** 3 h

**Passos:**
1. Índices: `amostras(talhao_id, capturada_em desc)`, `analises(amostra_id, criada_em desc)`, `usuarios(email)`.
2. `/amostras` com `limit`/`offset` (default 20, máx 100).
3. Contadores do dashboard via `COUNT(*) FILTER`.

**Aceite:**
- [ ] `/amostras` sem paginação retorna default 20
- [ ] Dashboard faz 1 query agregada
- [ ] `EXPLAIN ANALYZE` usa índice

**Prompt:**
```
Tarefa T1.5: adicione os índices indicados, paginação em GET
/api/v1/amostras (limit default 20, max 100) e troque os contadores do
dashboard por uma query agregada com COUNT(*) FILTER. Mostre o EXPLAIN
ANALYZE antes e depois.
```

---

### T1.6 — Migrar dados existentes
**Esforço:** 2 h

**Passos:** script que cria fazenda/talhão padrão, converte base64 → R2, preenche `imagem_key`/`hash` e cria uma `analise` por amostra já analisada (`modelo="legado"`, `prompt_versao="v0"`). Suporta `--dry-run`.

**Aceite:**
- [ ] `--dry-run` não altera nada
- [ ] Nenhuma amostra órfã após rodar
- [ ] Contagem antes = depois

**Prompt:**
```
Tarefa T1.6: escreva db/migrar_dados.py que converte amostras antigas para
o novo modelo (fazenda/talhao padrão, upload ao R2, imagem_key/hash, uma
analise com modelo="legado" e prompt_versao="v0"). Suporte --dry-run.
Mostre o script e a saída esperada.
```

---

### T1.7 — Backup e teste de restore
**Esforço:** 2 h

**Passos:** backup diário (Neon ou `pg_dump` para R2), `scripts/backup.sh`, `scripts/restore.sh`, restore validado em banco separado.

**Aceite:**
- [ ] Backup diário com retenção definida
- [ ] Restore completo validado
- [ ] Procedimento no runbook

**Prompt:**
```
Tarefa T1.7: crie scripts/backup.sh (pg_dump comprimido + upload R2) e
scripts/restore.sh (restaura em banco alvo). Documente como validar a
contagem de linhas após o restore. Mostre os scripts completos.
```

---

## FASE 2 — Migração e confiabilidade da IA

### T2.1 — Adaptador de provider (substitui o Gemini)
**Esforço:** 5 h

**Por quê:** hoje o código fala REST direto com o Google, com campos que a API ignora e um loop de até ~48 requisições. Um adaptador único resolve isso e tira o lock-in.

**Arquivos (novos):** `VisionAgro/ia/__init__.py`, `provider.py`, `openai_compat.py`, `schemas.py`, `registry.py`
**Arquivos alterados:** `main.py`, `requirements.txt`, `.env.example`

**Passos:**
1. Definir a interface `Provider.analisar(imagem_bytes, rubrica, prompt) -> ResultadoIA`.
2. Implementar `OpenAICompatProvider` usando o SDK `openai` apontando para `https://opencode.ai/inference/openai/v1`.
3. `registry.py` escolhe provider/modelo por `IA_PROVIDER`, `IA_BASE_URL`, `IA_API_KEY`, `IA_MODEL`, `IA_MODEL_FALLBACK`.
4. Remover `get_gemini_client`, `obter_modelos_disponiveis`, o loop de modelos e todo o parsing por regex.
5. Saída validada por Pydantic (`ResultadoIA.model_validate_json`).

**Aceite:**
- [ ] Nenhuma referência a `generativelanguage.googleapis.com` no código
- [ ] Nenhum `re.sub`/`re.search` no caminho de parsing
- [ ] Trocar `IA_MODEL` muda o modelo sem alterar código
- [ ] Falha do provider retorna erro claro, não texto livre

**Prompt:**
```
Tarefa T2.1: crie VisionAgro/ia/ com a interface Provider, uma
implementação OpenAICompatProvider usando o SDK openai contra
https://opencode.ai/inference/openai/v1, schemas Pydantic e um registry
que escolhe provider/modelo por variável de ambiente. Remova o cliente
Gemini, a descoberta de modelos, o loop de tentativas e o parsing por
regex de main.py. Mostre todos os arquivos e um teste de chamada.
```

---

### T2.2 — Validar visão e saída estruturada no modelo escolhido
**Esforço:** 2 h

**Por quê:** a documentação do OpenCode diz que modelos de texto funcionam em qualquer API do gateway por tradução — mas **imagem** precisa ser validada. Descobrir isso depois de migrar tudo custa uma semana.

**Arquivos (novo):** `scripts/smoke_ia.py`

**Passos:**
1. Script que envia uma imagem de caule + pergunta simples e exige JSON.
2. Rodar contra `claude-haiku-5-5` e `gpt-6-luna`.
3. Medir: aceita imagem? respeita schema? latência? custo reportado?
4. Se o endpoint OpenAI não aceitar imagem, testar o endpoint nativo (Anthropic Messages / Responses).
5. Registrar o resultado numa tabela no README.

**Aceite:**
- [ ] Pelo menos 1 modelo aceita imagem e retorna JSON válido
- [ ] Latência e custo medidos e registrados
- [ ] Endpoint escolhido documentado

**Prompt:**
```
Tarefa T2.2: crie scripts/smoke_ia.py que envia uma imagem JPEG e um prompt
exigindo JSON contra https://opencode.ai/inference, testando
claude-haiku-5-5 e gpt-6-luna nos endpoints OpenAI Chat Completions,
Anthropic Messages e OpenAI Responses. Reporte: aceita imagem, respeita o
schema, latência e custo. Mostre o script e uma tabela de resultados.
```

---

### T2.3 — Remover o percentual inventado e implementar abstenção
**Esforço:** 2 h

**Por quê:** `45.0` fixo quando o parse falha é dado fabricado em laudo agronômico.

**Arquivos:** `ia/schemas.py`, `main.py`, migration `003_abstencao.sql`

**Passos:**
1. `percentual_afetacao` passa a ser `nullable`.
2. Sem percentual → gravar `NULL`, UI mostra "não estimado".
3. Adicionar `indeterminado` ao enum de saída.
4. Instruir o modelo a preferir `indeterminado` quando a evidência for insuficiente.
5. Nunca preencher número por default.

**Aceite:**
- [ ] Nenhum literal `45.0` como fallback
- [ ] Caso sem percentual grava `NULL`
- [ ] Caso ambíguo retorna `indeterminado`

**Prompt:**
```
Tarefa T2.3: remova o fallback percentual=45.0. Torne percentual_afetacao
nullable, adicione "indeterminado" ao enum e instrua o modelo a usar
indeterminado quando não houver evidência suficiente. Atualize a UI para
"não estimado". Mostre o diff e 3 casos de teste.
```

---

### T2.4 — Saída auditável: evidências, confiança e fonte
**Esforço:** 3 h

**Arquivos:** `ia/schemas.py`, `db/migrations/004_auditoria.sql`, templates

**Passos:**
1. Schema: `evidencias: list[str]`, `confianca: float (0–1)`, `fonte: {documento, pagina, trecho}`.
2. Prompt exige descrever a evidência visual **antes** de classificar.
3. UI mostra evidências e confiança.
4. `confianca < 0.6` → "requer verificação humana".

**Aceite:**
- [ ] Toda análise tem ao menos 1 evidência textual
- [ ] Confiança exibida na UI
- [ ] Confiança < 0.6 sinaliza revisão

**Prompt:**
```
Tarefa T2.4: estenda o schema com evidencias, confianca (0-1) e fonte
(documento, pagina, trecho). No prompt, exija descrever a evidência visual
antes de classificar. Atualize migration e dashboard para exibir e
sinalizar revisão quando confianca < 0.6. Mostre tudo.
```

---

### T2.5 — Log de inferência e custo real
**Esforço:** 3 h

**Arquivos:** `ia/provider.py`, `db/migrations/005_log.sql`

**Passos:**
1. Gravar por análise: `modelo`, `prompt_versao`, `rubrica_versao`, `latencia_ms`, `tokens_entrada`, `tokens_saida`, `custo_usd`, `sucesso`, `erro`.
2. Usar o campo `usage.cost` que o gateway retorna — não estime.
3. Endpoint `/api/v1/analises/{id}`.

**Aceite:**
- [ ] Toda chamada gera linha, inclusive falhas
- [ ] Custo vem do `usage`, não de tabela manual
- [ ] "Quanto gastei este mês" responde com uma query

**Prompt:**
```
Tarefa T2.5: registre em analises modelo, prompt_versao, rubrica_versao,
latencia_ms, tokens_entrada, tokens_saida, custo_usd, sucesso e erro.
Use o campo usage.cost retornado pelo gateway do OpenCode, não uma tabela
de preços manual. Crie GET /api/v1/analises/{id}. Mostre migration, código
e a query de custo mensal.
```

---

### T2.6 — Timeout, retry e circuit breaker
**Esforço:** 3 h

**Por quê:** hoje são até ~48 requisições sequenciais de 15 s. Na Vercel isso estoura o limite da função.

**Passos:**
1. Timeout total por análise: 25 s.
2. Retry apenas em 429/5xx, backoff exponencial (máx. 2).
3. Circuit breaker: 5 falhas em 60 s abre por 60 s.
4. `maxDuration` no `vercel.json`.

**Aceite:**
- [ ] Nenhuma análise passa de 30 s
- [ ] 429 não é tratado como falha definitiva
- [ ] Circuito aberto é observável em log

**Prompt:**
```
Tarefa T2.6: implemente timeout total de 25s por análise, retry com
backoff apenas para 429/5xx (máx 2) e circuit breaker (5 falhas em 60s abre
por 60s). Adicione maxDuration ao vercel.json. Mostre o código e como
simular cada cenário.
```

---

### T2.7 — Prompt versionado em arquivo
**Esforço:** 2 h

**Arquivos:** `prompts/v1.txt`, `ia/provider.py`

**Passos:** mover prompt para arquivo com cabeçalho de versão e data; gravar hash em `analises.prompt_versao`; proibir prompt inline.

**Aceite:**
- [ ] Prompt versionado no Git
- [ ] Cada análise registra a versão
- [ ] Mudar o prompt muda o hash

**Prompt:**
```
Tarefa T2.7: mova o prompt para prompts/v1.txt com cabeçalho de versão e
data. Grave o hash do conteúdo em analises.prompt_versao. Remova prompt
inline. Mostre o arquivo e o diff.
```

---

### T2.8 — Validação e pré-processamento de imagem
**Esforço:** 3 h

**Passos:**
1. Validar formato (JPEG/PNG), tamanho máx. 10 MB, dimensão mín. 640 px.
2. Remover EXIF (inclui GPS — relevante para LGPD e para o envio a provider nos EUA).
3. Redimensionar para 1024 px, qualidade 85, determinístico.
4. Rejeitar imagem escura/dessfocada (variância do Laplaciano).

**Aceite:**
- [ ] Upload de PDF ou 20 MB retorna 400 com motivo
- [ ] EXIF não sobrevive
- [ ] Imagem desfocada é sinalizada antes de gastar chamada de IA

**Prompt:**
```
Tarefa T2.8: crie VisionAgro/imagem.py com validação (formato, <=10MB,
>=640px), remoção de EXIF, resize determinístico para 1024px e detecção de
desfoque por variância do Laplaciano. Integre antes da chamada de IA e
retorne 400 com motivo. Mostre o módulo e os testes.
```

---

### T2.9 — Teto de custo por usuário e por dia
**Esforço:** 3 h

**Passos:**
1. Orçamento mensal por usuário (configurável, default R$ 20).
2. Somar `custo_usd` do mês antes da análise.
3. Bloquear com 402/429 e mensagem clara.
4. Query de custo agregado por usuário/dia.

**Aceite:**
- [ ] Usuário no limite é bloqueado antes de chamar a IA
- [ ] Custo agregado consultável
- [ ] Limite configurável por env

**Prompt:**
```
Tarefa T2.9: implemente teto de custo mensal por usuário (configurável por
env, default R$20). Some custo_usd do mês antes da análise e bloqueie com
402 e mensagem clara. Crie query de custo agregado por usuário e dia.
Mostre o código e os testes de limite.
```

---

## FASE 3 — Segurança da aplicação

### T3.1 — Cookies e sessão
**Esforço:** 2 h · **Passos:** `secure=True`, `samesite="lax"`, `max_age=86400`; logout invalida via `tokens_revogados`.
**Aceite:** cookie `Secure` em produção · logout invalida na hora · expira em 24 h.
**Prompt:**
```
Tarefa T3.1: ajuste o cookie para secure=True, samesite=lax, max_age=24h.
Implemente revogação no logout com tabela tokens_revogados verificada no
decode. Mostre o diff e os testes.
```

---

### T3.2 — CSRF nos formulários
**Esforço:** 2 h · **Passos:** token por sessão, campo hidden, validação no POST.
**Aceite:** POST sem token → 403 · token único por sessão · login/cadastro funcionam.
**Prompt:**
```
Tarefa T3.2: implemente proteção CSRF nos formulários de login e cadastro
(token por sessão em campo hidden, validação no POST, 403 se ausente).
Mostre o diff e o teste de POST sem token.
```

---

### T3.3 — Lockout de login
**Esforço:** 2 h · **Passos:** 5 falhas por e-mail/IP em 15 min → 429; mensagem genérica.
**Aceite:** 6ª tentativa → 429 · mensagem não revela existência do e-mail · bloqueio expira.
**Prompt:**
```
Tarefa T3.3: adicione lockout de login: 5 falhas por email/IP em 15 min,
bloqueio com 429 e mensagem genérica que não revele se o email existe.
Registre o evento. Mostre o código e o teste.
```

---

### T3.4 — Validação de e-mail e senha
**Esforço:** 1 h · **Passos:** formato de e-mail; senha mín. 8 com letra e número; máx. 72 bytes (bcrypt).
**Aceite:** e-mail inválido rejeitado · senha fraca rejeitada · senha > 72 bytes rejeitada (não truncada).
**Prompt:**
```
Tarefa T3.4: valide email (formato) e senha (min 8, letra e numero, max 72
bytes por causa do bcrypt) no cadastro, com mensagens específicas. Mostre
o diff e os testes.
```

---

### T3.5 — Headers de segurança completos
**Esforço:** 1 h · **Passos:** CSP, HSTS, Referrer-Policy, Permissions-Policy no middleware existente.
**Aceite:** headers presentes em produção · dashboard renderiza sem erro de CSP · `curl -I` confirma.
**Prompt:**
```
Tarefa T3.5: amplie o middleware com CSP, HSTS, Referrer-Policy e
Permissions-Policy. A CSP deve funcionar com os templates atuais (use nonce
se necessário). Mostre o diff e a saída de curl -I.
```

---

### T3.6 — Upload autenticado para o dispositivo
**Esforço:** 4 h · **Passos:** `POST /api/v1/amostras` multipart, token de dispositivo (tabela `dispositivos`), idempotente por `imagem_hash`.
**Aceite:** Pi sem `DATABASE_URL` · reenvio não duplica · token revogável.
**Prompt:**
```
Tarefa T3.6: crie POST /api/v1/amostras (multipart) autenticado por token
de dispositivo (tabela dispositivos com hash e revogação). Idempotente por
imagem_hash: 201 se novo, 200 se já existe. Mostre migration, endpoint e
teste com curl.
```

---

## FASE 4 — Operação de campo

### T4.1 — `pi_sync` como cliente HTTP
**Esforço:** 4 h · **Passos:** reescrever para `POST /api/v1/amostras` com token, timeout e retry; remover `psycopg2`.
**Aceite:** sem `psycopg2` · funciona local e produção · token inválido dá erro claro.
**Prompt:**
```
Tarefa T4.1: reescreva VisionAgro-capturar/pi_sync.py como cliente HTTP do
endpoint POST /api/v1/amostras, com token de dispositivo, timeout e retry.
Remova psycopg2 e qualquer acesso direto ao banco. Mostre o arquivo
completo.
```

---

### T4.2 — Fila local, idempotência e retry
**Esforço:** 4 h · **Passos:** SQLite local (`pendente`, `enviando`, `enviado`, `erro`), backoff exponencial, retomada após reboot, inspeção por comando.
**Aceite:** desligar no meio não perde nem duplica · backoff com teto · fila inspecionável.
**Prompt:**
```
Tarefa T4.2: adicione ao pi_sync uma fila local em SQLite com estados,
backoff exponencial e retomada após reboot. Idempotência por hash. Crie um
comando para inspecionar a fila. Mostre o código completo.
```

---

### T4.3 — systemd, healthcheck e logs
**Esforço:** 3 h · **Passos:** unit `visionagro-sync.service`, restart automático, log com rotação, `GET /health`.
**Aceite:** sobe no boot · reinicia após crash · `/health` cobre banco, storage e IA.
**Prompt:**
```
Tarefa T4.3: crie o unit systemd visionagro-sync.service com restart
automático e logging. Adicione GET /health verificando banco, storage e
provider de IA. Mostre os arquivos e os comandos de instalação.
```

---

### T4.4 — Conectividade confiável
**Esforço:** 1 h · **Passos:** trocar `socket(8.8.8.8)` por chamada a `/health` com timeout de 3 s, tratando captive portal.
**Aceite:** sem internet real não tenta enviar · API fora entra em backoff · não depende de DNS público.
**Prompt:**
```
Tarefa T4.4: substitua a checagem de conectividade por uma chamada a
/health com timeout de 3s, tratando captive portal e API indisponível com
backoff. Mostre o diff.
```

---

### T4.5 — Consertar a interface de captura
**Esforço:** 4 h · **Por quê:** `index.html` usa `url_for('video_feed')` e `POST /capturar`; nenhuma das duas rotas existe.
**Passos:** implementar a opção mais simples funcional — página estática com `getUserMedia` (ou stream MJPEG local no Pi) e upload para a fila.
**Aceite:** página carrega sem erro · captura entra na fila · "Salvar Foto" retorna sucesso real.
**Prompt:**
```
Tarefa T4.5: a página VisionAgro-capturar/index.html usa
url_for('video_feed') e POST /capturar, mas nenhuma rota existe.
Implemente a opção mais simples funcional: página estática com getUserMedia
(ou stream MJPEG local no Pi) e upload para a fila do pi_sync. Mostre os
arquivos completos e como testar no Pi.
```

---

## FASE 5 — Rubrica e citação

### T5.1 — Rubrica estruturada e validada
**Esforço:** 3 h · **Arquivos:** `rubrica/doencas.yaml`, `VisionAgro/rubrica.py`
**Passos:** schema com `doenca`, `criterios_visuais[]`, `limiares_severidade{}`, `fonte{documento,pagina,trecho}`; validação Pydantic; versão semântica.
**Aceite:** YAML inválido falha na inicialização · cada doença tem ≥2 critérios · versão gravada em cada análise.
**Prompt:**
```
Tarefa T5.1: crie rubrica/doencas.yaml com schema (doenca,
criterios_visuais, limiares_severidade, fonte) e VisionAgro/rubrica.py com
validação Pydantic e versão semântica. Preencha com Fusariose e deixe
espaço para novas doenças. Mostre os arquivos.
```

---

### T5.2 — Ingestão do PDF para rubrica
**Esforço:** 5 h · **Passos:** Docling para extrair texto/tabelas; LLM propõe rubrica; **revisão humana obrigatória**; diff versionado.
**Aceite:** PDF gera proposta · nada entra em produção sem revisão registrada · cada critério aponta página.
**Prompt:**
```
Tarefa T5.2: crie um script que usa Docling para extrair texto e tabelas de
um PDF de referência e propõe rubrica/doencas.yaml no schema da T5.1, com
página e trecho de origem. A saída é rascunho para revisão humana, nunca
aplicada automaticamente. Mostre o script e um exemplo.
```

---

### T5.3 — Judge com rubrica, few-shot e citação
**Esforço:** 6 h · **Passos:** prompt recebe rubrica relevante + 2–3 exemplos rotulados; saída cita página/trecho; abstenção obrigatória quando o critério não for observável.
**Aceite:** toda saída cita fonte · remover a rubrica degrada a acurácia (comprovado na F6) · abstenção funciona em imagem ambígua.
**Prompt:**
```
Tarefa T5.3: implemente o judge que recebe a rubrica (T5.1) e 2-3 exemplos
rotulados, exige citação de página/trecho e abstenção quando o critério
não for observável. Mantenha structured output. Mostre o código e 3
exemplos de saída.
```

---

### T5.4 — Decisão sobre RAG
**Esforço:** 2 h · **Passos:** medir tamanho da rubrica. < 30 regras → manter no prompt. > 30 ou multi-cultura → pgvector.
**Aceite:** decisão registrada em ADR com números · se RAG, latência e custo medidos antes/depois.
**Prompt:**
```
Tarefa T5.4: escreva um ADR decidindo entre context stuffing e RAG com
pgvector, com base no tamanho da rubrica e nos números de latência/custo da
F6. Não implemente nada ainda. Mostre o ADR.
```

---

## FASE 6 — Avaliação e métricas

### T6.1 — Conjunto de avaliação com gabarito
**Esforço:** 5 h · **Passos:** 150–300 imagens do campo; 2 anotadores independentes; kappa; divergências resolvidas; conjunto fora do repositório, manifesto versionado.
**Aceite:** ≥150 imagens · kappa ≥ 0.6 · manifesto com hash.
**Prompt:**
```
Tarefa T6.1: crie a estrutura de um conjunto de avaliação (manifesto CSV
com id, caminho, rotulo_1, rotulo_2, rotulo_final) e um script que calcula
concordância kappa entre anotadores. O conjunto fica fora do Git; só o
manifesto e o hash entram. Mostre o script.
```

---

### T6.2 — Harness de avaliação
**Esforço:** 6 h · **Passos:** matriz de confusão; recall por classe (priorizar severo); taxa de abstenção; calibração; custo e latência.
**Aceite:** `python -m eval.run` gera Markdown · métricas por classe · custo por imagem.
**Prompt:**
```
Tarefa T6.2: crie eval/run.py que roda o judge sobre o manifesto da T6.1 e
gera relatório Markdown com matriz de confusão, recall por classe, taxa de
abstenção, calibração (bins de confiança vs acurácia), custo e latência.
Mostre o script e um relatório de exemplo com dados sintéticos.
```

---

### T6.3 — Comparativo de modelos e configurações
**Esforço:** 3 h · **Passos:** comparar `claude-haiku-5-5` vs `gpt-6-luna` vs `qwen3.8-flash`, em zero-shot vs rubrica vs rubrica+few-shot. Tabela final no README.
**Aceite:** tabela com modelos e configurações nas mesmas métricas · conclusão sobre custo-benefício · números reprodutíveis.
**Prompt:**
```
Tarefa T6.3: rode o harness da T6.2 em 3 modelos (claude-haiku-5-5,
gpt-6-luna, qwen3.8-flash) e 3 configurações (zero-shot, rubrica,
rubrica+few-shot). Gere tabela Markdown com acurácia, recall por classe,
abstenção, custo e latência, e uma conclusão de 5 linhas. Mostre a tabela.
```

---

## FASE 7 — Conformidade e operação

### T7.1 — Linguagem de triagem e disclaimer
**Esforço:** 2 h · **Passos:** trocar "diagnóstico/laudo" por "triagem/indício" em UI, prompt e docs; disclaimer fixo; remover recomendação de produto comercial.
**Aceite:** nenhuma tela trata diagnóstico como certeza · disclaimer em todo laudo · nenhum princípio ativo recomendado.
**Prompt:**
```
Tarefa T7.1: revise todos os textos (templates, prompt, README) trocando
diagnóstico/laudo por triagem/indício, adicionando disclaimer de que não
substitui avaliação de engenheiro agrônomo, e removendo qualquer
recomendação de produto comercial. Mostre o diff completo.
```

---

### T7.2 — LGPD: retenção, exclusão e termos
**Esforço:** 4 h · **Passos:** retenção (ex. 24 meses), exclusão de conta e amostras, registro de consentimento, aviso sobre envio de imagem a provider nos EUA/UE e retenção de 30 dias.
**Aceite:** usuário exclui conta e dados · retenção automática documentada · termo publicado.
**Prompt:**
```
Tarefa T7.2: implemente exclusão de conta e de amostras (removendo o objeto
no storage), política de retenção configurável e registro de consentimento.
Inclua no termo de uso o aviso de que imagens são processadas por provider
nos EUA/UE com retenção de 30 dias. Mostre o código e o texto.
```

---

### T7.3 — Observabilidade
**Esforço:** 3 h · **Passos:** logs JSON, Sentry, `request_id`, alerta de taxa de erro.
**Aceite:** erro rastreável por `request_id` · Sentry recebe exceções · alerta quando erro > 5%.
**Prompt:**
```
Tarefa T7.3: adicione logging estruturado em JSON com request_id, integre
Sentry e configure alerta de taxa de erro. Mostre o código e como validar.
```

---

### T7.4 — Healthcheck e status
**Esforço:** 3 h · **Passos:** `/health` com banco, storage e IA; monitor externo com alerta.
**Aceite:** `/health` diferencia componentes · monitor configurado · alerta chega por e-mail/Telegram.
**Prompt:**
```
Tarefa T7.4: implemente /health detalhado (banco, storage, IA) e documente
a configuração de um monitor externo com alerta. Mostre o código e o passo
a passo.
```

---

## FASE 8 — Documentação

### T8.1 — README de produto
**Esforço:** 3 h · **Passos:** problema, público, arquitetura, setup, deploy, limitações, métricas da F6, decisão de provider.
**Aceite:** alguém roda em < 15 min · diagrama presente · limitações declaradas.
**Prompt:**
```
Tarefa T8.1: reescreva o README como documento de produto: problema,
público, arquitetura com diagrama, setup local, deploy, variáveis de
ambiente, decisão de provider de IA, limitações e métricas. Mostre o
arquivo completo.
```

---

### T8.2 — ADRs
**Esforço:** 2 h · **Passos:** 6 decisões: storage de imagem, abstenção, provider/modelo, context stuffing vs RAG, triagem vs diagnóstico, retenção/LGPD.
**Aceite:** 6 ADRs em `docs/adr/` com contexto, decisão, alternativas, consequências.
**Prompt:**
```
Tarefa T8.2: crie docs/adr/ com 6 ADRs (storage de imagem, abstenção,
provider/modelo, context stuffing vs RAG, triagem vs diagnóstico,
retenção/LGPD) no formato contexto/decisão/alternativas/consequências.
Mostre os arquivos.
```

---

### T8.3 — Runbook
**Esforço:** 1 h · **Passos:** banco fora, IA fora, Pi offline, custo estourado, credencial vazada.
**Aceite:** 5 cenários com sintoma, diagnóstico e ação · comando de verificação em cada.
**Prompt:**
```
Tarefa T8.3: escreva docs/runbook.md com procedimentos para banco fora, IA
fora, Pi offline, custo estourado e credencial vazada. Cada cenário com
sintoma, diagnóstico e ação. Mostre o arquivo.
```

---

# 7. Schema alvo

```sql
-- 001_init.sql
create extension if not exists pgcrypto;

create table if not exists schema_version (
  versao int primary key,
  aplicada_em timestamptz not null default now()
);

create table usuarios (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  senha_hash text not null,
  nome text,
  papel text not null default 'produtor',      -- produtor | tecnico | admin
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz
);

create table fazendas (
  id uuid primary key default gen_random_uuid(),
  usuario_id uuid not null references usuarios(id) on delete cascade,
  nome text not null,
  municipio text,
  uf char(2),
  area_ha numeric(10,2),
  criado_em timestamptz not null default now()
);

create table talhoes (
  id uuid primary key default gen_random_uuid(),
  fazenda_id uuid not null references fazendas(id) on delete cascade,
  nome text not null,
  variedade text,
  plantio date,
  criado_em timestamptz not null default now()
);

create table dispositivos (
  id uuid primary key default gen_random_uuid(),
  usuario_id uuid not null references usuarios(id) on delete cascade,
  nome text not null,
  token_hash text not null,
  ultimo_acesso timestamptz,
  revogado_em timestamptz,
  criado_em timestamptz not null default now()
);

create table amostras (
  id uuid primary key default gen_random_uuid(),
  talhao_id uuid not null references talhoes(id) on delete cascade,
  fileira text,
  pe text,
  imagem_key text not null,
  imagem_hash char(64) not null,
  imagem_bytes int,
  capturada_em timestamptz,
  recebida_em timestamptz not null default now(),
  origem text default 'pi',                     -- pi | web
  status text not null default 'pendente',      -- pendente|processando|analisada|erro
  unique (talhao_id, fileira, pe, imagem_hash)
);

create table analises (
  id uuid primary key default gen_random_uuid(),
  amostra_id uuid not null references amostras(id) on delete cascade,
  provider text not null,
  modelo text not null,
  prompt_versao text not null,
  rubrica_versao text,
  doenca text,
  severidade text,                              -- leve|moderada|severa|indeterminado
  percentual_afetacao numeric(5,2),
  confianca numeric(3,2),
  evidencias jsonb,
  fonte jsonb,
  latencia_ms int,
  tokens_entrada int,
  tokens_saida int,
  custo_usd numeric(10,6),
  sucesso boolean not null default true,
  erro text,
  criada_em timestamptz not null default now()
);

create table eventos (
  id bigserial primary key,
  usuario_id uuid references usuarios(id) on delete set null,
  tipo text not null,
  payload jsonb,
  criado_em timestamptz not null default now()
);

create table tokens_revogados (
  jti text primary key,
  expira_em timestamptz not null
);

create index on amostras (talhao_id, capturada_em desc);
create index on analises (amostra_id, criada_em desc);
create index on eventos (usuario_id, criado_em desc);
```

---

# 8. O que NÃO fazer agora

1. **Treinar modelo próprio de visão computacional.** Você não quer, e não precisa: VLM com rubrica resolve. Sem dataset grande e rotulado, um YOLO seu tende a ser pior.
2. **Fine-tuning.** Só depois da F6, com avaliação mostrando falha sistemática.
3. **RAG com pgvector antes da F5.** Se a rubrica cabe no prompt, RAG só adiciona latência e partes móveis.
4. **Usar modelos `-free` do OpenCode no produto.** Retornam HTTP 403 fora do OpenCode.
5. **App mobile.** Web responsiva resolve.
6. **Multi-tenant complexo.** Um usuário = um produtor, por enquanto.
7. **Navegação autônoma do robô.** É outro projeto, com outro risco.
8. **Microserviços.** Monolito FastAPI é a escolha certa nesta escala.

---

# 9. Métricas de sucesso

| Dimensão | Métrica | Meta |
|---|---|---|
| Confiabilidade | Análises sem erro / total | ≥ 98% |
| Latência | p95 por análise | ≤ 12 s |
| Custo | Custo médio por análise | ≤ $0,001 |
| Qualidade | Recall em "severo" | ≥ 0,90 |
| Qualidade | Taxa de abstenção | 5–15% |
| Calibração | Erro médio entre confiança e acerto | ≤ 0,10 |
| Operação | Amostras duplicadas | 0 |
| Operação | Sync de 100 fotos | ≤ 5 min |
| Segurança | Segredos no repositório | 0 |

---

# 10. Riscos e decisões pendentes

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Modelo escolhido não aceitar imagem no endpoint OpenAI | Média | Alto | T2.2 antes de migrar; fallback para endpoint nativo |
| Custo de IA sair do controle | Média | Médio | T2.9 + rate limit já existente |
| Retenção de 30 dias do provider gerar problema de LGPD | Média | Alto | T2.8 (EXIF) + T7.2 (termo e base legal) |
| Timeout da Vercel em imagens grandes | Alta | Médio | T2.6 + T2.8 |
| Laudo errado gerar perda de safra | Média | Alto | Abstenção, confiança, disclaimer, revisão humana |
| Perda de dados do campo | Média | Alto | T1.7 + T4.2 |
| Escopo crescer e nada terminar | Alta | Alto | Seção 8 |

**Decisões que dependem de você:**

1. **Modelo principal:** `claude-haiku-5-5` (recomendado) ou `gpt-6-luna`? Decida após a T2.2, com número.
2. **Object storage:** Cloudflare R2 (recomendado) ou Supabase Storage?
3. **Fonte da rubrica:** qual documento oficial (Embrapa, manual estadual, laudo de agrônomo parceiro)?
4. **Quem revisa a rubrica:** você tem acesso a um engenheiro agrônomo? É o item mais importante da F5 e não tem substituto técnico.
5. **Assinatura OpenCode Go:** você já tem, ou vai usar créditos pay-as-you-go no Console?

---

*Fim do relatório v2.0. Revisar após a T2.2 (validação do modelo).*
