import json
import os

def carregar_dados():
    if not os.path.exists("estoque.json"):
        return {"produtos": [], "utilizadores": {}, "vendas": []}
    with open("estoque.json", "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_dados(dados):
    with open("estoque.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)
        
import sqlite3
import logging
import requests
import base64
from io import BytesIO
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ------------------------------------------------------------------------------
# 🔒 CREDENCIAIS E CONSTANTES DE PRODUÇÃO
# ------------------------------------------------------------------------------
TOKEN = "8826676433:AAEjicVbEpow_dbalsja15hFYCghRwAq0D0"
PUSHINPAY_TOKEN = "71078|M1MASBFV155gtnKBttSvkE6u8bD8kSBFjAMLwOXa70ca5a25"

# 🛡️ CREDENCIAIS DE SEGURANÇA DO PAINEL ADMIN
USUARIO_ADMIN_MINISITE = "aguia2026"
SENHA_ADMIN_MINISITE = "yuresantos26"

# LINK DIRETO DA SUA LOGO NO GITHUB
LOGO_URL = "https://raw.githubusercontent.com/thallisimports-maker/bot-esim-yure/main/logo.png"

logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------------------
# 🗄️ INICIALIZAÇÃO DO BANCO DE DADOS SQLITE
# ------------------------------------------------------------------------------
def conectar_banco():
    con = sqlite3.connect("banco_usuarios.db")
    con.row_factory = sqlite3.Row
    return con

def inicializar_banco():
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS carteira (
                chat_id TEXT PRIMARY KEY, 
                first_name TEXT, 
                username TEXT, 
                saldo REAL DEFAULT 0.0,
                data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS estoque (produto_id TEXT PRIMARY KEY, quantidade INTEGER DEFAULT 0)")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS estoque_codigos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                produto_id TEXT, 
                conteudo_esim TEXT,
                ddd TEXT DEFAULT 'BR',
                gb TEXT DEFAULT 'Padrão'
            )
        """)
        
        cur.execute("PRAGMA table_info(estoque_codigos)")
        colunas = [col["name"] for col in cur.fetchall()]
        if "ddd" not in colunas:
            cur.execute("ALTER TABLE estoque_codigos ADD COLUMN ddd TEXT DEFAULT 'BR'")
        if "gb" not in colunas:
            cur.execute("ALTER TABLE estoque_codigos ADD COLUMN gb TEXT DEFAULT 'Padrão'")

        cur.execute("CREATE TABLE IF NOT EXISTS acessos_miniapp (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, data_acesso DATETIME DEFAULT CURRENT_TIMESTAMP)")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS giftcards (
                codigo TEXT PRIMARY KEY, 
                valor REAL, 
                usado INTEGER DEFAULT 0,
                usado_por TEXT
            )
        """)
        
        cur.execute("SELECT COUNT(*) FROM estoque")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('vivo_30gb', 0), ('tim_40gb', 0), ('claro_40gb', 0)")
        con.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco: {e}")
    finally:
        con.close()

inicializar_banco()

# ------------------------------------------------------------------------------
# 🤖 LÓGICA DO BOT DO TELEGRAM (COMANDOS & HANDLERS)
# ------------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    first_name = user.first_name or "Usuário"
    username = user.username or "sem_username"

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("""
            INSERT INTO carteira (chat_id, first_name, username, saldo) 
            VALUES (?, ?, ?, 0.0)
            ON CONFLICT(chat_id) DO UPDATE SET first_name=?, username=?
        """, (chat_id, first_name, username, first_name, username))
        con.commit()

        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0
        
        cur.execute("SELECT produto_id, quantidade FROM estoque")
        est = {row["produto_id"]: row["quantidade"] for row in cur.fetchall()}
    except Exception as e:
        logging.error(f"Erro no /start: {e}")
        saldo = 0.0
        est = {}
    finally:
        con.close()

    url_miniapp = "https://e-simsyure.shop"

    texto = (
        f"👑 **YURE eSIMS — HUMILDADE, LEALDADE, DISCIPLINA E ATITUDE**\n\n"
        f"Olá, **{first_name}**! Seja bem-vindo ao melhor do mercado.\n\n"
        f"💰 **Saldo na Carteira:** `R$ {saldo:.2f}`\n\n"
        f"📱 **eSIMS Com Alta Qualidade E Durabilidade!**\n"
        f"Escolha uma opção abaixo para acessar a loja:"
    )
    
    botoes = [
        [InlineKeyboardButton("👑 ABRIR LOJA YURE eSIMS (MINIAPP)", web_app=WebAppInfo(url=url_miniapp))]
    ]

    # 1. Carrega os produtos atualizados do estoque.json
    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    # 2. Percorre os produtos e adiciona botões apenas para os e-SIMs 'disponivel'
    for prod in produtos:
        if str(prod.get("status", "")).lower().strip() == "disponivel":
            op = prod.get("operadora", "eSIM")
            plano = prod.get("plano", "")
            preco = float(prod.get("preco", 0))
            prod_id = prod.get("id")

            # Cria o botão dinâmico com o nome, plano e preço cadastrados no Painel
            texto_botao = f"📱 {op} {plano} - R$ {preco:.2f}"
            callback = f"buy_{prod_id}"

            botoes.append(
                [InlineKeyboardButton(texto_botao, callback_data=callback)]
            )
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=LOGO_URL, caption=texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))
    except Exception as err:
        logging.error(f"Erro ao enviar photo, enviando texto: {err}")
        await context.bot.send_message(chat_id=chat_id, text=texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

async def comando_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res = cur.fetchone()
        saldo = float(res["saldo"]) if res else 0.0
    finally:
        con.close()

    url_miniapp = "https://thallisimports-maker.github.io/bot-esim-yure/"
    texto = f"💳 **SUA CARTEIRA YURE eSIMS**\n\n💰 **Saldo Disponível:** `R$ {saldo:.2f}`\n\nPara recarregar via PIX ou resgatar um cupom de saldo, clique abaixo:"
    botoes = [[InlineKeyboardButton("⚡ Adicionar Saldo / Recarregar", web_app=WebAppInfo(url=url_miniapp))]]
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

async def comando_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        "📞 **ATENDIMENTO & SUPORTE YURE eSIMS**\n\n"
        "Precisa de ajuda com a ativação, dúvidas ou trocas?\n"
        "Escolha abaixo por onde deseja falar diretamente conosco:"
    )
    botoes = [
        [InlineKeyboardButton("💬 Atendimento via WhatsApp", url="https://wa.me/5535997550084")],
        [InlineKeyboardButton("✈️ Atendimento via Telegram", url="https://t.me/@Yureconsul7")] # Substitua pelo seu @username do Telegram
    ]
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

