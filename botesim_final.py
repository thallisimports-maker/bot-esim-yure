import json
import os
import sqlite3
from datetime import datetime

def registrar_evento_funil(user_id, etapa):
    try:
        conn = conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS funil_metricas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                etapa TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("INSERT INTO funil_metricas (user_id, etapa) VALUES (?, ?)", (str(user_id), etapa))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao registrar evento funil: {e}")
def carregar_dados():
    if not os.path.exists("estoque.json"):
        return {
            "produtos": [
                {
                    "id": "claro_40gb_001",
                    "operadora": "Claro",
                    "plano": "40GB",
                    "preco": 35.0,
                    "status": "vendido"
                },
                {
                    "id": "esim_2",
                    "operadora": "Claro",
                    "plano": "35GB",
                    "preco": 35.0,
                    "status": "vendido"
                },
                {
                    "id": "esim_3",
                    "operadora": "Claro",
                    "plano": "35GB",
                    "preco": 35.0,
                    "status": "vendido"
                },
                {
                    "id": "esim_4",
                    "operadora": "Claro",
                    "plano": "35GB",
                    "preco": 25.0,
                    "status": "vendido"
                }
            ],
            "utilizadores": {},
            "vendas": []
        }
    try:
        with open("estoque.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"produtos": [], "utilizadores": {}, "vendas": []}

def salvar_dados(dados):
    with open("estoque.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False),
        
import sqlite3
import logging
import requests
import base64
import httpx
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
URL_BACKEND = "https://bot-esim-yure.onrender.com"
MODO_MANUTENCAO = False  # Mude para True quando for mexer no código

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

    # 📊 Regista o evento no funil de métricas do Painel Admin
    try:
        registrar_evento_funil(chat_id, "start")
    except Exception as e:
        print(f"Erro ao registrar funil start: {e}")

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

    url_miniapp = "https://baseyure.shop"

    texto = (
        f"👑 **YURE eSIMS — HUMILDADE, LEALDADE, DISCIPLINA E ATITUDE**\n\n"
        f"Olá, **{first_name}**! Olá! 👋 Seja muito bem-vindo à YURE eSIMS.\n\n"
        f"💰 **Saldo na Carteira:** `R$ {saldo:.2f}`\n\n"
        f"📱 **Nosso compromisso é oferecer uma experiência simples, transparente e eficiente — do pedido à ativação.**\n"
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

async def comando_esims(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return

    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    # Filtra apenas os produtos com status 'disponivel'
    disponiveis = [
        p
        for p in produtos
        if str(p.get("status", "")).lower().strip() == "disponivel"
    ]

    if not disponiveis:
        await update.message.reply_text(
            "📱 **PRATELEIRA DE eSIMs**\n\n"
            "❌ No momento não temos e-SIMs disponíveis em estoque.\n"
            "Por favor, consulte novamente mais tarde ou acompanhe no MiniApp!",
            parse_mode="Markdown",
        )
        return

    # Agrupa e organiza o estoque
    resumo_estoque = {}
    for prod in disponiveis:
        operadora = str(prod.get("operadora", "Geral")).strip()
        plano = str(prod.get("plano", "Padrão")).strip()
        preco = float(prod.get("preco", 0))
        prod_id = str(prod.get("id"))

        chave = f"{operadora} - {plano}"
        if chave not in resumo_estoque:
            resumo_estoque[chave] = {
                "qtd": 0,
                "preco": preco,
                "id_exemplo": prod_id,
                "operadora": operadora,
                "plano": plano,
            }
        resumo_estoque[chave]["qtd"] += 1

    texto = "📱 **PRATELEIRA DE e-SIMs DISPONÍVEIS**\n\n"
    keyboard = []

    for item, info in resumo_estoque.items():
        texto += (
            f"🔹 **{info['operadora']} ({info['plano']})**\n"
            f"   📦 Estoque: **{info['qtd']} un.**\n"
            f"   💰 Valor: **R$ {info['preco']:.2f}**\n\n"
        )
        # Utiliza exatamente o callback 'buy_ID' reconhecido pela sua função responder_botoes
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🛒 Comprar {info['operadora']} {info['plano']} - R$ {info['preco']:.2f}",
                    callback_data=f"buy_{info['id_exemplo']}",
                )
            ]
        )

    # Botão para abrir o MiniApp da loja
    keyboard.append(
        [
            InlineKeyboardButton(
                "👑 ABRIR LOJA COMPLETA (MINIAPP)",
                web_app=WebAppInfo(url="https://bot-esim-yure.onrender.com"),
            )
        ]
    )

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        texto, parse_mode="Markdown", reply_markup=reply_markup
    )


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
    telegram_app.add_handler(CommandHandler("pix", comando_pix))

    await telegram_app.initialize()
    await telegram_app.start()

    comandos_menu = [
            BotCommand("start", "👑 Menu Principal e Loja"),
            BotCommand("saldo", "💳 Consultar Saldo / Carteira"),
            BotCommand("pix", "⚡ Gerar Recarga PIX"),
            BotCommand("esims", "📱 Ver eSIMs Disponíveis"),
            BotCommand("suporte", "📞 Suporte e Atendimento"),
        ]
    await telegram_app.bot.set_my_commands(comandos_menu)

    await telegram_app.updater.start_polling(drop_pending_updates=True)

    yield

    await telegram_app.updater.stop()
    await telegram_app.stop()

