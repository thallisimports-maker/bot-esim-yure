import os, json, logging, urllib.parse, shutil, sqlite3, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = "8826676433:AAG1hzAzX1dult6yvV2hBGuD5JIiqlpWwbo"
PUSHINPAY_TOKEN = "71037|z3q7oDUiZHaGhooOUPiRXJct31dt2nXkAjqJ0efzdb7ec317"
SENHA_ADMIN_MINISITE = "yure123"
DATABASE_URL_NUVEM = "COLE_AQUI"
PASTA_IMAGENS = "imagens_chips"

if not os.path.exists(PASTA_IMAGENS): os.makedirs(PASTA_IMAGENS)

def conectar_banco():
    con = sqlite3.connect("banco_usuarios.db"); con.row_factory = sqlite3.Row; return con

def inicializar_banco():
    con = conectar_banco(); cur = con.cursor()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS carteira (chat_id TEXT PRIMARY KEY, saldo REAL DEFAULT 0.0)")
        cur.execute("CREATE TABLE IF NOT EXISTS estoque (produto_id TEXT PRIMARY KEY, quantidade INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id TEXT, conteudo_esim TEXT)")
        cur.execute("SELECT COUNT(*) FROM estoque")
        if cur.fetchone() == 0:
            cur.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('vivo_30gb', 0), ('tim_40gb', 0), ('claro_40gb', 0)")
        con.commit()
    except Exception: pass
    finally: con.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id); user = update.effective_user; saldo = 0.0; con = conectar_banco(); cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res = cur.fetchone()
        if res: saldo = float(res["saldo"])
        else: cur.execute("INSERT INTO carteira (chat_id, saldo) VALUES (?, 0.0)", (chat_id,)); con.commit()
        cur.execute("SELECT produto_id, quantidade FROM estoque")
        est = {row["produto_id"]: row["whitespace_fix"] if (row := row) else 0 for row in cur.fetchall()} if hasattr(cur, "fetchall") else {row["produto_id"]: row["quantidade"] for row in cur.fetchall()}
    except Exception: est = {}
    finally: con.close()
    texto = f"Olá, {user.first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    botoes = [
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")],
        [InlineKeyboardButton("➕ Adicionar Saldo (Pix)", callback_data="solicitar_recarga")]
    ]
    banner_url = "https://freepik.com"
    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, reply_markup=InlineKeyboardMarkup(botoes))
    async def processar_compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); chat_id = str(query.message.chat_id); produto_id = query.data.replace("buy_", "")
    precos = {"vivo_30gb": 25.0, "tim_40gb": 30.0, "claro_40gb": 35.0}; preco_item = precos.get(produto_id, 999.0); con = conectar_banco(); cur = con.cursor()
    try:
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cur.fetchone(); saldo = float(res_saldo["saldo"]) if res_saldo else 0.0
        if saldo < preco_item: await context.bot.send_message(chat_id=chat_id, text="⚠️ **Saldo Insuficiente!** Use o comando /pix valor para recarregar."); con.close(); return
        cur.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (produto_id,))
        chip = cur.fetchone()
        if not chip: await context.bot.send_message(chat_id=chat_id, text="❌ **Estoque esgotado!** Tente novamente mais tarde."); con.close(); return
        chip_id, caminho_foto = chip["id"], chip["conteudo_esim"]
        cur.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, chat_id))
        cur.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
        cur.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (produto_id,))
        con.commit()
        with open(caminho_foto, "rb") as f: await context.bot.send_photo(chat_id=chat_id, photo=f, caption=f"🎉 **COMPRA REALIZADA!**\n\(\ne-\)SIM ({produto_id.upper()}) ativo!")
    except Exception: await context.bot.send_message(chat_id=chat_id, text="🎉 **COMPRA REALIZADA!**\n\nErro ao carregar a foto do chip, solicite suporte.")
    finally: con.close()

