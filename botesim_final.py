import os
import json
import logging
import urllib.parse
import shutil
import sqlite3
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = "8826676433:AAGihzAzXlduLt6yvV2hBGuDSJIiqlppWbo"
PUSHINPAY_TOKEN = "71037|z3q7oDUiZHaGhooOUPiRXJct31dt2nXkAjqJ0efzdb7ec317"
SENHA_ADMIN_MINISITE = "yure123"
DATABASE_URL_NUVEM = "COLE_AQUI"

PASTA_IMAGENS = "imagens_chips"
if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)

def conectar_banco():
    if DATABASE_URL_NUVEM and "COLE_AQUI" not in DATABASE_URL_NUVEM:
        url = DATABASE_URL_NUVEM.replace("postgres://", "postgresql://")
        import psycopg2
        return psycopg2.connect(url)
    else:
        conexao = sqlite3.connect("banco_usuarios.db")
        conexao.row_factory = sqlite3.Row
        return conexao

def inicializar_banco():
    con = conectar_banco(); cursor = con.cursor()
    if hasattr(cursor, "execute"):
        try: cursor.execute("CREATE TABLE IF NOT EXISTS carteira (chat_id TEXT PRIMARY KEY, saldo REAL DEFAULT 0)")
        except Exception: pass
        try: cursor.execute("CREATE TABLE IF NOT EXISTS estoque (produto_id TEXT PRIMARY KEY, quantidade INTEGER DEFAULT 0)")
        except Exception: pass
        try: cursor.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id SERIAL PRIMARY KEY, produto_id TEXT, conteudo_esim TEXT)")
        except Exception:
            try: cursor.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id TEXT, conteudo_esim TEXT)")
            except Exception: pass
        try:
            cursor.execute("SELECT COUNT(*) FROM estoque")
            if cursor.fetchone() == 0:
                cursor.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('vivo_30gb', 0)")
                cursor.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('tim_40gb', 0)")
                cursor.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('claro_40gb', 0)")
        except Exception: pass
    con.commit(); con.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    saldo = 0.0  # 🔒 BLINDAGEM DE VARIÁVEL: Garante que o saldo nunca inicie vazio
    
    con = conectar_banco()
    cursor = con.cursor()
    try:
        if "psycopg2" in str(type(con)):
            cursor.execute("SELECT saldo FROM carteira WHERE chat_id = %s", (chat_id,))
        else:
            cursor.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res = cursor.fetchone()
        if res:
            saldo = float(next(iter(res)))
        else:
            if "psycopg2" in str(type(con)):
                cursor.execute("INSERT INTO carteira (chat_id, saldo) VALUES (%s, 0.0)", (chat_id,))
            else:
                cursor.execute("INSERT INTO carteira (chat_id, saldo) VALUES (?, 0.0)", (chat_id,))
            con.commit()
    except Exception as e:
        logging.error(f"Erro banco start: {e}")
    finally:
        try:
            cursor.execute("SELECT produto_id, quantidade FROM estoque")
            est_res = cursor.fetchall()
            est = {row[0]: row[1] for row in est_res} if "psycopg2" in str(type(con)) else {row["produto_id"]: row["quantidade"] for row in est_res}
        except Exception:
            est = {}
        con.close()

    texto = f"Olá, {user.first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    botoes = [
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")],
        [InlineKeyboardButton("➕ Adicionar Saldo (Pix)", callback_data="solicitar_recarga")]
    ]
    banner_url = "https://unsplash.com"
    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, reply_markup=InlineKeyboardMarkup(botoes))

async def processar_compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); chat_id = str(query.message.chat_id); produto_id = query.data.replace("buy_", "")
    precos = {"vivo_30gb": 25.0, "tim_40gb": 30.0, "claro_40gb": 35.0}; preco_item = precos.get(produto_id, 999.0)
    con = conectar_banco(); cursor = con.cursor()
    try:
        cursor.execute("SELECT saldo FROM carteira WHERE chat_id = %s", (chat_id,)) if "psycopg2" in str(type(con)) else cursor.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cursor.fetchone(); saldo = float(res_saldo) if res_saldo else 0.0
    except Exception: saldo = 0.0
    if saldo < preco_item:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ **Saldo Insuficiente!** Use o comando /pix valor para recarregar sua carteira.")
        con.close(); return
    try:
        cursor.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = %s LIMIT 1", (produto_id,)) if "psycopg2" in str(type(con)) else cursor.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (produto_id,))
        chip = cursor.fetchone()
    except Exception: chip = None
    if not chip:
        await context.bot.send_message(chat_id=chat_id, text="❌ **Estoque esgotado** para este plano! Tente novamente mais tarde.")
        con.close(); return
    chip_id, caminho_foto = chip, chip
    try:
        if "psycopg2" in str(type(con)):
            cursor.execute("UPDATE carteira SET saldo = saldo - %s WHERE chat_id = %s", (preco_item, chat_id))
            cursor.execute("DELETE FROM estoque_codigos WHERE id = %s", (chip_id,))
            cursor.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = %s", (produto_id,))
        else:
            cursor.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, chat_id))
            cursor.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
            cursor.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (produto_id,))
        con.commit()
    except Exception: pass
    con.close()
    try:
        with open(caminhi_foto, "rb") as f: await context.bot.send_photo(chat_id=chat_id, photo=f, caption=f"🎉 **COMPRA REALIZADA!**\n\nAqui está o QR Code do seu e-SIM ({produto_id.upper()}). Basta escanear para ativar!")
    except Exception: await context.bot.send_message(chat_id=chat_id, text="🎉 **COMPRA REALIZADA!**\n\nErro ao carregar a foto do chip, solicite suporte.")
