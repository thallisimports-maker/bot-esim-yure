import os
import json
import logging
import urllib.parse
import shutil
import sqlite3
import requests
import qrcode
import threading
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# 🔒 CREDENCIAIS E CONSTANTES
TOKEN = "8826676433:AAHy2DkXR1TH7u4T-JO8FaOCQebFdryOg-M"
PUSHINPAY_TOKEN = "71078|M1MASBFV155gtnKBttSvkE6u8bD8kSBFjAMLwOXa70ca5a25"
SENHA_ADMIN_MINISITE = "yure123"
PASTA_IMAGENS = "imagens_chips"

if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)

# 🚀 INICIALIZAÇÃO DO FASTAPI E CORS NATIVO (Resolve o Preflight OPTIONS do Chrome)
app = FastAPI(title="eSIM Bot & Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite chamadas do GitHub Pages e de qualquer origem
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🏦 BANCO DE DADOS
def conectar_banco():
    con = sqlite3.connect("banco_usuarios.db")
    con.row_factory = sqlite3.Row
    return con

def inicializar_banco():
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS carteira (chat_id TEXT PRIMARY KEY, saldo REAL DEFAULT 0.0)")
        cur.execute("CREATE TABLE IF NOT EXISTS estoque (produto_id TEXT PRIMARY KEY, quantidade INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id TEXT, conteudo_esim TEXT)")
        cur.execute("SELECT COUNT(*) FROM estoque")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('vivo_30gb', 0), ('tim_40gb', 0), ('claro_40gb', 0)")
        con.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco: {e}")
    finally:
        con.close()

# 🌐 SCHEMAS E ROTAS DO FASTAPI (SITE WEB / GITHUB PAGES)
class PixSitePayload(BaseModel):
    valor: float = Field(..., gte=10.0, description="Valor do Pix em Reais (Mínimo R$ 10,00)")

@app.post("/api/admin/gerar-pix-site")
async def api_gerar_pix_site(payload: PixSitePayload):
    """
    Rota para o index.html (GitHub Pages) solicitar a geração de Pix de forma segura.
    O CORS é tratado nativamente pelo CORSMiddleware.
    """
    valor_centavos = int(payload.valor * 100)
    url_api = "https://api.pushinpay.com.br/api/pix/cashIn"
    
    headers = {
        "Authorization": f"Bearer {PUSHINPAY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    body = {
        "value": valor_centavos,
        "webhook_url": "https://thallisimports-maker.github.io/bot-esim-yure/",
        "external_id": "venda_site_web",
        "split_rules": [],
        "customer": {
            "name": "Cliente Web Store",
            "email": "cliente_esim@gmail.com",
            "document": "03620633037"
        }
    }
    
    try:
        resposta = requests.post(url_api, json=body, headers=headers, timeout=15)
        if resposta.status_code in (200, 201):
            dados = resposta.json()
            return {
                "status": "sucesso",
                "qr_code": dados.get("qr_code"),
                "qr_code_base64": dados.get("qr_code_base64")
            }
        return {"status": "erro", "detalhe": resposta.text}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro na comunicação com a PushinPay: {str(e)}"
        )

# 🤖 HANDLERS DO BOT DO TELEGRAM
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    saldo = 0.0
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res = cur.fetchone()
        if res:
            saldo = float(res["saldo"])
        else:
            cur.execute("INSERT INTO carteira (chat_id, saldo) VALUES (?, 0.0)", (chat_id,))
            con.commit()
        cur.execute("SELECT produto_id, quantidade FROM estoque")
        est = {row["produto_id"]: row["quantidade"] for row in cur.fetchall()}
    except Exception:
        est = {}
    finally:
        con.close()

    texto = f"Olá, {user.first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    botoes = [
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")],
        [InlineKeyboardButton("➕ Adicionar Saldo (Pix)", url="https://thallisimports-maker.github.io/bot-esim-yure/")]
    ]
    banner_url = "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"
    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, reply_markup=InlineKeyboardMarkup(botoes))