async def generar_fluxo_pix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import requests, qrcode
    message = update.message; chat_id = update.effective_chat.id; user = update.effective_user
    if not context.args:
        msg_ajuda = "➕ **COMO ADICIONAR SALDO:**\n\nPara gerar um QR Code Pix, digite `/pix` seguido do valor desejado.\n\n👉 **Exemplo:** `/pix 25` (Adiciona R\$ 25,00)\n\n⚠️ *Mínimo: R\$ 10,00.*"
        if update.callback_query: await update.callback_query.answer(); await context.bot.send_message(chat_id=chat_id, text=msg_ajuda, parse_mode="Markdown")
        else: await message.reply_text(msg_ajuda, parse_mode="Markdown")
        return
    try:
        valor_digitado = float("".join(context.args).replace(",", "."))
        if valor_digitado < 10.0: await context.bot.send_message(chat_id=chat_id, text="⚠️ *O valor mínimo para gerar o Pix é de R\$ 10,00.*", parse_mode="Markdown"); return
        valor_centavos = int(valor_digitado * 100)
    except Exception: await context.bot.send_message(chat_id=chat_id, text="❌ *Valor inválido! Exemplo: `/pix 15`*", parse_mode="Markdown"); return
    url_api = "https://pushinpay.com.br"
    headers = {"Authorization": f"Bearer {PUSHINPAY_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}
    dados = {"value": valor_centavos, "webhook_url": "https://onrender.com", "external_id": str(chat_id), "split_rules": [], "customer": {"name": f"{user.first_name} {user.last_name or ''}".strip() or "Cliente Pix", "email": "cliente_esim@gmail.com", "document": "03620633037"}}
    try:
        resposta = requests.post(url_api, json=dados, headers=headers, timeout=15)
        if resposta.status_code == 200 or resposta.status_code == 201:
            res_j = resposta.json(); copia_e_cola = res_j.get("qr_code"); qr_arquivo = f"pix_{chat_id}.png"
            qr = qrcode.QRCode(version=1, box_size=10, border=4); qr.add_data(copia_e_cola); qr.make(fit=True)
            qr.make_image(fill_color="black", back_color="white").save(qr_arquivo)
            msg = f"📥 **PIX DE R\$ {valor_digitado:.2f} GERADO COM SUCESSO!**\n\n1️⃣ Abra o app do seu banco e escaneie o **QR Code acima**.\n\n2️⃣ **PIX COPIA E COLA:**\n`{copia_e_cola}`\n\n💡 *O saldo entrará automaticamente após o pagamento!*"
            try:
                with open(qr_arquivo, "rb") as f: await context.bot.send_photo(chat_id=chat_id, photo=f, caption=msg, parse_mode="Markdown")
            except Exception: await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            finally:
                if os.path.exists(qr_arquivo): os.remove(qr_arquivo)
        else: await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Erro de Resposta PushinPay (Status {resposta.status_code})")
    except Exception: await context.bot.send_message(chat_id=chat_id, text="⚠️ Erro de conexão com o gateway.")

async def clique_botao_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); chat_id = query.message.chat_id
    msg_ajuda = "➕ **COMO ADICIONAR SALDO:**\n\nDigite o comando `/pix` seguido do valor desejado.\n\n👉 **Exemplo:**\n`/pix 10` (Adiciona R\$ 10,00)\n`/pix 25` (Adiciona R\$ 25,00)"
    await context.bot.send_message(chat_id=chat_id, text=msg_ajuda, parse_mode="Markdown")

api_app = FastAPI()
api_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
api_app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")

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
        con = conectar_banco(); cur = con.cursor()
        cur.execute("INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (?, ?)", (produto_id, caminho))
        cur.execute("UPDATE estoque SET quantidade = quantity + 1 WHERE produto_id = ?", (produto_id,)) if hasattr(cur, "execute") else cur.execute("UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = ?", (produto_id,))
        con.commit(); return {"status": "sucesso"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally: con.close()

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

if __name__ == "__main__": main()