async def comando_esims(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT produto_id, quantidade FROM estoque")
        est = {row["produto_id"]: row["quantidade"] for row in cur.fetchall()}
    finally:
        con.close()

    texto = (
        f"📊 **ESTOQUE DE eSIMS DISPONÍVEIS**\n\n"
        f"📱 **Vivo eSIM:** {est.get('vivo_5gb', 0)} unidades\n"
        f"📱 **Tim eSIM:** {est.get('tim_40gb', 0)} unidades\n"
        f"📱 **Claro eSIM:** {est.get('claro_40gb', 0)} unidades\n\n"
        f"⚡ *Ativação instantânea diretamente no MiniApp!*"
    )

    url_miniapp = "https://e-simsyure.shop/"
    botoes = [[InlineKeyboardButton("🛒 Comprar e-SIM pelo Bot", callback_data="comprar_bot")]]
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))


async def responder_botoes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    nome_usuario = query.from_user.first_name

    dados = carregar_dados()

    # 1. Processa a compra enviada pelo botão buy_
    if query.data.startswith("buy_"):
        prod_id = query.data.replace("buy_", "")
        produtos = dados.get("produtos", [])

        # Procura o produto específico cadastrado no Painel pelo ID
        produto = next((p for p in produtos if str(p.get("id")) == str(prod_id)), None)

        if not produto or str(produto.get("status", "")).lower().strip() != "disponivel":
            await query.message.reply_text("❌ Este e-SIM já não se encontra disponível!")
            return

        preco = float(produto.get("preco", 0))

        # Consulta o saldo na carteira SQLite
        con = conectar_banco()
        cur = con.cursor()
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (user_id,))
        res_saldo = cur.fetchone()
        saldo_atual = float(res_saldo["saldo"]) if res_saldo else 0.0

        if saldo_atual < preco:
            await query.message.reply_text(
                f"❌ **Saldo insuficiente!**\n\nEste e-SIM custa **R$ {preco:.2f}** e você tem **R$ {saldo_atual:.2f}** na carteira.\nAdicione saldo no MiniApp para comprar.",
                parse_mode="Markdown"
            )
            con.close()
            return

        # Desconta do saldo e marca produto como vendido
        novo_saldo = saldo_atual - preco
        cur.execute("UPDATE carteira SET saldo = ? WHERE chat_id = ?", (novo_saldo, user_id))
        con.commit()
        con.close()

        produto["status"] = "vendido"
        
        # Registra a venda para o relatório do painel
        registro_venda = {
            "user_id": user_id,
            "cliente": nome_usuario,
            "produto_id": produto.get("id"),
            "operadora": produto.get("operadora"),
            "valor": preco,
            "data": "2026-09-20"
        }
        dados.setdefault("vendas", []).append(registro_venda)

        salvar_dados(dados)
        salvar_dados_no_github(dados)

        imagem_qr = produto.get("imagem_qr", "")
        legenda = (
            f"✅ **COMPRA REALIZADA COM SUCESSO!**\n\n"
            f"📱 **Operadora:** {produto.get('operadora')}\n"
            f"📦 **Plano:** {produto.get('plano')}\n"
            f"💰 **Valor:** R$ {preco:.2f}\n\n"
            f"Seu QR Code de ativação encontra-se abaixo:"
        )

        # Envia a foto do QR Code ao cliente
        if imagem_qr and imagem_qr.startswith("http"):
            await context.bot.send_photo(chat_id=user_id, photo=imagem_qr, caption=legenda, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=user_id, text=legenda + "\n\n*(QR Code em processamento)*", parse_mode="Markdown")

