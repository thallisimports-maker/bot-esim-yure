import os
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# ------------------------------------------------------------------------------
# 🔒 CREDENCIAIS E CONSTANTES DE PRODUÇÃO
# ------------------------------------------------------------------------------
TOKEN = "8826676433:AAEjicVbEpow_dbalsja15hFYCghRwAq0D0"
PUSHINPAY_TOKEN = "71078|M1MASBFV155gtnKBttSvkE6u8bD8kSBFjAMLwOXa70ca5a25"

# 🛡️ CREDENCIAIS DE SEGURANÇA DO PAINEL ADMIN
USUARIO_ADMIN_MINISITE = "yure_admin"
SENHA_ADMIN_MINISITE = "yure123"

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
        cur.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id TEXT, conteudo_esim TEXT)")
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
# 🤖 LÓGICA DO BOT DO TELEGRAM
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

    url_miniapp = "https://thallisimports-maker.github.io/bot-esim-yure/"
    banner_url = "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"

    texto = f"Olá, {first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    
    botoes = [
        [InlineKeyboardButton("📱 ABRIR LOJA / CARTEIRA (MINIAPP)", web_app=WebAppInfo(url=url_miniapp))]
    ]

    qtd_vivo = est.get('vivo_30gb', 0)
    if qtd_vivo > 0:
        botoes.append([InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({qtd_vivo} un)", callback_data="buy_vivo_30gb")])

    qtd_tim = est.get('tim_40gb', 0)
    if qtd_tim > 0:
        botoes.append([InlineKeyboardButton(f"Tim 40GB - R$ 30 ({qtd_tim} un)", callback_data="buy_tim_40gb")])

    qtd_claro = est.get('claro_40gb', 0)
    if qtd_claro > 0:
        botoes.append([InlineKeyboardButton(f"Claro 40GB - R$ 35 ({qtd_claro} un)", callback_data="buy_claro_40gb")])

    if len(botoes) == 1:
        texto += "\n\n⚠️ *Atualmente todos os planos estão esgotados no estoque. Abra o MiniApp para novidades!*"

    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

# ------------------------------------------------------------------------------
# ⚙️ GESTOR DE LIFESPAN DA APLICAÇÃO (FASTAPI + TELEGRAM BOT)
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    
    yield
    
    await telegram_app.updater.stop()
    await telegram_app.stop()

# ------------------------------------------------------------------------------
# 🚀 APLICAÇÃO FASTAPI (ROTAS DO ADMIN E MINIAPP)
# ------------------------------------------------------------------------------
app = FastAPI(title="Yure e-SIM API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CompraMiniAppPayload(BaseModel):
    chat_id: str
    produto_id: str

class AdminAuthAddEsimPayload(BaseModel):
    usuario_admin: str
    senha_admin: str
    produto_id: str
    conteudo_esim: str
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

        cur.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (payload.produto_id,))
        chip = cur.fetchone()
        if not chip:
            return {"status": "erro", "detalhe": "Estoque esgotado para este produto!"}

        chip_id, conteudo_bruto = chip["id"], chip["conteudo_esim"]

        cur.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, payload.chat_id))
        cur.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
        cur.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (payload.produto_id,))
        con.commit()

        partes = conteudo_bruto.split('||')
        qr_code_url = partes[0]
        instrucoes = partes[1] if len(partes) > 1 else "Escaneie o QR Code abaixo para ativar o seu e-SIM."

        # DISPARA A FOTO NO TELEGRAM (SUPORTA URL OU BASE64 ENVIADO DO PC)
        try:
            url_telegram_photo = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            caption_text = f"🎉 **COMPRA REALIZADA COM SUCESSO!**\n\n{instrucoes}\n\n📱 **Plano:** {payload.produto_id.upper()}"

            if qr_code_url.startswith("data:image"):
                # Se for Base64 (upload do PC), converte e envia como arquivo binário
                header, encoded = qr_code_url.split(",", 1)
                image_data = base64.b64decode(encoded)
                files = {'photo': ('esim_qrcode.png', BytesIO(image_data), 'image/png')}
                data = {'chat_id': payload.chat_id, 'caption': caption_text, 'parse_mode': 'Markdown'}
                requests.post(url_telegram_photo, data=data, files=files, timeout=15)
            else:
                # Se for link normal (URL)
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
            "novo_saldo": saldo - preco_item
        }
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
    finally:
        con.close()

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
        cur.execute("INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (?, ?)", (payload.produto_id, conteudo_final))
        cur.execute("UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = ?", (payload.produto_id,))
        con.commit()
        return {"status": "sucesso", "mensagem": f"e-SIM adicionado ao estoque de {payload.produto_id.upper()}!"}
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
        cur.execute("SELECT valor, usado FROM giftcards WHERE codigo = ?", (codigo_clean,))
        gc = cur.fetchone()

        if not gc:
            return {"status": "erro", "detalhe": "Código de Gift Card inválido!"}
        if gc["usado"] == 1:
            return {"status": "erro", "detalhe": "Este Gift Card já foi resgatado!"}

        valor_gc = float(gc["valor"])

        cur.execute("UPDATE carteira SET saldo = saldo + ? WHERE chat_id = ?", (valor_gc, payload.chat_id))
        cur.execute("UPDATE giftcards SET usado = 1, usado_por = ? WHERE codigo = ?", (payload.chat_id, codigo_clean))
        con.commit()

        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (payload.chat_id,))
        novo_saldo = float(cur.fetchone()["saldo"])

        return {
            "status": "sucesso",
            "mensagem": f"🎉 R$ {valor_gc:.2f} adicionados à sua carteira!",
            "novo_saldo": novo_saldo
        }
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
    finally:
        con.close()

# ------------------------------------------------------------------------------
# 🟢 RUNNER DA APLICAÇÃO NA RENDER
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
