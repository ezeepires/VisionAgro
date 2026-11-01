# VisionAgro 🌿☕

Sistema inteligente para monitoramento, captura no campo e diagnóstico de doenças no cafeeiro usando **Inteligência Artificial (Google Gemini)**, banco **PostgreSQL (Neon.tech)** e deploy serverless na **Vercel**.

---

## 📁 Estrutura do Projeto

| Caminho | Descrição |
|---|---|
| `VisionAgro/` | Backend **FastAPI + Jinja2** (painel web e APIs). |
| `VisionAgro/main.py` | Rotas de autenticação, dashboard, upload e análise com IA. |
| `VisionAgro/database.py` | Acesso ao Neon PostgreSQL, hash bcrypt, JWT e limite de uso. |
| `VisionAgro/templates/` | Telas de Login, Cadastro, Dashboard e Fazendas. |
| `VisionAgro-capturar/` | Módulo de campo para **Raspberry Pi** (`pi_sync.py` + `index.html`). |
| `api/` | Entrypoint serverless da Vercel (`index.py`). |
| `vercel.json` | Rewrites/rotas da Vercel. |
| `RELATORIO-MELHORIAS.md` | Auditoria técnica e plano de melhorias. |

> ⚠️ O código **precisa** ser executado de dentro de `VisionAgro/`, porque os imports (`import database`) e os templates são resolvidos relativos a essa pasta.

---

## ✅ Pré-requisitos

- **Python 3.10+** (testado com 3.12)
- **Git**
- Projeto no **Neon.tech** (PostgreSQL) com as tabelas criadas (veja abaixo)
- Chave de API do **Google AI Studio** (Gemini)

---

## 🧩 1. Preparar o banco (Neon)

No **SQL Editor** do Neon, execute uma vez:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.usuarios (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      text NOT NULL UNIQUE,
    senha_hash text NOT NULL,
    nome       text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.amostras (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id            uuid NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    fileira               text,
    pe                    text,
    imagem_url            text,
    doencas               text,
    percentual_doencas    numeric,
    informacoes_adicionais text,
    status                text DEFAULT 'pendente',
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS amostras_usuario_created_idx
    ON public.amostras (usuario_id, created_at DESC);
```

A tabela `public.eventos` (controle de limite de análises) é criada automaticamente na primeira análise.

---

## ⚙️ 2. Variáveis de Ambiente

Copie o modelo e preencha com suas credenciais:

```bash
cp VisionAgro/.env.example .env
```

Conteúdo do `.env` (na **raiz** do repositório):

```env
DATABASE_URL=postgresql://usuario:senha@ep-xxxx-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require
GEMINI_API_KEY=sua_chave_do_google_ai_studio
JWT_SECRET=chave_com_no_minimo_32_caracteres
```

| Variável | Obrigatória | Origem |
|---|---|---|
| `DATABASE_URL` | Sim | Neon → *Connect* → *Connection string* |
| `GEMINI_API_KEY` | Sim (para análise) | https://aistudio.google.com/apikey |
| `JWT_SECRET` | Sim, ≥ 32 caracteres | gere com o comando abaixo |

Gere o segredo JWT:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> O arquivo `.env` está no `.gitignore` e **nunca** deve ser commitado. `VisionAgro/database.py` carrega tanto `VisionAgro/.env` quanto o `.env` da raiz.

---

## 🚀 3. Executar Localmente (do zero)

```bash
# 1. Clone e entre no repositório
git clone https://github.com/ezeepires/VisionAgro.git
cd VisionAgro

# 2. Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Instale as dependências
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure o .env (seção anterior)

# 5. Suba o servidor
cd VisionAgro
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse:

- **Painel Web:** [http://localhost:8000](http://localhost:8000)
- **Swagger / API:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Reiniciar depois de mudar o `.env`

O `--reload` recarrega apenas código. Variáveis de ambiente exigem reiniciar o processo:

```bash
pkill -f "uvicorn main:app"   # encerra instâncias antigas
cd VisionAgro && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🛠️ Problemas comuns

| Erro | Causa / Solução |
|---|---|
| `[Errno 98] Address already in use` | Porta 8000 ocupada. Veja `ss -ltnp \| grep :8000` e encerre com `pkill -f "uvicorn main:app"` ou use `--port 8001`. |
| `JWT_SECRET ausente ou com menos de 32 caracteres` | Defina `JWT_SECRET` com ≥ 32 caracteres no `.env`. |
| `DATABASE_URL não configurada` | Preencha `DATABASE_URL` no `.env` e reinicie o servidor. |
| `ModuleNotFoundError: database` | Você iniciou o Uvicorn fora de `VisionAgro/`. Use `cd VisionAgro` antes. |
| `relation "public.usuarios" does not exist` | Rode o SQL da seção 1 no Neon. |
| Análise retorna erro de chave Gemini | Verifique `GEMINI_API_KEY` no `.env` e se o modelo está habilitado na conta. |

---

## ☁️ Deploy na Vercel

1. Conecte o repositório GitHub na Vercel (framework: *Other*, entrypoint `api/index.py`).
2. Configure as variáveis `DATABASE_URL`, `GEMINI_API_KEY` e `JWT_SECRET` em **Settings → Environment Variables**.
3. Cada `git push` na `main` dispara um novo deploy.

> A aplicação não inicia sem `JWT_SECRET` com 32+ caracteres. Alterar o valor invalida todas as sessões ativas.

---

## 🍓 Execução no Raspberry Pi (Campo)

1. Coloque as fotos nas pastas das fileiras (ex.: `Fileira_1/Pe_1.jpg`).
2. Defina `DATABASE_URL` no ambiente ou em `VisionAgro-capturar/.env`.
3. Execute o sincronizador:

```bash
cd VisionAgro-capturar
python pi_sync.py
```

O script detecta a internet automaticamente, envia as fotos em Base64 para o Neon e move os arquivos enviados para `./enviadas/`.

---

## 🔐 Segurança

- Nunca commite `.env`, chaves ou strings de conexão reais.
- Antes de cada push, verifique segredos:

```bash
gitleaks detect --source . --no-git
```

- Se uma credencial vazar, **rotacione-a imediatamente** (Neon e Google AI Studio) — reescrever o histórico do Git não invalida chaves já expostas.
- O histórico deste repositório foi consolidado em um único commit para remover credenciais antigas.