async def receber_dados_webapp(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.message.web_app_data:
        return

    user_id = str(update.message.from_user.id)
    nome_usuario = update.message.from_user.first_name

    try:
        dados_recebidos = json.loads(update.message.web_app_data.data)
        acao = dados_recebidos.get("acao")

        # 1. COMPRA DE E-SIM VIA MINIAPP
        if acao == "comprar":
            prod_id = dados_recebidos.get("id")
            dados = carregar_dados()
            produtos = dados.get("produtos", [])

            produto = next(
                (p for p in produtos if str(p.get("id")) == str(prod_id)), None
            )

            if (
                not produto
                or str(produto.get("status", "")).lower().strip()
                != "disponivel"
            ):
                await update.message.reply_text(
                    "❌ Este e-SIM já não se encontra disponível!"
                )
                return

            preco = float(produto.get("preco", 0))

            con = conectar_banco()
            cur = con.cursor()
            cur.execute(
                "SELECT saldo FROM carteira WHERE chat_id = ?", (user_id,)
            )
            res_saldo = cur.fetchone()
            saldo_atual = float(res_saldo["saldo"]) if res_saldo else 0.0

            if saldo_atual < preco:
                await update.message.reply_text(
                    f"❌ **Saldo insuficiente!**\n\nEste e-SIM custa **R$ {preco:.2f}** e você possui **R$ {saldo_atual:.2f}** na carteira.\nAdicione saldo no MiniApp para finalizar a compra.",
                    parse_mode="Markdown",
                )
                con.close()
                return

            novo_saldo = saldo_atual - preco
            cur.execute(
                "UPDATE carteira SET saldo = ? WHERE chat_id = ?",
                (novo_saldo, user_id),
            )
            con.commit()
            con.close()

            produto["status"] = "vendido"

            registro_venda = {
                "user_id": user_id,
                "cliente": nome_usuario,
                "produto_id": produto.get("id"),
                "operadora": produto.get("operadora"),
                "valor": preco,
                "data": "2026-09-23",
            }
            dados.setdefault("vendas", []).append(registro_venda)

            salvar_dados(dados)
            salvar_dados_no_github(dados)

            imagem_qr = produto.get("imagem_qr", "")
            legenda = (
                f"✅ **COMPRA REALIZADA COM SUCESSO VIA MINIAPP!**\n\n"
                f"📱 **Operadora:** {produto.get('operadora')}\n"
                f"📦 **Plano:** {produto.get('plano')}\n"
                f"💰 **Valor:** R$ {preco:.2f}\n\n"
                f"Seu QR Code de ativação encontra-se abaixo:"
            )

            if imagem_qr and imagem_qr.startswith("http"):
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=imagem_qr,
                    caption=legenda,
                    parse_mode="Markdown",
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=legenda + "\n\n*(QR Code enviado com sucesso)*",
                    parse_mode="Markdown",
                )

        # 2. SOLICITAÇÃO DE RECARGA
        elif acao == "recarga":
            valor = float(dados_recebidos.get("valor", 0))
            await update.message.reply_text(
                f"💳 **Solicitação de Recarga Recebida!**\n\nValor: **R$ {valor:.2f}**\nUtilize a opção de recarga do bot para gerar o PIX.",
                parse_mode="Markdown",
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar pedido: {str(e)}")

# ------------------------------------------------------------------
# ⚙️ GESTOR DE LIFESPAN (REGISTRO DO MENU DE COMANDOS NATIVO)
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    telegram_app = Application.builder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("saldo", comando_saldo))
    telegram_app.add_handler(CommandHandler("suporte", comando_suporte))
    telegram_app.add_handler(CommandHandler("esims", comando_esims))
    telegram_app.add_handler(CallbackQueryHandler(responder_botoes))

    await telegram_app.initialize()
    await telegram_app.start()

    comandos_menu = [
        BotCommand("start", "👑 Menu Principal e Loja"),
        BotCommand("saldo", "💳 Consultar Saldo / Carteira"),
        BotCommand("esims", "📱 Ver eSIMs Disponíveis"),
        BotCommand("suporte", "📞 Suporte e Atendimento")
    ]
    await telegram_app.bot.set_my_commands(comandos_menu)

    await telegram_app.updater.start_polling(drop_pending_updates=True)

    yield

    await telegram_app.updater.stop()
    await telegram_app.stop()