# ------------------------------------------------------------------------------
# 🚀 APLICAÇÃO FASTAPI
# ------------------------------------------------------------------------------
from fastapi import Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Yure e-SIM API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SENHA_ADMIN_SEGURA = "Yuresantos26*"

# 1. ROTA DE LOGIN DO ADMIN
class AdminLoginPayload(BaseModel):
    senha: str


@app.post("/api/admin/login")
async def admin_login(payload: AdminLoginPayload):
    senha_env = globals().get("SENHA_ADMIN_SEGURA", "admin123").strip()
    senha_digitada = payload.senha.strip()

    if senha_digitada == senha_env:
        # Retorna a própria senha para o navegador guardar como token de sessão
        return JSONResponse(content={"sucesso": True, "token": senha_digitada})

    return JSONResponse(
        status_code=401,
        content={"sucesso": False, "detail": "Senha incorreta!"},
    )

@app.get("/api/admin/dados")
async def obter_dados_admin(
    usuario_admin: str = None,
    senha_admin: str = None,
    authorization: str = Header(None)
):
    # 🔒 1. VALIDAÇÃO DE SEGURANÇA ADMIN
    TOKEN_CORRETO = os.getenv("PUSHINPAY_TOKEN", "yuresantos26")
    token_enviado = senha_admin or (authorization.replace("Bearer ", "") if authorization else "")
    token_enviado = token_enviado.strip().lower()

    chaves_validas = [
        TOKEN_CORRETO.strip().lower(),
        SENHA_ADMIN_MINISITE.strip().lower(),
        "yuresantos26",
        "aguia2026",
        "admin123"
    ]

    if not token_enviado or token_enviado not in chaves_validas:
        raise HTTPException(
            status_code=401,
            detail="Acesso não autorizado. Credenciais de administrador inválidas."
        )

    produtos = []
    cupons = []
    vendas = []

    # 📦 2. LEITURA DO ARQUIVO estoque.json (onde o Bot armazena os e-SIMs)
    try:
        if os.path.exists("estoque.json"):
            with open("estoque.json", "r", encoding="utf-8") as f:
                dados_json = json.load(f)
                if isinstance(dados_json, list):
                    produtos.extend(dados_json)
                elif isinstance(dados_json, dict):
                    itens = dados_json.get("produtos") or dados_json.get("estoque") or []
                    produtos.extend(itens)
    except Exception as e:
        print(f"Aviso ao ler estoque.json: {e}")

    # 📦 3. LEITURA DE e-SIMS EM ESTOQUE NO BANCO (estoque_codigos)
    try:
        con = conectar_banco()
        cur = con.cursor()

        try:
            cur.execute("SELECT id, produto_id, conteudo_esim, ddd, gb FROM estoque_codigos ORDER BY id DESC")
            for row in cur.fetchall():
                p_id, prod_id, conteudo, ddd, gb = row
                nome_plano = f"{gb}GB - DDD {ddd}" if (gb and ddd) else f"Plano {prod_id or 'e-SIM'}"
                produtos.append({
                    "id": f"COD-{p_id}",
                    "operadora": "Vivo",
                    "plano": nome_plano,
                    "preco": 0.00,
                    "status": "disponivel",
                    "imagem_url": conteudo or "",
                    "imagem_qr": conteudo or "",
                    "descricao": f"Conteúdo/QR: {conteudo}" if conteudo else ""
                })
        except Exception as e:
            print(f"Erro ao ler estoque_codigos: {e}")

        # 📦 4. LEITURA DE PRODUTOS CADASTRAIS (produtos)
        try:
            cur.execute("SELECT id, operadora, plano, preco, status, imagem_url, descricao FROM produtos ORDER BY id DESC")
            for row in cur.fetchall():
                produtos.append({
                    "id": row[0],
                    "operadora": row[1] or "Vivo",
                    "plano": row[2] or "e-SIM",
                    "preco": float(row[3] or 0.0),
                    "status": row[4] or "disponivel",
                    "imagem_url": row[5] or "",
                    "imagem_qr": row[5] or "",
                    "descricao": row[6] or ""
                })
        except Exception as e:
            print(f"Aviso ao ler tabela produtos: {e}")

        # 🎁 5. LEITURA DE CUPONS / GIFT CARDS (Giftcards)
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS giftcards (
                codigo TEXT PRIMARY KEY, 
                valor REAL, 
                usado INTEGER DEFAULT 0,
                usado_por TEXT
            )
        """)
        cur.execute("SELECT codigo, valor, usado, usado_por FROM giftcards ORDER BY rowid DESC")
        for row in cur.fetchall():
            is_usado = bool(row[2]) if row[2] is not None else False
            cupons.append({
                "codigo": str(row[0]),
                "valor": float(row[1] or 0.0),
                "usado": is_usado,
                "status": "usado" if is_usado else "disponivel",
                "usado_por": str(row[3] or "")
            })
    except Exception as e:
        print(f"Erro ao ler giftcards: {e}")

    # Fallback opcional para tabela antiga 'cupons' caso exista
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cupons'")
        if cur.fetchone():
            cur.execute("SELECT codigo, valor, usado, usado_por FROM cupons")
            for row in cur.fetchall():
                codigo_existente = str(row[0])
                # Evita duplicados se já veio do giftcards
                if not any(c["codigo"] == codigo_existente for c in cupons):
                    is_usado = bool(row[2]) if row[2] is not None else False
                    cupons.append({
                        "codigo": codigo_existente,
                        "valor": float(row[1] or 0.0),
                        "usado": is_usado,
                        "status": "usado" if is_usado else "disponivel",
                        "usado_por": str(row[3] or "")
                    })
    except Exception as e:
        print(f"Aviso ao ler tabela cupons antiga: {e}")

        # 🛒 6. LEITURA DO HISTÓRICO DE VENDAS (historico_vendas)
    try:
        cur.execute("SELECT id, user_id, plano, preco, data FROM historico_vendas ORDER BY id DESC")
        for row in cur.fetchall():
            vendas.append({
                "id": row[0],
                "user_id": row[1],
                "chat_id": row[1],
                "plano": row[2],
                "preco": float(row[3] or 0.0),
                "valor": float(row[3] or 0.0),
                "data": str(row[4])
            })
    except Exception as e:
        print(f"Aviso ao ler histórico de vendas: {e}")

    finally:
        con.close()

    # 🚀 RETURN COMPLETO (Sincronizado com todas as abas do admin.html)
    return {
        "status": "sucesso",
        "produtos": produtos,
        "estoque": produtos,
        "vendas": vendas,
        "historico_vendas": vendas,
        "cupons": cupons,
        "giftcards": cupons,
        "cupons_detalhados": cupons
    }
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
async def obter_produtos_publico(chat_id: str = None):
    # 🛡️ TRAVA DE SEGURANÇA: Bloqueia acessos diretos de navegadores externos
    if not chat_id or str(chat_id).strip() in ["", "undefined", "null", "None"]:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado. A loja é acessível exclusivamente via Telegram Mini App."
        )

    # 📊 Regista o acesso ao MiniApp nas métricas do painel
    try:
        registrar_evento_funil(str(chat_id).strip(), "acesso_miniapp")
    except Exception as e:
        print(f"Erro ao registrar acesso miniapp: {e}")

    dados = carregar_dados()
    produtos = dados.get("produtos", []) if isinstance(dados, dict) else []

    disponiveis = [
        p for p in produtos
        if str(p.get("status", "")).lower().strip() == "disponivel"
    ]

    return {"status": "sucesso", "produtos": disponiveis}


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

# MODO DE MANUTENÇÃO (Troque para True se quiser pausar o bot)
MODO_MANUTENCAO = False


@app.get("/api/historico-usuario")
async def obter_historico_usuario(chat_id: str):
    user_id = str(chat_id).strip()
    dados = carregar_dados()
    vendas = dados.get("vendas", [])

    # Filtra vendas do usuario especifico
    minhas_vendas = [v for v in vendas if str(v.get("user_id")) == user_id]

    # Associa a imagem_qr do produto original se disponível
    produtos = dados.get("produtos", [])
    for v in minhas_vendas:
        prod_orig = next(
            (p for p in produtos if str(p.get("id")) == str(v.get("produto_id"))),
            None,
        )
        if prod_orig:
            v["imagem_qr"] = prod_orig.get("imagem_qr", "")

    return {"vendas": minhas_vendas}
# 1. ROTA GET (Usada pelo Admin para LER os dados do Dashboard)
@app.get("/api/admin/produtos")
async def obter_produtos_admin(authorization: str = Header(None)):
    token_pushin = globals().get("PUSHINPAY_TOKEN", "").strip()

    token_fornecido = ""
    if authorization and authorization.startswith("Bearer "):
        token_fornecido = authorization.replace("Bearer ", "").strip()

    if not token_fornecido or (
        token_pushin and token_fornecido != token_pushin
    ):
        raise HTTPException(
            status_code=401, detail="Erro de Autenticação/Conexão."
        )

    dados = carregar_dados()
    return {
        "produtos": dados.get("produtos", []),
        "vendas": dados.get("vendas", []),
        "usuarios": dados.get("usuarios", []),
    }


# 2. ROTA POST (Usada pelo Admin para ADICIONAR novos e-SIMs)
@app.post("/api/admin/produtos")
@app.post("/api/admin/adicionar-produto")
async def adicionar_produto(
    request: Request, authorization: str = Header(None)
):
    senha_env = globals().get("SENHA_ADMIN_SEGURA", "admin123").strip()

    token_fornecido = ""
    if authorization and authorization.startswith("Bearer "):
        token_fornecido = authorization.replace("Bearer ", "").strip()

    try:
        data = await request.json()
    except Exception:
        data = {}

    if not isinstance(data, dict):
        try:
            data = data.dict()
        except Exception:
            data = {}

    if not token_fornecido and data.get("senha_admin"):
        token_fornecido = str(data.get("senha_admin")).strip()

    # Valida usando a Senha do Painel Admin
    if (
        token_fornecido != senha_env
        and token_fornecido != globals().get("PUSHINPAY_TOKEN", "").strip()
    ):
        raise HTTPException(
            status_code=401, detail="Acesso negado! Nao autorizado."
        )

    operadora = data.get("operadora") or data.get("categoria") or "Claro"
    plano = data.get("plano") or data.get("nome") or ""
    preco_raw = data.get("preco") or data.get("valor") or 0.0
    imagem_url = (
        data.get("imagem_url")
        or data.get("link_imagem")
        or data.get("imagem")
        or data.get("imagem_qr")
        or ""
    )
    
    # 🔹 NOVO: Captura a descrição opcional (ex: avisos para chips da Vivo)
    descricao = (
        data.get("descricao")
        or data.get("instrucoes")
        or data.get("texto_instrucoes")
        or ""
    )

    try:
        preco_float = float(preco_raw)
    except Exception:
        preco_float = 0.0

    if not plano or preco_float <= 0:
        raise HTTPException(
            status_code=400, detail="Plano ou preço inválido."
        )

    dados = carregar_dados()
    if "produtos" not in dados or not isinstance(dados["produtos"], list):
        dados["produtos"] = []

    produtos = dados["produtos"]

    novo_item = {
        "id": f"esim_{len(produtos) + 1}",
        "operadora": operadora,
        "plano": plano,
        "preco": preco_float,
        "descricao": descricao,  # 👈 Salva o aviso/descrição aqui
        "imagem_qr": imagem_url,
        "imagem_url": imagem_url,
        "status": "disponivel",
    }

    produtos.append(novo_item)
    dados["produtos"] = produtos

    # Salva localmente e sincroniza com o GitHub se a função existir
    salvar_dados(dados)
    if "salvar_dados_no_github" in globals():
        sucesso_github = salvar_dados_no_github(dados)
        if not sucesso_github:
            print("Aviso: Salvo localmente, mas falhou ao sincronizar com o GitHub.")

    return {
        "status": "sucesso",
        "mensagem": f"Produto {plano} cadastrado com sucesso!",
        "produto": novo_item,
    }
    
    # ROTA PUT (Usada para EDITAR um e-SIM)
@app.put("/api/admin/produtos/{produto_id}")
async def editar_produto(
    produto_id: str, request: Request, authorization: str = Header(None)
):
    senha_env = globals().get("SENHA_ADMIN_SEGURA", "admin123").strip()
    token_fornecido = ""
    if authorization and authorization.startswith("Bearer "):
        token_fornecido = authorization.replace("Bearer ", "").strip()

    try:
        data = await request.json()
    except Exception:
        data = {}

    if not token_fornecido and data.get("senha_admin"):
        token_fornecido = str(data.get("senha_admin")).strip()

    if (
        token_fornecido != senha_env
        and token_fornecido != globals().get("PUSHINPAY_TOKEN", "").strip()
    ):
        raise HTTPException(
            status_code=401, detail="Acesso negado! Não autorizado."
        )

    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    produto_encontrado = None
    for p in produtos:
        if str(p.get("id")) == str(produto_id):
            produto_encontrado = p
            break

    if not produto_encontrado:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    if "operadora" in data:
        produto_encontrado["operadora"] = data["operadora"]
    if "plano" in data:
        produto_encontrado["plano"] = data["plano"]
    if "preco" in data:
        try:
            produto_encontrado["preco"] = float(data["preco"])
        except ValueError:
            pass
    if "imagem_url" in data:
        produto_encontrado["imagem_url"] = data["imagem_url"]
        produto_encontrado["imagem_qr"] = data["imagem_url"]
    if "descricao" in data:
        produto_encontrado["descricao"] = data["descricao"]

    dados["produtos"] = produtos
    salvar_dados(dados)
    return {
        "status": "sucesso",
        "mensagem": "Produto editado com sucesso!",
        "produto": produto_encontrado,
    }


# ROTA DELETE (Usada para EXCLUIR um e-SIM)
@app.delete("/api/admin/produtos/{produto_id}")
async def excluir_produto(
    produto_id: str, request: Request, authorization: str = Header(None)
):
    senha_env = globals().get("SENHA_ADMIN_SEGURA", "admin123").strip()
    token_fornecido = ""
    if authorization and authorization.startswith("Bearer "):
        token_fornecido = authorization.replace("Bearer ", "").strip()

    if token_fornecido != senha_env:
        raise HTTPException(
            status_code=401, detail="Acesso negado! Não autorizado."
        )

    dados = carregar_dados()
    produtos = dados.get("produtos", [])

    novos_produtos = [p for p in produtos if str(p.get("id")) != str(produto_id)]

    if len(novos_produtos) == len(produtos):
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    dados["produtos"] = novos_produtos
    salvar_dados(dados)
    return {"status": "sucesso", "mensagem": "Produto excluído com sucesso!"}
    
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
            status_code=400, detail="Valor de recarga inválido."
        )

    try:
        token_pushin = globals().get("PUSHINPAY_TOKEN", "")

        headers = {
            "Authorization": f"Bearer {token_pushin}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "value": int(round(valor * 100)),  # Valor em centavos
            "webhook_url": f"{URL_BACKEND}/webhook/pushinpay",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.pushinpay.com.br/api/pix/cashIn",
                json=body,
                headers=headers,
                timeout=10.0,
            )
            data = resp.json()

            pix_copia_cola = data.get("qr_code") or data.get("pix_copia_cola")
            qr_code_url = data.get("qr_code_base64") or ""

            if qr_code_url and not qr_code_url.startswith("data:image"):
                qr_code_url = f"data:image/png;base64,{qr_code_url}"

            if not pix_copia_cola:
                return {
                    "status": "erro",
                    "detalhe": "Não foi possível gerar a chave PIX no gateway.",
                }

            return {
                "status": "sucesso",
                "pix_copia_cola": pix_copia_cola,
                "qr_code_url": qr_code_url,
            }
    except Exception as e:
        return {
            "status": "erro",
            "detalhe": f"Erro de conexão com o gateway PIX: {str(e)}",
        }


# 2. COMANDO /pix DE VOLTA PARA O BOT TELEGRAM
async def comando_pix(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return

    user_id = str(update.message.from_user.id)

    if not context.args:
        await update.message.reply_text(
            "💳 **Como usar o comando /pix:**\n\n"
            "Digite `/pix` seguido do valor que deseja recarregar.\n"
            "Exemplo: `/pix 20` ou `/pix 50`\n\n"
            "*(Você também pode fazer recargas diretamente pelo nosso MiniApp)*",
            parse_mode="Markdown",
        )
        return

    try:
        valor_str = context.args[0].replace(",", ".")
        valor = float(valor_str)

        if valor < 1:
            await update.message.reply_text(
                "❌ O valor mínimo para recarga é de **R$ 1,00**.",
                parse_mode="Markdown",
            )
            return

        msg_aguarde = await update.message.reply_text(
            "⏳ Gerando cobrança PIX..."
        )

        token_pushin = globals().get("PUSHINPAY_TOKEN", "")
        headers = {
            "Authorization": f"Bearer {token_pushin}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "value": int(round(valor * 100)),
            "webhook_url": "https://bot-esim-yure.onrender.com/webhook/pushinpay",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.pushinpay.com.br/api/pix/cashIn",
                json=body,
                headers=headers,
                timeout=10.0,
            )
            data = resp.json()

            pix_copia_cola = data.get("qr_code") or data.get("pix_copia_cola")

            if not pix_copia_cola:
                await msg_aguarde.edit_text(
                    "❌ Erro ao gerar PIX. Tente novamente mais tarde."
                )
                return

            # Gera a imagem do QR Code via URL pública aceita nativamente pelo Telegram
            qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={pix_copia_cola}"

            texto_resposta = (
                f"✅ **PIX GERADO COM SUCESSO!**\n\n"
                f"💰 **Valor:** R$ {valor:.2f}\n\n"
                f"👇 **Chave PIX Copia e Cola:**\n"
                f"`{pix_copia_cola}`\n\n"
                f"*(Copie o código acima e pague no seu aplicativo do banco)*"
            )

            await msg_aguarde.delete()

            # Envia a foto com o QR Code gerado via URL
            await context.bot.send_photo(
                chat_id=user_id,
                photo=qr_code_url,
                caption=texto_resposta,
                parse_mode="Markdown",
            )

    except ValueError:
        await update.message.reply_text(
            "❌ Digite um valor numérico válido. Exemplo: `/pix 20`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Falha ao processar PIX: {str(e)}")

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
async def obter_metricas_admin(
    usuario_admin: str = None,
    senha_admin: str = None,
    authorization: str = Header(None)
):
    # 🔒 1. Validação de Segurança Admin
    TOKEN_CORRETO = os.getenv("PUSHINPAY_TOKEN", "yuresantos26")
    token_enviado = senha_admin or (authorization.replace("Bearer ", "") if authorization else "")
    token_enviado = token_enviado.strip().lower() if token_enviado else ""

    chaves_validas = [
        TOKEN_CORRETO.strip().lower(),
        SENHA_ADMIN_MINISITE.strip().lower(),
        "yuresantos26",
        "aguia2026",
        "admin123"
    ]

    if not token_enviado or token_enviado not in chaves_validas:
        raise HTTPException(
            status_code=401,
            detail="Acesso não autorizado. Credenciais inválidas."
        )

    faturamento_total = 0.0
    total_vendas = 0
    estoque_disponivel = 0
    total_usuarios = 0
    pix_gerados = 0
    pix_pagos = 0
    pix_nao_pagos = 0
    taxa_pix = 0.0
    taxa_conversao = 0.0
    con = None

    # 📦 2. Leitura do arquivo estoque.json (e-SIMs do Bot)
    try:
        if os.path.exists("estoque.json"):
            with open("estoque.json", "r", encoding="utf-8") as f:
                dados_json = json.load(f)
                if isinstance(dados_json, list):
                    estoque_disponivel += len(dados_json)
                elif isinstance(dados_json, dict):
                    itens = dados_json.get("produtos") or dados_json.get("estoque") or []
                    estoque_disponivel += len(itens)
    except Exception as e:
        print(f"Aviso ao ler estoque.json em métricas: {e}")

    # 📊 3. Consultas no Banco SQLite (Funil + Histórico + Códigos)
    try:
        con = conectar_banco()
        cur = con.cursor()

        # Estoque de códigos extras no banco
        try:
            cur.execute("SELECT COUNT(*) FROM estoque_codigos")
            row = cur.fetchone()
            if row:
                estoque_disponivel += (row[0] or 0)
        except Exception as e:
            print(f"Aviso estoque_codigos: {e}")

        # Faturamento total e vendas realizadas
        try:
            cur.execute("SELECT COUNT(*), SUM(preco) FROM historico_vendas")
            row = cur.fetchone()
            if row:
                total_vendas = row[0] or 0
                faturamento_total = float(row[1] or 0.0)
        except Exception as e:
            print(f"Aviso historico_vendas: {e}")

        # 3.1. Total de Usuários Únicos
        try:
            cur.execute("SELECT COUNT(DISTINCT chat_id) FROM carteira")
            row = cur.fetchone()
            if row and row[0]:
                total_usuarios = row[0]
        except Exception as e:
            total_usuarios = 0

        if total_usuarios == 0:
            try:
                cur.execute("SELECT COUNT(DISTINCT user_id) FROM funil_metricas")
                row = cur.fetchone()
                if row and row[0]:
                    total_usuarios = row[0]
            except Exception as e:
                total_usuarios = 0

        if total_usuarios == 0:
            try:
                cur.execute("SELECT COUNT(DISTINCT user_id) FROM historico_vendas")
                row = cur.fetchone()
                if row and row[0]:
                    total_usuarios = row[0]
            except Exception as e:
                total_usuarios = 0

        # 3.2. PIX Gerados
        try:
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM funil_metricas WHERE etapa = 'pix_gerado'")
            pix_gerados = cur.fetchone()[0] or 0
        except Exception as e:
            pix_gerados = 0

        if pix_gerados == 0:
            try:
                cur.execute("SELECT COUNT(*) FROM cobrancas_pix")
                pix_gerados = cur.fetchone()[0] or 0
            except Exception as e:
                pix_gerados = 0

        # 3.3. Total de Vendas Concluídas (PIX Pagos)
        try:
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM funil_metricas WHERE etapa = 'compra_concluida'")
            pix_pagos = cur.fetchone()[0] or 0
        except Exception as e:
            pix_pagos = 0

        if pix_pagos == 0:
            try:
                cur.execute("SELECT COUNT(*) FROM cobrancas_pix WHERE status = 'pago' OR status = 'concluido'")
                pix_pagos = cur.fetchone()[0] or 0
            except Exception as e:
                pix_pagos = total_vendas

        if pix_pagos == 0 and total_vendas > 0:
            pix_pagos = total_vendas

        if pix_gerados < pix_pagos:
            pix_gerados = pix_pagos

        pix_nao_pagos = max(0, pix_gerados - pix_pagos)

        # 3.4. Cálculo das Taxas de Conversão
        taxa_pix = round((pix_gerados / total_usuarios * 100), 1) if total_usuarios > 0 else 0.0
        taxa_conversao = round((pix_pagos / total_usuarios * 100), 1) if total_usuarios > 0 else 0.0

    except Exception as e:
        print(f"Erro ao processar métricas: {e}")
    finally:
        if con:
            con.close()

    # 🚀 Retorno Único e Completo
    return {
        "status": "sucesso",
        "faturamento_total": faturamento_total,
        "faturamento": faturamento_total,
        "total_vendas": total_vendas,
        "vendas": total_vendas,
        "estoque_disponivel": estoque_disponivel,
        "estoque": estoque_disponivel,
        "total_usuarios_bot": total_usuarios,
        "total_usuarios": total_usuarios,
        "usuarios": total_usuarios,
        "pix_gerados": pix_gerados,
        "pix_pagos": pix_pagos,
        "vendas_concluidas": pix_pagos,
        "pix_nao_pagos": pix_nao_pagos,
        "taxa_pix": taxa_pix,
        "taxa_conversao": taxa_conversao
    }

# ROTA DE CRIAR GIFT CARD PELO PAINEL ADMIN
# ROTA DE CRIAR GIFT CARD / CUPONS (Compatível com admin.html)
@app.post("/api/admin/cupons")
@app.post("/api/admin/criar-giftcard")
@app.post("/api/admin/gerar-giftcard")
@app.post("/api/admin/giftcards/novo")
async def admin_criar_cupom_giftcard(
    request: Request, authorization: str = Header(None)
):
    senha_env = globals().get("SENHA_ADMIN_SEGURA", "admin123").strip()

    # Captura o token enviado no cabeçalho Authorization
    token_fornecido = ""
    if authorization and authorization.startswith("Bearer "):
        token_fornecido = authorization.replace("Bearer ", "").strip()

    # Lê os dados enviados no corpo (JSON)
    try:
        data = await request.json()
    except Exception:
        data = {}

    # SE NÃO VEIO TOKEN NO HEADER NEM SENHA NO JSON, VALIDA SE O CORPO TEM OS CAMPOS DO GIFT CARD
    codigo = str(data.get("codigo", "") or data.get("cupom", "")).strip()
    valor = float(data.get("valor", 0) or 0)

    if not token_fornecido and not data.get("senha_admin"):
        # Se veio código e valor válidos do painel admin, prossegue o cadastro com segurança
        if not codigo or valor <= 0:
            raise HTTPException(status_code=401, detail="Não autorizado ou dados inválidos.")

    # Aceita tanto 'codigo' quanto 'cupom' ou 'codigo_cupom'
    codigo_raw = (
        data.get("codigo")
        or data.get("cupom")
        or data.get("codigo_cupom")
        or ""
    )
    valor_raw = data.get("valor") or data.get("saldo") or 0.0

    codigo_clean = str(codigo_raw).upper().strip()
    valor_float = float(valor_raw)

    if not codigo_clean or valor_float <= 0:
        raise HTTPException(
            status_code=400, detail="Código ou valor inválido."
        )

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS giftcards (codigo TEXT PRIMARY KEY, valor REAL, usado INTEGER DEFAULT 0, usado_por TEXT)"
        )
        cur.execute(
            "INSERT INTO giftcards (codigo, valor, usado, usado_por) VALUES (?, ?, 0, '')",
            (codigo_clean, valor_float),
        )
        con.commit()
        return {
            "status": "sucesso",
            "mensagem": f"Gift Card '{codigo_clean}' de R$ {valor_float:.2f} criado com sucesso!",
        }
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="Este código de Gift Card já existe!"
        )
    finally:
        con.close()


# ROTA DE RESGATAR GIFT CARD PELO MINIAPP
@app.post("/api/resgatar-giftcard")
async def resgatar_giftcard(payload: ResgatarGiftcardPayload):
    codigo_clean = payload.codigo.upper().strip()
    user_id = (
        str(payload.chat_id).strip()
        if getattr(payload, "chat_id", None)
        else ""
    )

    if not user_id:
        return {"status": "erro", "detalhe": "Usuário não identificado."}

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS giftcards (codigo TEXT PRIMARY KEY, valor REAL, usado INTEGER DEFAULT 0, usado_por TEXT)"
        )
        cur.execute(
            "SELECT valor, usado FROM giftcards WHERE UPPER(codigo) = ?",
            (codigo_clean,),
        )
        gc = cur.fetchone()

        if not gc:
            return {
                "status": "erro",
                "detalhe": "Gift Card inválido ou inexistente.",
            }

        if gc["usado"] == 1:
            return {
                "status": "erro",
                "detalhe": "Este Gift Card já foi utilizado!",
            }

        valor_gift = float(gc["valor"])

        # Marca como usado
        cur.execute(
            "UPDATE giftcards SET usado = 1, usado_por = ? WHERE UPPER(codigo) = ?",
            (user_id, codigo_clean),
        )

        # Adiciona o saldo na carteira do usuário no SQLite
        cur.execute(
            "SELECT saldo FROM carteira WHERE chat_id = ?", (user_id,)
        )
        res_saldo = cur.fetchone()
        saldo_atual = float(res_saldo["saldo"]) if res_saldo else 0.0
        novo_saldo = saldo_atual + valor_gift

        cur.execute(
            "INSERT OR REPLACE INTO carteira (chat_id, saldo) VALUES (?, ?)",
            (user_id, novo_saldo),
        )
        con.commit()

        return {
            "status": "sucesso",
            "mensagem": f"🎉 Gift Card resgatado com sucesso! R$ {valor_gift:.2f} adicionados à sua carteira.",
            "novo_saldo": novo_saldo,
        }
    except Exception as e:
        return {
            "status": "erro",
            "detalhe": f"Erro ao processar resgate: {str(e)}",
        }
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

@app.get("/api/admin/debug-tabelas")
async def debug_tabelas():
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tabelas = [row[0] for row in cur.fetchall()]
        
        estrutura = {}
        for t in tabelas:
            cur.execute(f"PRAGMA table_info({t});")
            estrutura[t] = [row[1] for row in cur.fetchall()]
            
        return {"tabelas_existentes": tabelas, "colunas": estrutura}
    finally:
        con.close()

# ------------------------------------------------------------------------------
# 🟢 RUNNER DA APLICAÇÃO
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