async def generar_fluxo_pix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import requests
    message = update.message; chat_id = update.effective_chat.id; user = update.effective_user
    
    if not context.args:
        msg_ajuda = "➕ **COMO ADICIONAR SALDO:**\n\nPara gerar um QR Code Pix, digite o comando `/pix` seguido do valor desejado.\n\n👉 **Exemplo:** `/pix 25` (Adiciona R\$ 25,00)\n\n⚠️ *O valor mínimo aceito para recargas é de R\$ 10,00.*"
        if update.callback_query: 
            await update.callback_query.answer()
            await context.bot.send_message(chat_id=chat_id, text=msg_ajuda, parse_mode="Markdown")
        else: 
            await message.reply_text(msg_ajuda, parse_mode="Markdown")
        return
        
    try:
        texto_valor = "".join(context.args).replace(",", ".")
        valor_digitado = float(texto_valor)
        if valor_digitado < 10.0:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ *O valor mínimo para gerar o Pix é de R\$ 10,00.*", parse_mode="Markdown")
            return
        valor_centavos = int(valor_digitado * 100)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="❌ *Valor inválido! Digite apenas números. Exemplo: `/pix 15`*", parse_mode="Markdown")
        return

    url_api = "https://api.pushinpay.com.br/api/pix/cashIn"
    headers = {"Authorization": f"Bearer {PUSHINPAY_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}
    dados = {"value": valor_centavos, "webhook_url": "https://onrender.com", "external_id": str(chat_id), "split_rules": [], "customer": {"name": f"{user.first_name} {user.last_name or ''}".strip() or "Cliente Pix", "email": "cliente_esim@gmail.com", "document": "03620633037"}}
    
    try:
        resposta = requests.post(url_api, json=dados, headers=headers, timeout=15)
                if resposta.status_code == 200 or resposta.status_code == 201:
            res_j = resposta.json(); copia_e_cola = res_j.get("qr_code"); google_chart_link = f"https://googleapis.com{urllib.parse.quote(copia_e_cola)}"
            msg = f"📥 **PIX DE R\$ {valor_digitado:.2f} GERADO COM SUCESSO!**\n\n1️⃣ Abra o aplicativo do seu banco e escaneie o **QR Code acima**.\n\n2️⃣ **PIX COPIA E COLA:**\n`{copia_e_cola}`\n\n💡 *O saldo entrará automaticamente na sua carteira assim que o banco confirmar o pagamento!*"
            try: await context.bot.send_photo(chat_id=chat_id, photo=google_chart_link, caption=msg, parse_mode="Markdown")
            except Exception: await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        else: 
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Erro de Resposta PushinPay (Status {resposta.status_code}):\n`{resposta.text}`")
    except Exception as e: 
        logging.error(f"Erro Pix: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Falha de Conexão Crítica: {str(e)}")

async def clique_botao_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); chat_id = query.message.chat_id
    msg_ajuda = "➕ **COMO ADICIONAR SALDO:**\n\nPara gerar um QR Code Pix, use o teclado do celular e digite o comando `/pix` seguido do valor desejado.\n\n👉 **Exemplo:**\n`/pix 10` (Adiciona R\$ 10,00)\n`/pix 25` (Adiciona R\$ 25,00)\n\n⚠️ *O valor mínimo aceito para recargas é de R\$ 10,00.*"
    await context.bot.send_message(chat_id=chat_id, text=msg_ajuda, parse_mode="Markdown")

api_app = FastAPI()
api_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class LoginAdmin(BaseModel): senha: str

@api_app.post("/api/admin/login")
def api_admin_login(dados: LoginAdmin):
    if dados.senha == SENHA_ADMIN_MINISITE: return {"status": "sucesso", "token": "sessao_admin_valida_yure"}
    raise HTTPException(status_code=401, detail="Senha incorreta")

@api_app.post("/api/admin/cadastrar-chip")
async def api_cadastrar_chip(produto_id: str = Form(...), arquivo: UploadFile = File(...)):
    try:
        caminho = os.path.join(PASTA_IMAGENS, f"{produto_id}_{urllib.parse.quote(arquivo.filename)}")
        with open(caminho, "wb") as b: shutil.copyfileobj(arquivo.file, b)
        con = conectar_banco(); cursor = con.cursor()
        if "psycopg2" in str(type(con)):
            cursor.execute("INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (%s, %s)", (produto_id, caminho))
            cursor.execute("UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = %s", (produto_id,))
        else:
            cursor.execute("INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (?, ?)", (produto_id, caminho))
            cursor.execute("UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = ?", (produto_id,))
        con.commit(); con.close(); return {"status": "sucesso"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

def main() -> None:
    try: inicializar_banco()
    except Exception: pass
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(processar_compra, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(clique_botao_recarga, pattern="solicitar_recarga"))
    app.add_handler(CommandHandler("pix", generar_fluxo_pix))
    print("\n🤖 [STATUS] Servidor unificado pronto e estável!")
    import threading, uvicorn
    threading.Thread(target=lambda: uvicorn.run(api_app, host="0.0.0.0", port=10000), daemon=True).start()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