# ------------------------------------------------------------------------------
# 🚀 APLICAÇÃO FASTAPI
# ------------------------------------------------------------------------------
app = FastAPI(title="Yure e-SIM API", lifespan=lifespan)

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

SENHA_ADMIN_SEGURA = "SuaSenhaAqui123!"

@app.get("/api/admin/login")
async def login_admin(senha: str = ""):
    if str(senha).strip() == SENHA_ADMIN_SEGURA.strip():
        return JSONResponse(content={"sucesso": True, "token": PUSHINPAY_TOKEN})
    return JSONResponse(status_code=401, content={"sucesso": False, "detail": "Senha incorreta!"})

@app.get("/api/admin/dados")
async def obter_dados_admin(authorization: str = Header(None)):
    if authorization != f"Bearer {PUSHINPAY_TOKEN}":
        raise HTTPException(status_code=401, detail="Nao autorizado")
    
    dados = carregar_dados()
    
    # Busca os Gift Cards cadastrados no SQLite
    con = conectar_banco()
    cur = con.cursor()
    cupons_lista = []
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS giftcards (codigo TEXT PRIMARY KEY, valor REAL, usado INTEGER DEFAULT 0, usado_por TEXT)")
        cur.execute("SELECT codigo, valor, usado, usado_por FROM giftcards")
        linhas = cur.fetchall()
        for row in linhas:
            cupons_lista.append({
                "codigo": row["codigo"],
                "valor": float(row["valor"]),
                "usado": bool(row["usado"]),
                "usado_por": row["usado_por"] or ""
            })
    except Exception as e:
        print("Erro ao ler giftcards:", e)
    finally:
        con.close()
        
    dados["cupons_detalhados"] = cupons_lista
    return dados

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "thallisimports-maker/bot-esim-yure"
GITHUB_FILE_PATH = "estoque.json"


