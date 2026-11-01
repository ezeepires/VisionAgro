"""
pi_sync.py - Sincronizador Offline para Raspberry Pi
Responsável por:
1. Verificar conexão com a internet.
2. Ler as fotos tiradas na lavoura (pastas Fileira_X).
3. Converter a foto em Base64 e enviar diretamente para o banco Neon PostgreSQL.
4. Mover a foto enviada para a pasta './enviadas' para não reenviar duplicada.
"""

import os
import time
import socket
import shutil
import base64
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# ==========================================================
# CONFIGURAÇÕES
# ==========================================================

# String de conexão do Neon PostgreSQL (obrigatória, vinda do ambiente ou do .env)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada. Defina a variável de ambiente ou o arquivo .env.")

# E-mail do proprietário das fotos no painel
EMAIL_USUARIO = os.environ.get("PI_EMAIL", "teste@gmail.com")

PASTA_CAPTURAS = Path(".")
PASTA_ENVIADAS = Path("./enviadas")


# ==========================================================
# FUNÇÕES DE REDE E BANCO
# ==========================================================

def tem_conexao():
    """Testa se há conexão de internet ativa."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


def get_db_connection():
    """Conecta diretamente ao banco Neon PostgreSQL."""
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        print(f"[-] Erro ao conectar ao banco Neon: {e}")
        return None


def obter_usuario_id(conn, email):
    """Busca o ID do usuário no banco pelo e-mail."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM public.usuarios WHERE email = %s LIMIT 1;", (email,))
        usuario = cur.fetchone()
        return str(usuario["id"]) if usuario else None


# ==========================================================
# PROCESSAMENTO DE FOTOS DA LAVOURA
# ==========================================================

def sincronizar_fotos():
    """Varre as pastas de fileiras e envia as fotos para o banco."""
    if not tem_conexao():
        print("[-] Sem internet no momento. Aguardando...")
        return

    print("[+] Internet conectada! Iniciando sincronização das fotos...")
    conn = get_db_connection()
    if not conn:
        return

    try:
        usuario_id = obter_usuario_id(conn, EMAIL_USUARIO)
        if not usuario_id:
            print(f"[-] Usuário {EMAIL_USUARIO} não encontrado no banco.")
            return

        PASTA_ENVIADAS.mkdir(exist_ok=True)

        # Procura pastas que começam com 'Fileira_'
        for pasta_fileira in PASTA_CAPTURAS.iterdir():
            if pasta_fileira.is_dir() and pasta_fileira.name.startswith("Fileira_"):
                fileira_nome = pasta_fileira.name

                for foto in pasta_fileira.iterdir():
                    if foto.is_file() and foto.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                        pe_nome = foto.stem
                        print(f"  -> Enviando {foto.name} da {fileira_nome} (Pé: {pe_nome})...")

                        try:
                            # 1. Converte a foto em Base64 Data URI
                            with open(foto, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("utf-8")
                                data_uri = f"data:image/jpeg;base64,{b64}"

                            # 2. Grava a amostra diretamente no Neon
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    INSERT INTO public.amostras (usuario_id, fileira, pe, imagem_url, status)
                                    VALUES (%s, %s, %s, %s, 'pendente');
                                    """,
                                    (usuario_id, fileira_nome, pe_nome, data_uri)
                                )
                                conn.commit()

                            # 3. Move para a pasta 'enviadas'
                            destino_pasta = PASTA_ENVIADAS / fileira_nome
                            destino_pasta.mkdir(parents=True, exist_ok=True)
                            destino_arquivo = destino_pasta / foto.name
                            
                            if destino_arquivo.exists():
                                os.remove(foto)
                            else:
                                shutil.move(str(foto), str(destino_arquivo))

                            print(f"     [OK] Amostra salva no banco com sucesso!")

                        except Exception as e:
                            print(f"     [ERRO] Falha ao enviar {foto.name}: {e}")
                            conn.rollback()

    finally:
        conn.close()


# ==========================================================
# EXECUÇÃO CONTÍNUA
# ==========================================================

if __name__ == "__main__":
    print("🌿 VisionAgro - Sincronizador Raspberry Pi Iniciado")
    while True:
        sincronizar_fotos()
        print("[*] Aguardando 5 minutos para a próxima verificação...\n")
        time.sleep(300)
