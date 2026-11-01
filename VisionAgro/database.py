"""
database.py - Módulo de Conexão e Banco de Dados (Neon PostgreSQL)
Responsável por:
1. Conectar ao PostgreSQL no Neon.
2. Cadastrar e autenticar usuários (com hash de senha bcrypt e tokens JWT).
3. Consultar e atualizar amostras de café.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import jwt
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
load_dotenv(dotenv_path=BASE_DIR.parent / ".env")
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
if len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET ausente ou com menos de 32 caracteres. Defina uma chave forte na Vercel e no .env.")
JWT_ALGORITHM = "HS256"


# ==========================================================
# 1. CONEXÃO COM O BANCO DE DADOS
# ==========================================================

def get_connection():
    """Abre e retorna uma conexão com o banco Neon PostgreSQL."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL não configurada no arquivo .env ou na Vercel.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


# ==========================================================
# 2. SEGURANÇA E AUTENTICAÇÃO (SENHAS E JWT)
# ==========================================================

def hash_senha(senha: str) -> str:
    """Criptografa a senha do usuário usando algoritmo Bcrypt com salt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(senha.encode("utf-8"), salt).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    """Compara a senha digitada com a senha criptografada salva no banco."""
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))
    except Exception:
        return False


def gerar_token_jwt(usuario_id: str, email: str) -> str:
    """Gera um token JWT com validade de 7 dias para manter o usuário logado."""
    expiracao = datetime.utcnow() + timedelta(days=7)
    payload = {
        "sub": str(usuario_id),
        "email": email,
        "exp": expiracao
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decodificar_token_jwt(token: str) -> dict:
    """Valida o token JWT e retorna os dados do usuário se for válido."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


# ==========================================================
# 3. OPERAÇÕES DE USUÁRIOS
# ==========================================================

def buscar_usuario_por_email(email: str):
    """Busca um usuário no banco pelo endereço de e-mail."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM public.usuarios WHERE email = %s LIMIT 1;", (email,))
            return cur.fetchone()


def buscar_usuario_por_id(usuario_id: str):
    """Busca os dados do usuário pelo seu UUID (identificador único)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, nome, created_at FROM public.usuarios WHERE id = %s LIMIT 1;", (usuario_id,))
            return cur.fetchone()


def criar_usuario(email: str, senha: str, nome: str = None):
    """Cadastra um novo usuário no banco de dados com senha criptografada."""
    senha_criptografada = hash_senha(senha)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.usuarios (email, senha_hash, nome) VALUES (%s, %s, %s) RETURNING id, email, nome, created_at;",
                (email, senha_criptografada, nome)
            )
            novo_usuario = cur.fetchone()
            conn.commit()
            return novo_usuario


# ==========================================================
# 4. OPERAÇÕES DE AMOSTRAS DE CAFÉ
# ==========================================================

def listar_amostras_usuario(usuario_id: str):
    """Retorna todas as amostras cadastradas pelo usuário, ordenadas pelas mais recentes."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, fileira, pe, imagem_url, doencas, percentual_doencas, informacoes_adicionais, status, created_at 
                FROM public.amostras 
                WHERE usuario_id = %s 
                ORDER BY created_at DESC;
                """,
                (usuario_id,)
            )
            linhas = cur.fetchall()
            # Converte tipos especiais para formatos compatíveis com JSON
            for r in linhas:
                if r.get("created_at"):
                    r["created_at"] = str(r["created_at"])
                if r.get("percentual_doencas") is not None:
                    r["percentual_doencas"] = float(r["percentual_doencas"])
                if r.get("id"):
                    r["id"] = str(r["id"])
            return linhas


def buscar_amostra_por_id(amostra_id: str, usuario_id: str):
    """Busca uma amostra específica pertencente ao usuário logado."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM public.amostras WHERE id = %s AND usuario_id = %s LIMIT 1;",
                (amostra_id, usuario_id)
            )
            r = cur.fetchone()
            if r:
                if r.get("created_at"):
                    r["created_at"] = str(r["created_at"])
                if r.get("percentual_doencas") is not None:
                    r["percentual_doencas"] = float(r["percentual_doencas"])
                if r.get("id"):
                    r["id"] = str(r["id"])
            return r


def atualizar_laudo_amostra(amostra_id: str, doencas: str, percentual: float, info: str, status: str):
    """Salva no banco o resultado do diagnóstico gerado pela Inteligência Artificial."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.amostras 
                SET doencas = %s, percentual_doencas = %s, informacoes_adicionais = %s, status = %s 
                WHERE id = %s;
                """,
                (doencas, percentual, info, status, amostra_id)
            )
            conn.commit()


def atualizar_status_erro_amostra(amostra_id: str, status: str, info: str):
    """Registra uma mensagem de erro caso a análise da IA falhe."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.amostras SET status = %s, informacoes_adicionais = %s WHERE id = %s;",
                (status, info, amostra_id)
            )
            conn.commit()


# ==========================================================
# 5. CONTROLE DE USO (LIMITE DE ANÁLISES POR USUÁRIO)
# ==========================================================

_eventos_pronta = False


def garantir_tabela_eventos():
    """Cria a tabela eventos na primeira utilização. Idempotente."""
    global _eventos_pronta
    if _eventos_pronta:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.eventos (
                  id bigserial PRIMARY KEY,
                  usuario_id text NOT NULL,
                  tipo text NOT NULL,
                  payload jsonb,
                  criado_em timestamptz NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS eventos_usuario_tipo_criado_idx ON public.eventos (usuario_id, tipo, criado_em DESC);"
            )
    _eventos_pronta = True


def registrar_analise_com_limite(usuario_id: str, limite_hora: int, limite_dia: int):
    """Registra uma análise se o usuário estiver abaixo dos limites por hora e por dia.
    Retorna {"permitida": bool, "limite": "hora" | "dia" | None, "retry_after": int}."""
    garantir_tabela_eventos()
    uid = str(usuario_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", (uid,))
            cur.execute(
                """
                SELECT
                  count(*) FILTER (WHERE criado_em > now() - interval '1 hour') AS na_hora,
                  count(*) AS no_dia,
                  coalesce(extract(epoch FROM min(criado_em) FILTER (WHERE criado_em > now() - interval '1 hour') + interval '1 hour' - now()), 0) AS espera_hora,
                  coalesce(extract(epoch FROM min(criado_em) + interval '1 day' - now()), 0) AS espera_dia
                FROM public.eventos
                WHERE usuario_id = %s AND tipo = 'analise' AND criado_em > now() - interval '1 day';
                """,
                (uid,)
            )
            r = cur.fetchone()
            if r["na_hora"] >= limite_hora:
                return {"permitida": False, "limite": "hora", "retry_after": int(r["espera_hora"]) + 1}
            if r["no_dia"] >= limite_dia:
                return {"permitida": False, "limite": "dia", "retry_after": int(r["espera_dia"]) + 1}
            cur.execute("INSERT INTO public.eventos (usuario_id, tipo) VALUES (%s, 'analise');", (uid,))
            return {"permitida": True, "limite": None, "retry_after": 0}