async def processar_compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    produto_id = query.data.replace("buy_", "")
    precos = {"vivo_30gb": 25.0, "tim_40gb": 30.0, "claro_40gb": 35.0}
    preco_item = precos.get(produto_id, 999.0)
    
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0
        
        if saldo < preco_item:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ **Saldo Insuficiente!** Digite /pix <valor> para recarregar.")
            return

        cur.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (produto_id,))
        chip = cur.fetchone()
        if not chip:
            await context.bot.send_message(chat_id=chat_id, text="❌ **Estoque esgotado!** Tente novamente mais tarde.")
            return

        chip_id, caminho_foto = chip["id"], chip["conteudo_esim"]
        cur.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, chat_id))
        cur.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
        cur.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (produto_id,))
        con.commit()

        if os.path.exists(caminho_foto):
            with open(caminho_foto, "rb") as f:
                await context.bot.send_photo(chat_id=chat_id, photo=f, caption=f"🎉 **COMPRA REALIZADA!**\ne-SIM ({produto_id.upper()}) ativo!")
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"🎉 **COMPRA REALIZADA!**\nSua chave/QR-Code e-SIM: {caminho_foto}")
            
    except Exception as e:
        logging.error(f"Erro no processamento da compra: {e}")
        await context.bot.send_message(chat_id=chat_id, text="🎉 **COMPRA REALIZADA!**\n\nErro ao carregar os dados do chip, solicite suporte.")
    finally:
        con.close()

async def generar_fluxo_pix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = update.effective_chat.id
    
    if not context.args:
        msg_ajuda = "➕ **COMO ADICIONAR SALDO:**\n\nPara gerar um QR Code Pix, digite `/pix` seguido do valor desejado.\n\n👉 **Exemplo:** `/pix 25` (Adiciona R$ 25,00)\n\n⚠️ *Mínimo: R$ 10,00.*"
        await context.bot.send_message(chat_id=chat_id, text=msg_ajuda, parse_mode="Markdown")
        return

    try:
        valor_digitado = float("".join(context.args).replace(",", "."))
        if valor_digitado < 10.0:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ *O valor mínimo para gerar o Pix é de R$ 10,00.*", parse_mode="Markdown")
            return
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="❌ *Valor inválido! Exemplo: `/pix 15`*", parse_mode="Markdown")
        return

    # Geração do Pix no Telegram via PushinPay
    valor_centavos = int(valor_digitado * 100)
    url_api = "https://api.pushinpay.com.br/api/pix/cashIn"
    headers = {
        "Authorization": f"Bearer {PUSHINPAY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "value": valor_centavos,
        "webhook_url": "https://thallisimports-maker.github.io/bot-esim-yure/",
        "external_id": f"recarga_{chat_id}"
    }

    try:
        res = requests.post(url_api, json=payload, headers=headers, timeout=15)
        if res.status_code in (200, 201):
            dados = res.json()
            qr_code = dados.get("qr_code", "QR Code indisponível")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ **PIX GERADO COM SUCESSO!**\n\nValor: R$ {valor_digitado:.2f}\n\n**Copia e Cola:**\n`{qr_code}`",
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Erro ao comunicar com a gateway de pagamento.")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Falha no processamento: {str(e)}")

# 🚀 INICIALIZAÇÃO UNIFICADA DO SERVIDOR
def rodar_fastapi():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

def main() -> None:
    inicializar_banco()
    
    # Inicia a API Web em uma thread paralela
    thread_api = threading.Thread(target=rodar_fastapi, daemon=True)
    thread_api.start()

    # Inicia o Bot do Telegram na thread principal
    telegram_app = Application.builder().token(TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(processar_compra, pattern="^buy_"))
    telegram_app.add_handler(CommandHandler("pix", generar_fluxo_pix))
    
    print("\n🤖 [STATUS] Servidor unificado FastAPI + Telegram rodando perfeitamente!")
    
    # Derruba webhooks pendentes e roda em modo polling
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
