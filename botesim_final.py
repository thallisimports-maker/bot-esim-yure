import os, sys, logging, sqlite3, urllib.parse, json, shutil
try:
    from fastapi import FastAPI, HTTPException, File, UploadFile, Form
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
except Exception as e:
    print(f"\n❌ ERRO: Faltam bibliotecas! {e}"); sys.exit(1)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = "8826676433:AAH04c0lZ7g_QVgfyTQS4Ro2N5oLzl_f3pA"
WEBAPP_URL = "https://github.io"
SEU_TELEGRAM_ID = 1890506390  
LINK_DO_BANNER = "https://unsplash.com" 
PUSHINPAY_TOKEN = "71008|0uzqn6ne0SG8EPMBU2pCkGPG1QlJ83SMj19bnNfy88fb3b8f"
DATABASE_URL_NUVEM = "COLE_AQUI_SEU_EXTERNAL_DATABASE_URL"
SENHA_ADMIN_MINISITE = "COLE_AQUI_SUA_SENHA_SECRETA"

PASTA_IMAGENS = "imagens_esim"
os.makedirs(PASTA_IMAGENS, exist_ok=True)

def conectar_banco():
    if DATABASE_URL_NUVEM and "COLE_AQUI" not in DATABASE_URL_NUVEM:
        return psycopg2.connect(DATABASE_URL_NUVEM.replace("postgres://", "postgresql://"))
    con = sqlite3.connect("banco_usuarios.db"); con.row_factory = sqlite3.Row; return con

def inicializar_banco():
    con = conectar_banco(); cursor = con.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (telegram_id BIGINT PRIMARY KEY, nome TEXT, saldo REAL DEFAULT 0.0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS estoque (produto_id TEXT PRIMARY KEY, nome_produto TEXT, preco REAL, quantidade INTEGER)")
    if "COLE_AQUI" in DATABASE_URL_NUVEM:
        cursor.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id TEXT, conteudo_esim TEXT)")
    else:
        cursor.execute("CREATE TABLE IF NOT EXISTS estoque_codigos (id SERIAL PRIMARY KEY, produto_id TEXT, conteudo_esim TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS historico_pedidos (id TEXT PRIMARY KEY, telegram_id BIGINT, produto_id TEXT, nome_produto TEXT, conteudo_esim TEXT, data_compra TEXT)")
    try:
        cursor.execute("SELECT COUNT(*) FROM estoque")
        if cursor.fetchone() == 0:
            cursor.execute("INSERT INTO estoque VALUES ('vivo_30gb', 'e-SIM Vivo 30GB', 25.0, 1)")
            cursor.execute("INSERT INTO estoque VALUES ('claro_35gb', 'e-SIM Claro 35GB', 30.0, 1)")
            cursor.execute("INSERT INTO estoque VALUES ('claro_40gb', 'e-SIM Claro 40GB', 35.0, 2)")
    except: pass
    con.commit(); con.close()