def salvar_dados_no_github(dados_novos):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 1. Buscar o SHA atual do arquivo
    res_get = requests.get(url, headers=headers)
    if res_get.status_code != 200:
        print("Erro ao buscar SHA do GitHub:", res_get.json())
        return False

    sha = res_get.json()["sha"]

    # 2. Converter JSON para Base64
    conteudo_json = json.dumps(dados_novos, indent=2, ensure_ascii=False)
    conteudo_base64 = base64.b64encode(conteudo_json.encode("utf-8")).decode(
        "utf-8"
    )

    # 3. Commit no GitHub
    payload = {
        "message": "📦 Atualização do estoque via Painel Admin",
        "content": conteudo_base64,
        "sha": sha,
    }

    res_put = requests.put(url, headers=headers, json=payload)
    return res_put.status_code == 200

@app.get("/api/produtos-publico")
async def obter_produtos_publico():
    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    # Filtra apenas os produtos que estão com status 'disponivel'
    disponiveis = [
        p
        for p in produtos
        if str(p.get("status", "")).lower().strip() == "disponivel"
    ]
    return {"produtos": disponiveis}
    
class NovoProduto(BaseModel):
    operadora: str
    plano: str
    descricao: str = ""
    preco: float
    imagem_qr: str

class PayloadCompraMiniApp(BaseModel):
    chat_id: str
    produto_id: str


@app.post("/api/comprar-miniapp")
async def comprar_miniapp(payload: PayloadCompraMiniApp):
    user_id = str(payload.chat_id).strip()
    prod_id = str(payload.produto_id).strip()

    if not user_id:
        raise HTTPException(
            status_code=400, detail="ID do usuário não identificado."
        )

    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    produto = next(
        (p for p in produtos if str(p.get("id")) == str(prod_id)), None
    )

    if (
        not produto
        or str(produto.get("status", "")).lower().strip() != "disponivel"
    ):
        return {
            "status": "erro",
            "detalhe": "Este e-SIM já não se encontra disponível!",
        }

    preco = float(produto.get("preco", 0))

    con = conectar_banco()
    cur = con.cursor()
    cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (user_id,))
    res_saldo = cur.fetchone()
    saldo_atual = float(res_saldo["saldo"]) if res_saldo else 0.0

    if saldo_atual < preco:
        con.close()
        return {
            "status": "erro",
            "detalhe": f"Saldo insuficiente! O e-SIM custa R$ {preco:.2f} e você possui R$ {saldo_atual:.2f} na carteira.",
        }

    novo_saldo = saldo_atual - preco
    cur.execute(
        "UPDATE carteira SET saldo = ? WHERE chat_id = ?",
        (novo_saldo, user_id),
    )
    con.commit()
    con.close()

    produto["status"] = "vendido"

    registro_venda = {
        "user_id": user_id,
        "cliente": f"Cliente ({user_id})",
        "produto_id": produto.get("id"),
        "operadora": produto.get("operadora"),
        "valor": preco,
        "data": "2026-09-23",
    }
    dados.setdefault("vendas", []).append(registro_venda)

    salvar_dados(dados)
    salvar_dados_no_github(dados)

    return {
        "status": "sucesso",
        "mensagem": "Compra realizada com sucesso!",
        "operadora": produto.get("operadora"),
        "plano": produto.get("plano"),
        "preco": preco,
        "imagem_qr": produto.get("imagem_qr", ""),
        "novo_saldo": novo_saldo,
    }

@app.post("/api/admin/produtos")
async def adicionar_produto(
    produto: NovoProduto, authorization: str = Header(None)
):
    if authorization != f"Bearer {PUSHINPAY_TOKEN}":
        raise HTTPException(
            status_code=401, detail="Acesso negado! Nao autorizado."
        )

    dados = carregar_dados()
    if "produtos" not in dados or not isinstance(dados["produtos"], list):
        dados["produtos"] = []

    produtos = dados["produtos"]

    novo_item = {
        "id": f"esim_{len(produtos) + 1}",
        "operadora": produto.operadora,
        "plano": produto.plano,
        "descricao": produto.descricao,
        "preco": float(produto.preco),
        "imagem_qr": produto.imagem_qr,
        "status": "disponivel",
    }

    produtos.append(novo_item)
    dados["produtos"] = produtos

    salvar_dados(dados)
    sucesso_github = salvar_dados_no_github(dados)

    if not sucesso_github:
        print(
            "Aviso: Salvo localmente, mas falhou ao sincronizar com o GitHub."
        )

    return {"sucesso": True, "produto": novo_item}
    
