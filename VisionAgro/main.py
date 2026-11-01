"""
main.py - Servidor Principal da Aplicação VisionAgro (FastAPI)
Responsável por:
1. Servir as páginas web (Login, Cadastro e Dashboard).
2. Gerenciar sessões e autenticação.
3. Fornecer API REST e processar análise de fotos com a IA Google Gemini.
"""

import os
import json
import base64
import re
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ConfigDict

import database as db

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("VisionAgro")

load_dotenv()

# ==========================================================
# 1. INICIALIZAÇÃO DA IA GEMINI E DO FASTAPI
# ==========================================================

def get_gemini_client():
    """Obtém o cliente da IA Gemini de forma dinâmica a partir da GEMINI_API_KEY."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key and gemini_key.strip() and gemini_key != "your-gemini-api-key":
        try:
            from google import genai
            return genai.Client(api_key=gemini_key.strip())
        except Exception as e:
            logger.error(f"Erro ao instanciar cliente Gemini: {e}")
    return None

def obter_modelos_disponiveis(gemini_key: str) -> List[str]:
    """Consulta os modelos ativos na conta Google AI Studio dinamicamente para nunca dar 404."""
    modelos_api = []
    try:
        r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}", timeout=4)
        if r.status_code == 200:
            dados = r.json()
            for m in dados.get("models", []):
                nome = m.get("name", "").replace("models/", "").strip()
                metodos = m.get("supportedGenerationMethods", [])
                if "generateContent" in metodos and nome:
                    modelos_api.append(nome)
    except Exception as e:
        logger.warning(f"Não foi possível listar modelos dinamicamente: {e}")

    # Lista de prioridade dos modelos mais modernos e rápidos
    prioridades = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-pro",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]

    resultado = []
    # 1. Primeiro os modelos de alta prioridade que existem na conta
    for p in prioridades:
        if p in modelos_api and p not in resultado:
            resultado.append(p)

    # 2. Outros modelos descobertos na API
    for m in modelos_api:
        if m not in resultado:
            resultado.append(m)

    # 3. Caso a consulta dinâmica falhe, usa a lista padrão de prioridade
    for p in prioridades:
        if p not in resultado:
            resultado.append(p)

    return resultado

# Diretório de Templates compatível com Vercel Serverless
BASE_DIR = Path(__file__).resolve().parent
caminhos_templates = [
    BASE_DIR / "templates",
    BASE_DIR.parent / "templates",
    BASE_DIR.parent / "api" / "templates",
    Path.cwd() / "VisionAgro" / "templates",
    Path.cwd() / "templates",
    Path.cwd() / "api" / "templates",
]
pasta_templates = next((p for p in caminhos_templates if p.exists() and p.is_dir()), BASE_DIR / "templates")
templates = Jinja2Templates(directory=str(pasta_templates))

app = FastAPI(
    title="VisionAgro API",
    description="Sistema de monitoramento e análise de doenças do café.",
    version="3.0.0"
)

# Middleware de Segurança para Cabeçalhos HTTP
@app.middleware("http")
async def seguranca_headers_middleware(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    return resposta


# ==========================================================
# 2. MODELOS DE DADOS (SCHEMAS PYDANTIC)
# ==========================================================

class AmostraOut(BaseModel):
    id: str = Field(..., description="Identificador único")
    fileira: str
    pe: str
    imagem_url: str
    doencas: Optional[str] = None
    percentual_doencas: Optional[float] = None
    informacoes_adicionais: Optional[str] = None
    status: str
    created_at: str
    model_config = ConfigDict(extra="ignore")

class AnaliseResultData(BaseModel):
    doencas: str
    percentual_doencas: float
    informacoes_adicionais: str
    status: str
    model_config = ConfigDict(extra="ignore")

class AnaliseResponse(BaseModel):
    status: str
    dados: AnaliseResultData
    model_config = ConfigDict(extra="ignore")


# ==========================================================
# 3. CONTROLE DE SESSÃO E USUÁRIO LOGADO
# ==========================================================

def get_current_user_cookie(request: Request):
    """Lê o cookie de sessão do navegador para renderizar o painel web."""
    token = request.cookies.get("access-token")
    if not token:
        return None
    dados = db.decodificar_token_jwt(token)
    if not dados:
        return None
    return db.buscar_usuario_por_id(dados.get("sub"))

def get_current_user_api(request: Request):
    """Autentica chamadas de API via Header Bearer Token ou Cookie."""
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    if not token:
        token = request.cookies.get("access-token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autorizado. Faça login primeiro.")
        
    dados = db.decodificar_token_jwt(token)
    if not dados:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada. Faça login novamente.")
        
    usuario = db.buscar_usuario_por_id(dados.get("sub"))
    if not usuario:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado.")
    return usuario


# ==========================================================
# 4. ROTAS DE INTERFACE WEB (HTML)
# ==========================================================

router_ui = APIRouter(tags=["Painel Web"])

@router_ui.get("/", response_class=HTMLResponse, include_in_schema=False)
async def rota_raiz(user=Depends(get_current_user_cookie)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@router_ui.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def pagina_login(request: Request, user=Depends(get_current_user_cookie)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"erro": None})

@router_ui.get("/cadastro", response_class=HTMLResponse, include_in_schema=False)
async def pagina_cadastro(request: Request, user=Depends(get_current_user_cookie)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="cadastro.html", context={"erro": None})

@router_ui.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def pagina_dashboard(request: Request, user=Depends(get_current_user_cookie)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    try:
        amostras = db.listar_amostras_usuario(user["id"])
    except Exception as e:
        logger.error(f"Erro ao carregar amostras: {e}")
        amostras = []
    
    total = len(amostras)
    pendentes = sum(1 for a in amostras if a.get("status") == "pendente")
    
    dados = {
        "usuario": user.get("email"),
        "total": total,
        "pendentes": pendentes,
        "analisadas": total - pendentes
    }
    
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={"dados": dados, "amostras": amostras}
    )


# ==========================================================
# 5. ROTAS DE AUTENTICAÇÃO (LOGIN / CADASTRO / SAIR)
# ==========================================================

router_auth = APIRouter(prefix="/auth", tags=["Autenticação"])

@router_auth.post("/login", summary="Fazer Login")
async def acao_login(request: Request, email: str = Form(...), senha: str = Form(...)):
    try:
        usuario = db.buscar_usuario_por_email(email.strip().lower())
        if not usuario or not db.verificar_senha(senha, usuario["senha_hash"]):
            return templates.TemplateResponse(
                request=request, 
                name="login.html", 
                context={"erro": "E-mail ou senha incorretos."}
            )
            
        token = db.gerar_token_jwt(usuario["id"], usuario["email"])
        resposta = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        resposta.set_cookie(key="access-token", value=token, httponly=True, max_age=60*60*24*7, samesite="lax")
        return resposta
    except Exception as e:
        logger.error(f"Erro no login: {e}")
        return templates.TemplateResponse(
            request=request, 
            name="login.html", 
            context={"erro": "Erro ao conectar ao banco de dados."}
        )

@router_auth.post("/cadastro", summary="Criar Conta")
async def acao_cadastro(request: Request, email: str = Form(...), senha: str = Form(...), confirmacao_senha: str = Form(...)):
    if senha != confirmacao_senha:
        return templates.TemplateResponse(
            request=request, 
            name="cadastro.html", 
            context={"erro": "As senhas não coincidem."}
        )
    if len(senha) < 6:
        return templates.TemplateResponse(
            request=request, 
            name="cadastro.html", 
            context={"erro": "A senha deve ter no mínimo 6 dígitos."}
        )
    try:
        email_limpo = email.strip().lower()
        if db.buscar_usuario_por_email(email_limpo):
            return templates.TemplateResponse(
                request=request, 
                name="cadastro.html", 
                context={"erro": "Este e-mail já está cadastrado."}
            )
            
        novo_usuario = db.criar_usuario(email_limpo, senha)
        token = db.gerar_token_jwt(novo_usuario["id"], novo_usuario["email"])
        resposta = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        resposta.set_cookie(key="access-token", value=token, httponly=True, max_age=60*60*24*7, samesite="lax")
        return resposta
    except Exception as e:
        logger.error(f"Erro no cadastro: {e}")
        return templates.TemplateResponse(
            request=request, 
            name="cadastro.html", 
            context={"erro": "Não foi possível cadastrar no momento."}
        )

@router_auth.get("/sair", summary="Encerrar Sessão", include_in_schema=False)
async def acao_sair():
    resposta = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resposta.delete_cookie(key="access-token")
    return resposta


# ==========================================================
# 6. ROTAS DE API REST E ANÁLISE COM IA
# ==========================================================

router_api = APIRouter(prefix="/api/v1", tags=["Inteligência Artificial e Amostras"])

LIMITE_ANALISES_HORA = 20
LIMITE_ANALISES_DIA = 100

@router_api.get("/amostras", response_model=List[AmostraOut], summary="Listar Amostras")
async def listar_amostras(user=Depends(get_current_user_api)):
    """Retorna todas as amostras salvas pelo usuário."""
    return db.listar_amostras_usuario(user["id"])

@router_api.post("/analisar/{amostra_id}", response_model=AnaliseResponse, summary="Analisar Amostra com Gemini IA")
async def analisar_amostra(amostra_id: str, user=Depends(get_current_user_api)):
    """Envia a foto para a IA Gemini e atualiza o laudo no banco Neon."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not gemini_key or gemini_key == "your-gemini-api-key":
        raise HTTPException(
            status_code=500, 
            detail="Chave GEMINI_API_KEY não configurada na Vercel. Adicione em Settings > Environment Variables e faça Redeploy."
        )

        
    amostra = db.buscar_amostra_por_id(amostra_id, user["id"])
    if not amostra:
        raise HTTPException(status_code=404, detail="Amostra não encontrada.")
        
    imagem_url = amostra.get("imagem_url")
    if not imagem_url:
        raise HTTPException(status_code=400, detail="Amostra sem foto associada.")

    limite = db.registrar_analise_com_limite(user["id"], LIMITE_ANALISES_HORA, LIMITE_ANALISES_DIA)
    if not limite["permitida"]:
        logger.warning(f"Análise bloqueada por limite por {limite['limite']} do usuário {user['id']}")
        espera = limite["retry_after"]
        raise HTTPException(
            status_code=429,
            detail=f"Limite de análises por {limite['limite']} atingido. Tente novamente em {espera} segundos.",
            headers={"Retry-After": str(espera)}
        )

    try:
        # 1. Carrega e otimiza a imagem em memória (redimensiona para 768px e comprime para upload ultrarrápido)
        if imagem_url.startswith("data:image"):
            _, base64_data = imagem_url.split(",", 1)
            raw_b64_orig = base64_data.strip()
            img_bytes = base64.b64decode(raw_b64_orig)
        else:
            resposta_img = requests.get(imagem_url, timeout=8)
            if resposta_img.status_code != 200:
                raise Exception("Falha ao baixar a imagem.")
            img_bytes = resposta_img.content

        # Redimensiona e comprime para envio leve e instantâneo
        try:
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            img.thumbnail((768, 768), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            raw_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            raw_b64 = base64.b64encode(img_bytes).decode("utf-8")

        prompt = """
Você é um engenheiro agrônomo fitopatologista especialista em cafeicultura.
Realize uma análise fitossanitária 100% original, minuciosa e detalhada baseando-se EXCLUSIVAMENTE na imagem desta planta/amostra de café.

DIRETRIZES DA ANÁLISE:
1. OBSERVAÇÃO VISUAL DIRETA:
   - Observe detalhadamente o estado desta foto: tronco, colo da planta, ramos laterais, folhas e frutos.
   - Identifique os sintomas visuais reais presentes nesta imagem específica (ex: rachaduras longitudinais na casca, cancros abertos, descascamento, necrose do lenho, folhas murchas/secas, frutos pretos mumificados nos ramos).

2. CLASSIFICAÇÃO DA DOENÇA (escolha ESTRITAMENTE uma das 3 opções abaixo):
   - "Fusariose (Fusarium spp.)" -> Quando houver evidência visual de infecção vascular, cancros no tronco/colo, descascamento característico ou mumificação/seca de frutos por Fusarium.
   - "Saudável" -> Quando a planta estiver verde, vigorosa, com tronco íntegro e sem lesões visíveis.
   - "Doença não identificada" -> Quando houver anormalidade visual que não corresponda especificamente ao padrão de Fusariose.

3. ESTIMATIVA DE AFETAÇÃO:
   - Estime a porcentagem de comprometimento da planta observada nesta foto (número de 0 a 100). Plantas saudáveis devem ter 0.0.

4. PARECER TÉCNICO CONCISO E OBJETIVO ('informacoes_adicionais'):
   - Redija um laudo técnico, direto e sucinto (cerca de 2 a 4 frases).
   - Descreva brevemente os sintomas identificados nesta planta e indique as medidas práticas imediatas de manejo (ex: poda fitossanitária, desinfecção e fungicida). Seja claro e objetivo, sem enrolação.

Responda ESTRITAMENTE em formato JSON puro:
{
  "doencas": "Fusariose (Fusarium spp.)",
  "percentual_doencas": 45.0,
  "informacoes_adicionais": "Redija aqui o laudo técnico conciso e exclusivo para esta imagem."
}
"""
        texto_resposta = None
        erros_acumulados = []

        # Obtém dinamicamente os modelos ativos na conta do usuário
        modelos_disponiveis = obter_modelos_disponiveis(gemini_key)

        payload_json = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": raw_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "response_mime_type": "application/json",
                "max_output_tokens": 500,
                "temperature": 0.35
            }
        }

        payload_simples = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": raw_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "max_output_tokens": 500,
                "temperature": 0.35
            }
        }

        for mod in modelos_disponiveis:
            for versao in ["v1beta", "v1"]:
                url_api = f"https://generativelanguage.googleapis.com/{versao}/models/{mod}:generateContent?key={gemini_key}"
                
                # Tenta primeiro com JSON estruturado e depois com payload padrão se necessário
                for p_envio in [payload_json, payload_simples]:
                    try:
                        r = requests.post(url_api, json=p_envio, timeout=15)
                        if r.status_code == 200:
                            dados_res = r.json()
                            candidates = dados_res.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                parts = candidates[0]["content"].get("parts", [])
                                if parts and "text" in parts[0]:
                                    texto_resposta = parts[0]["text"]
                                    logger.info(f"Análise concluída com sucesso ({versao}/{mod})")
                                    break
                        else:
                            erros_acumulados.append(f"{versao}/{mod} -> HTTP {r.status_code}")
                    except Exception as e_req:
                        erros_acumulados.append(f"{versao}/{mod} -> {str(e_req)}")
                        continue
                
                if texto_resposta:
                    break
            if texto_resposta:
                break

        if not texto_resposta:
            ultimo = erros_acumulados[-1] if erros_acumulados else "Nenhum modelo respondeu com sucesso."
            raise Exception(f"Falha ao gerar laudo da IA: {ultimo}")

        # Limpeza robusta de blocos de código e markdown
        texto_limpo = texto_resposta.strip()
        texto_limpo = re.sub(r"```(?:json)?", "", texto_limpo, flags=re.IGNORECASE).strip()
        texto_limpo = re.sub(r"```", "", texto_limpo).strip()

        dados_ia = {}
        try:
            dados_ia = json.loads(texto_limpo)
        except Exception:
            match = re.search(r"\{.*\}", texto_limpo, re.DOTALL)
            if match:
                try:
                    dados_ia = json.loads(match.group(0))
                except Exception:
                    pass

        # Extração das informações adicionais geradas dinamicamente pela IA
        info_extraida = ""
        if isinstance(dados_ia, dict) and "informacoes_adicionais" in dados_ia:
            info_extraida = str(dados_ia.get("informacoes_adicionais", "")).strip()

        # Fallback de regex para pegar a descrição caso o JSON tenha falhado parcialmente
        if not info_extraida:
            match_info = re.search(r'"informacoes_adicionais"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', texto_limpo)
            if match_info:
                info_extraida = match_info.group(1).encode().decode('unicode-escape', 'ignore').strip()

        # Identificação da doença
        texto_baixo = texto_resposta.lower()
        if "fusari" in str(dados_ia.get("doencas", "")).lower() or "fusari" in texto_baixo or "cancro" in texto_baixo or "mumific" in texto_baixo:
            doencas = "Fusariose (Fusarium spp.)"
        elif any(w in str(dados_ia.get("doencas", "")).lower() for w in ["saudav", "saudáv", "sadio", "sadia"]) or "sadia" in texto_baixo or "saudável" in texto_baixo:
            doencas = "Saudável"
        else:
            doencas = "Doença não identificada"

        # Converte percentual
        try:
            p_raw = dados_ia.get("percentual_doencas", 0)
            if isinstance(p_raw, str):
                p_raw = re.sub(r"[^\d.]", "", p_raw)
            percentual = float(p_raw) if p_raw else (45.0 if doencas == "Fusariose (Fusarium spp.)" else 0.0)
        except Exception:
            percentual = 45.0 if doencas == "Fusariose (Fusarium spp.)" else 0.0

        if doencas == "Saudável":
            percentual = 0.0

        # Se a IA não redigiu texto legível, gera laudo descritivo
        if not info_extraida or len(info_extraida) < 15 or "```" in info_extraida:
            if doencas == "Fusariose (Fusarium spp.)":
                info = "Sinais visíveis compatíveis com infecção por Fusarium no cafeeiro. Recomenda-se poda fitossanitária e manejo com fungicida registrado."
            elif doencas == "Saudável":
                info = "Planta em bom estado fitossanitário sem sinais de infecção no caule. Manter o monitoramento de rotina."
            else:
                info = "Anomalia fitossanitária detectada. Recomendado acompanhamento de campo para confirmação."
        else:
            info = info_extraida

        status_ia = "analisado"
        
        # Atualiza o laudo no banco Neon
        db.atualizar_laudo_amostra(amostra_id, doencas, percentual, info, status_ia)
        
        return AnaliseResponse(
            status="sucesso", 
            dados=AnaliseResultData(
                doencas=doencas,
                percentual_doencas=percentual,
                informacoes_adicionais=info,
                status=status_ia
            )
        )


        
    except json.JSONDecodeError:
        msg_erro = "A IA respondeu em formato incompatível."
        db.atualizar_status_erro_amostra(amostra_id, "erro_ia", msg_erro)
        raise HTTPException(status_code=500, detail=msg_erro)
        
    except Exception as e:
        logger.error(f"Erro na análise de IA: {e}")
        msg_erro = f"Erro da IA: {str(e)}"
        db.atualizar_status_erro_amostra(amostra_id, "erro_ia", msg_erro)
        raise HTTPException(status_code=500, detail=msg_erro)



# Registrar Roteadores
app.include_router(router_ui)
app.include_router(router_auth)
app.include_router(router_api)