def obter_saldo_e_estoque(telegram_id, nome_user):
    con = conectar_banco(); cursor = con.cursor(); saldo = 0.0
    try:
        cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id = ?", (telegram_id,))
        res = cursor.fetchone()
        if res is None:
            cursor.execute("INSERT INTO usuarios (telegram_id, nome, saldo) VALUES (?, ?, ?)", (telegram_id, nome_user, 0.0)); con.commit()
        else: saldo = res if isinstance(res, tuple) else res['saldo']
    except: pass
    est = {}
    try:
        cursor.execute("SELECT produto_id, quantity FROM estoque")
        for r in cursor.fetchall(): est[r if isinstance(r, tuple) else r['produto_id']] = r if isinstance(r, tuple) else r['quantity']
    except: pass
    con.close(); return saldo, est
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user; saldo, est = obter_saldo_e_estoque(user.id, user.first_name)
    texto = f"Ola, {user.first_name}! \n\n do Carteira Saldo Virtual: **R\$ {saldo:.2f}**\n\n Escolha o seu plano de e-SIM abaixo."
    keyboard = [
        [InlineKeyboardButton(text=" Abrir Loja Virtual (Web App)", web_app=WebAppInfo(url=WEBAPP_URL))],
        [
            InlineKeyboardButton(text=f" Vivo 30GB - R\$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb"),
            InlineKeyboardButton(text=f" Claro 35GB - R\$ 30 ({est.get('claro_35gb', 0)} un)", callback_data="buy_claro_35gb")
        ],
        [InlineKeyboardButton(text=f" Claro 40GB - R\$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")],
        [InlineKeyboardButton(text=" Adicionar Saldo", callback_data="solicitar_recarga"), InlineKeyboardButton(text=" Suporte", url="https://t.me")]
    ]
    try: await update.message.reply_photo(photo=LINK_DO_BANNER, caption=texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except: await update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def processar_compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); user = query.from_user; prod_id = query.data.replace("buy_", "")
    con = conectar_banco(); cursor = con.cursor()
    cursor.execute("SELECT nome_produto, preco, quantidade FROM estoque WHERE produto_id = ?", (prod_id,))
    prod = cursor.fetchone()
    if not prod: con.close(); return
    n_prod, p_prod, q_prod = (prod, prod, prod) if isinstance(prod, tuple) else (prod['nome_produto'], prod['preco'], prod['quantidade'])
    cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id = ?", (user.id,))
    res_s = cursor.fetchone(); s_user = res_s if isinstance(res_s, tuple) else res_s['saldo']
    if q_prod <= 0: await query.message.reply_text(f"Desculpe, o estoque de **{n_prod}** esgotou!")
    elif s_user < p_prod: await query.message.reply_text(f"Saldo insuficiente para realizar a compra!")
    else:
        cursor.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (prod_id,))
        esim = cursor.fetchone()
        if esim:
            id_reg, link_img = (esim, esim) if isinstance(esim, tuple) else (esim['id'], esim['conteudo_esim'])
            cursor.execute("DELETE FROM estoque_codigos WHERE id = ?", (id_reg,))
            cursor.execute("UPDATE usuarios SET saldo = ? WHERE telegram_id = ?", (s_user - p_prod, user.id))
            cursor.execute("UPDATE estoque SET quantity = ? WHERE produto_id = ?", (q_prod - 1, prod_id))
            con.commit()
            man = "⚙️ **MINI-TUTORIAL:**\n1. Va em Configuracoes > Redes Moveis > Adicionar e-SIM.\n2. Use a imagem enviada para leitura."
            if prod_id.startswith("vivo"): man += "\n\n⚠️ **ATENCAO VIVO:** Chame o suporte para ativacao!"
            try:
                if os.path.exists(link_img):
                    with open(link_img, 'rb') as f: await query.message.reply_photo(photo=f, caption=f"🎉 **Compra realizada!**\n\n{man}", parse_mode="Markdown")
                else: await query.message.reply_photo(photo=link_img, caption=f"🎉 **Compra realizada!**\n\n{man}", parse_mode="Markdown")
            except: await query.message.reply_text(f"🎉 **Compra realizada!**\n\n🔗 Link: {link_img}\n\n{man}", parse_mode="Markdown")
            await context.bot.send_message(chat_id=SEU_TELEGRAM_ID, text=f"🤖 **VENDA:** {user.first_name} comprou {n_prod}")
        else: await query.message.reply_text("⚠️ Sem chips no estoque.")
    con.close()

async def generar_fluxo_pix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); chat_id = query.message.chat_id
    url_api = "https://api.pushinpay.com.br/api/pix/cashIn"
    headers = {"Authorization": f"Bearer {PUSHINPAY_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}
    dados = {"value": 2500, "webhook_url": "https://github.io", "external_id": str(chat_id), "split_rules": []}
    try:
        req = urllib.request.Request(url_api, data=json.dumps(dados).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req) as r:
            res_j = json.loads(r.read().decode("utf-8"))
            msg = f"📥 **DADOS PAIX:**\n\nCopia e Cola:\n`{res_j.get('qr_code')}`"
            await context.bot.send_photo(chat_id=chat_id, photo=res_j.get("qr_code_url"), caption=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Erro Pix: {e}")
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Erro temporário. Tente novamente.")


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
        con = conectar_banco(); cursor = con.cursor()
        cursor.execute("INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (?, ?)", (produto_id, caminho))
        cursor.execute("UPDATE estoque SET quantity = quantity + 1 WHERE produto_id = ?", (produto_id,))
        con.commit(); con.close(); return {"status": "sucesso"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

def main() -> None:
    inicializar_banco()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(processar_compra, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(generar_fluxo_pix, pattern="solicitar_recarga"))
    print("\n🤖 [STATUS] Servidor unificado pronto e estável!")
    import threading, uvicorn
    threading.Thread(target=lambda: uvicorn.run(api_app, host="0.0.0.0", port=8000), daemon=True).start()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__": main()
  