class CompraMiniAppPayload(BaseModel):
    chat_id: str
    produto_id: str

class AdminAuthAddEsimPayload(BaseModel):
    usuario_admin: str
    senha_admin: str
    produto_id: str
    conteudo_esim: str
    ddd: Optional[str] = "BR"
    gb: Optional[str] = "Padrão"
    preco: Optional[float] = 25.0  # Campo de Preço do e-SIM
    texto_instrucoes: Optional[str] = "Escaneie o QR Code para ativar o seu e-SIM."

class GerarPixPayload(BaseModel):
    valor: float

class CriarGiftcardPayload(BaseModel):
    usuario_admin: str
    senha_admin: str
    codigo: str
    valor: float

class ResgatarGiftcardPayload(BaseModel):
    chat_id: str
    codigo: str

@app.get("/")
async def root():
    return {"status": "online", "mensagem": "API Yure e-SIM funcionando com sucesso!"}

@app.get("/api/estoque")
async def consultar_estoque_publico():
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT produto_id, quantidade FROM estoque")
        est = {row["produto_id"]: row["quantidade"] for row in cur.fetchall()}
        return {"status": "sucesso", "estoque": est}
    finally:
        con.close()

@app.get("/api/usuario/{chat_id}")
async def obter_dados_usuario(chat_id: str):
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO carteira (chat_id, saldo) VALUES (?, 0.0)", (chat_id,))
        con.commit()

        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0

        return {"status": "sucesso", "chat_id": chat_id, "saldo": saldo}
    finally:
        con.close()

@app.post("/api/comprar-esim")
async def comprar_esim_miniapp(payload: CompraMiniAppPayload):
    precos = {"vivo_30gb": 25.0, "tim_40gb": 30.0, "claro_40gb": 35.0}
    preco_item = precos.get(payload.produto_id, 999.0)

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (payload.chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0

        if saldo < preco_item:
            return {"status": "erro", "detalhe": "Saldo insuficiente na carteira!"}

        cur.execute("SELECT id, conteudo_esim, ddd, gb FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (payload.produto_id,))
        chip = cur.fetchone()
        if not chip:
            return {"status": "erro", "detalhe": "Estoque esgotado para este produto!"}

        chip_id, conteudo_bruto, esim_ddd, esim_gb = chip["id"], chip["conteudo_esim"], chip["ddd"], chip["gb"]

        cur.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, payload.chat_id))
        cur.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
        cur.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (payload.produto_id,))
        con.commit()

        partes = conteudo_bruto.split('||')
        qr_code_url = partes[0]
        instrucoes = partes[1] if len(partes) > 1 else "Escaneie o QR Code abaixo para ativar o seu e-SIM."

        try:
            url_telegram_photo = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            caption_text = f"🎉 **COMPRA REALIZADA COM SUCESSO!**\n\n📱 **Operadora:** {payload.produto_id.split('_')[0].upper()}\n📊 **Franquia:** {esim_gb}\n📞 **DDD:** {esim_ddd}\n\n{instrucoes}"

            if qr_code_url.startswith("data:image"):
                header, encoded = qr_code_url.split(",", 1)
                image_data = base64.b64decode(encoded)
                files = {'photo': ('esim_qrcode.png', BytesIO(image_data), 'image/png')}
                data = {'chat_id': payload.chat_id, 'caption': caption_text, 'parse_mode': 'Markdown'}
                requests.post(url_telegram_photo, data=data, files=files, timeout=15)
            else:
                payload_photo = {
                    "chat_id": payload.chat_id,
                    "photo": qr_code_url,
                    "caption": caption_text,
                    "parse_mode": "Markdown"
                }
                requests.post(url_telegram_photo, data=payload_photo, timeout=10)
        except Exception as err_tg:
            logging.error(f"Erro ao enviar foto no Telegram: {err_tg}")

        return {
            "status": "sucesso",
            "mensagem": "Compra efetuada com sucesso!",
            "qr_code_url": qr_code_url,
            "instrucoes": instrucoes,
            "ddd": esim_ddd,
            "gb": esim_gb,
            "novo_saldo": saldo - preco_item
        }
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
    finally:
        con.close()

class PayloadRecargaMiniApp(BaseModel):
    chat_id: str
    valor: float


@app.post("/api/gerar-pix-miniapp")
async def gerar_pix_miniapp(payload: PayloadRecargaMiniApp):
    user_id = str(payload.chat_id).strip()
    valor = float(payload.valor)

    if not user_id or valor <= 0:
        raise HTTPException(
            status_code=400, detail="Dados de recarga inválidos."
        )

    # Reutiliza suas configurações da PushinPay já existentes no código
    headers = {
        "Authorization": f"Bearer {PUSHINPAY_TOKEN}",
        "Content-Type": "application/json",
    }

    body = {
        "value": int(valor * 100),  # Converte R$ para centavos
        "webhook_url": f"{URL_BACKEND}/webhook/pushinpay",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.pushinpay.com.br/api/pix/cashIn",
                json=body,
                headers=headers,
            )
            data = resp.json()

            pix_copia_cola = data.get("qr_code") or data.get("pix_copia_cola")
            qr_code_url = data.get("qr_code_base64") or ""

            if qr_code_url and not qr_code_url.startswith("data:image"):
                qr_code_url = f"data:image/png;base64,{qr_code_url}"

            return {
                "status": "sucesso",
                "pix_copia_cola": pix_copia_cola,
                "qr_code_url": qr_code_url,
            }
    except Exception as e:
        return {
            "status": "erro",
            "detalhe": f"Falha ao gerar cobrança PIX: {str(e)}",
        }

@app.post("/api/admin/gerar-pix-site")
async def gerar_pix_site(payload: GerarPixPayload):
    try:
        url_pushin = "https://api.pushinpay.com.br/api/pix/cashIn"
        headers = {
            "Authorization": f"Bearer {PUSHINPAY_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        body = {
            "value": int(payload.valor * 100),
            "webhook_url": "https://bot-esim-yure.onrender.com/webhook/pushinpay"
        }
        res = requests.post(url_pushin, json=body, headers=headers, timeout=15)
        dados = res.json()
        if res.status_code in [200, 201]:
            return {"status": "sucesso", "qr_code": dados.get("qr_code") or dados.get("emv")}
        return {"status": "erro", "detalhe": dados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/adicionar-estoque")
async def admin_adicionar_estoque(payload: AdminAuthAddEsimPayload):
    if payload.usuario_admin != USUARIO_ADMIN_MINISITE or payload.senha_admin != SENHA_ADMIN_MINISITE:
        raise HTTPException(status_code=401, detail="Credenciais Administrativas Inválidas!")

    conteudo_final = f"{payload.conteudo_esim}||{payload.texto_instrucoes}"

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO estoque_codigos (produto_id, conteudo_esim, ddd, gb) VALUES (?, ?, ?, ?)", 
            (payload.produto_id, conteudo_final, payload.ddd, payload.gb)
        )
        cur.execute("UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = ?", (payload.produto_id,))
        con.commit()
        return {"status": "sucesso", "mensagem": f"e-SIM {payload.gb} (DDD {payload.ddd}) adicionado ao estoque!"}
    finally:
        con.close()

@app.get("/api/admin/metricas")
async def obter_metricas_admin(usuario_admin: str, senha_admin: str):
    if usuario_admin != USUARIO_ADMIN_MINISITE or senha_admin != SENHA_ADMIN_MINISITE:
        raise HTTPException(status_code=401, detail="Não autorizado")

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM carteira")
        total_usuarios = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM acessos_miniapp")
        total_acessos_app = cur.fetchone()[0]

        cur.execute("SELECT chat_id, first_name, username, saldo FROM carteira ORDER BY data_criacao DESC LIMIT 10")
        lista_usuarios = [dict(row) for row in cur.fetchall()]

        return {
            "status": "sucesso",
            "total_usuarios_bot": total_usuarios,
            "total_acessos_miniapp": total_acessos_app,
            "usuarios": lista_usuarios
        }
    finally:
        con.close()

@app.post("/api/admin/criar-giftcard")
async def admin_criar_giftcard(payload: CriarGiftcardPayload):
    if payload.usuario_admin != USUARIO_ADMIN_MINISITE or payload.senha_admin != SENHA_ADMIN_MINISITE:
        raise HTTPException(status_code=401, detail="Credenciais inválidas!")

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("INSERT INTO giftcards (codigo, valor) VALUES (?, ?)", (payload.codigo.upper().strip(), payload.valor))
        con.commit()
        return {"status": "sucesso", "mensagem": f"Gift Card '{payload.codigo.upper()}' no valor de R$ {payload.valor:.2f} criado com sucesso!"}
    except Exception:
        raise HTTPException(status_code=400, detail="Este código de Gift Card já existe!")
    finally:
        con.close()

@app.post("/api/resgatar-giftcard")
async def resgatar_giftcard(payload: ResgatarGiftcardPayload):
    codigo_clean = payload.codigo.upper().strip()

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT valor, usado FROM giftcards WHERE UPPER(codigo) = ?", (codigo_clean,))
        gc = cur.fetchone()

        if not gc:
            return {"status": "erro", "detalhe": "Código de Gift Card inválido!"}
        if gc["usado"] == 1:
            return {"status": "erro", "detalhe": "Este Gift Card já foi resgatado!"}

        valor_gc = float(gc["valor"])

        cur.execute("UPDATE carteira SET saldo = saldo + ? WHERE chat_id = ?", (valor_gc, payload.chat_id))
        cur.execute("UPDATE giftcards SET usado = 1, usado_por = ? WHERE UPPER(codigo) = ?", (payload.chat_id, codigo_clean))
        con.commit()

        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (payload.chat_id,))
        res_saldo = cur.fetchone()
        novo_saldo = float(res_saldo["saldo"]) if res_saldo else valor_gc

        return {
            "status": "sucesso",
            "mensagem": f"🎉 R$ {valor_gc:.2f} adicionados à sua carteira!",
            "novo_saldo": novo_saldo
        }
    except Exception as e:
        con.rollback()
        return {"status": "erro", "detalhe": f"Erro interno: {str(e)}"}
    finally:
        con.close()

class NovoCupom(BaseModel):
    codigo: str
    valor: float


@app.post("/api/admin/cupons")
async def adicionar_cupom(
    cupom: NovoCupom, authorization: str = Header(None)
):
    if authorization != f"Bearer {PUSHINPAY_TOKEN}":
        raise HTTPException(
            status_code=401, detail="Acesso negado! Nao autorizado."
        )

    codigo_limpo = cupom.codigo.strip().upper()
    valor_float = float(cupom.valor)

    con = conectar_banco()
    cur = con.cursor()
    try:
        # Garante que a tabela giftcards existe
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS giftcards (
                codigo TEXT PRIMARY KEY,
                valor REAL,
                usado INTEGER DEFAULT 0,
                usado_por TEXT
            )
        """
        )

        # Insere ou atualiza o valor do Gift Card no banco
        cur.execute(
            """
            INSERT INTO giftcards (codigo, valor, usado)
            VALUES (?, ?, 0)
            ON CONFLICT(codigo) DO UPDATE SET valor = excluded.valor, usado = 0
        """,
            (codigo_limpo, valor_float),
        )

        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        raise HTTPException(
            status_code=500, detail=f"Erro no banco de dados: {str(e)}"
        )
    finally:
        con.close()

    # Também salva no JSON para backup
    dados = carregar_dados()
    if "cupons" not in dados or not isinstance(dados["cupons"], dict):
        dados["cupons"] = {}
    dados["cupons"][codigo_limpo] = valor_float
    salvar_dados(dados)
    salvar_dados_no_github(dados)

    return {"sucesso": True, "codigo": codigo_limpo, "valor": valor_float}

# ------------------------------------------------------------------------------
# 🟢 RUNNER DA APLICAÇÃO
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
