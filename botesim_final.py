import os
import json
import logging
import sqlite3
import requests
import threading
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# 🔒 CREDENCIAIS E CONSTANTES DE PRODUÇÃO
TOKEN = "8826676433:AAEjicVbEpow_dbalsja15hFYCghRwAq0D0"
PUSHINPAY_TOKEN = "71078|M1MASBFV155gtnKBttSvkE6u8bD8kSBFjAMLwOXa70ca5a25"

# 🛡️ CREDENCIAIS DE SEGURANÇA DO PAINEL ADMIN
USUARIO_ADMIN_MINISITE = "yure_admin"  # <-- COLOQUE ESTA LINHA AQUI
SENHA_ADMIN_MINISITE = "yure123"

PASTA_IMAGENS = "imagens_chips"

if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)

# 🚀 INICIALIZAÇÃO DO FASTAPI E CORS
app = FastAPI(title="eSIM Bot & Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🏦 BANCO DE DADOS
def conectar_banco():
    con = sqlite3.connect("banco_usuarios.db")
    con.row_factory = sqlite3.Row
    return con

# 1. ATUALIZAÇÃO DO BANCO PARA REGISTRAR ACESSOS E NORMES
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
        
        cur.execute("SELECT COUNT(*) FROM estoque")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO estoque (produto_id, quantidade) VALUES ('vivo_30gb', 0), ('tim_40gb', 0), ('claro_40gb', 0)")
        con.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco: {e}")
    finally:
        con.close()

# 2. CAPTURA DE QUEM DEU /START (COM NOME E USERNAME)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    first_name = user.first_name or "Usuário"
    username = user.username or "sem_username"

    con = conectar_banco()
    cur = con.cursor()
    try:
        # Cadastra/atualiza o usuário no banco de dados para registrar no Admin
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
        logging.error(f"Erro no banco /start: {e}")
        saldo = 0.0
        est = {}
    finally:
        con.close()

    # 🔗 URL DO SEU MINIAPP NO GITHUB PAGES
    url_miniapp = "https://thallisimports-maker.github.io/bot-esim-yure/"
    
    # 🖼️ LINK DIRETO DO SEU BANNER
    # Substitua este link abaixo pela URL da imagem do seu banner oficial:
    banner_url = "https://chatgpt.com/s/m_6aab5a7bf33c81919a3625a128148666" 

    texto = f"Olá, {first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    
    # 📱 BOTÕES FIXADOS LOGO ABAIXO DA FOTO DO BANNER
    botoes = [
        [InlineKeyboardButton("📱 ABRIR LOJA / CARTEIRA (MINIAPP)", web_app=WebAppInfo(url=url_miniapp))],
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")]
    ]
    
    # Envia a foto com a legenda e os botões acoplados
    await context.bot.send_photo(
        chat_id=chat_id, 
        photo=banner_url, 
        caption=texto, 
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes)
    )

    url_miniapp = "https://thallisimports-maker.github.io/bot-esim-yure/"
    texto = f"Olá, {first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    
    botoes = [
        [InlineKeyboardButton("📱 ABRIR LOJA / CARTEIRA (MINIAPP)", web_app=WebAppInfo(url=url_miniapp))],
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")]
    ]
    
    banner_url = "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"
    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, reply_markup=InlineKeyboardMarkup(botoes))

# 3. ROTA DE MÉTRICAS PARA O PAINEL ADMIN
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

# 4. REGISTRAR ACESSO AO MINIAPP
@app.post("/api/miniapp/registrar-acesso")
async def registrar_acesso(payload: CompraMiniAppPayload):
    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute("INSERT INTO acessos_miniapp (chat_id) VALUES (?)", (payload.chat_id,))
        con.commit()
        return {"status": "ok"}
    finally:
        con.close()

# 🌐 SCHEMAS DO FASTAPI
class PixSitePayload(BaseModel):
    valor: float = Field(..., gte=10.0, description="Valor do Pix em Reais (Mínimo R$ 10,00)")

class CompraMiniAppPayload(BaseModel):
    chat_id: str
    produto_id: str

class AdminAuthAddEsimPayload(BaseModel):
    usuario_admin: str
    senha_admin: str
    produto_id: str
    conteudo_esim: str
    texto_instrucoes: Optional[str] = "Escaneie o QR Code para ativar o seu e-SIM."

# 🌐 ROTAS DA API WEB (MINIAPP & ADMIN)

@app.post("/api/admin/gerar-pix-site")
async def api_gerar_pix_site(payload: PixSitePayload):
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
        "external_id": "venda_site_web"
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

@app.get("/api/usuario/{chat_id}")
async def obter_dados_usuario(chat_id: str):
    con = conectar_banco()
    cur = con.cursor()
    try:
        # Registra o usuário se for a primeira vez que ele abre no site
        cur.execute("INSERT OR IGNORE INTO carteira (chat_id, saldo) VALUES (?, 0.0)", (chat_id,))
        con.commit()

        # Busca Saldo Real
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0

        # Busca e-SIMs / Compras do usuário
        cur.execute("SELECT produto_id, conteudo_esim FROM estoque_codigos LIMIT 10")
        esims = [dict(row) for row in cur.fetchall()]

        return {
            "status": "sucesso",
            "chat_id": chat_id,
            "saldo": saldo,
            "esims": esims
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()

@app.post("/api/comprar-esim")
async def comprar_esim_miniapp(payload: CompraMiniAppPayload):
    precos = {"vivo_30gb": 25.0, "tim_40gb": 30.0, "claro_40gb": 35.0}
    preco_item = precos.get(payload.produto_id, 999.0)

    con = conectar_banco()
    cur = con.cursor()
    try:
        # 1. Verifica Saldo do Cliente
        cur.execute("SELECT saldo FROM carteira WHERE chat_id = ?", (payload.chat_id,))
        res_saldo = cur.fetchone()
        saldo = float(res_saldo["saldo"]) if res_saldo else 0.0

        if saldo < preco_item:
            return {"status": "erro", "detalhe": "Saldo insuficiente na carteira!"}

        # 2. Busca o e-SIM no Estoque
        cur.execute("SELECT id, conteudo_esim FROM estoque_codigos WHERE produto_id = ? LIMIT 1", (payload.produto_id,))
        chip = cur.fetchone()
        if not chip:
            return {"status": "erro", "detalhe": "Estoque esgotado para este produto!"}

        chip_id, conteudo_bruto = chip["id"], chip["conteudo_esim"]

        # 3. Desconta o Saldo e Remove do Estoque
        cur.execute("UPDATE carteira SET saldo = saldo - ? WHERE chat_id = ?", (preco_item, payload.chat_id))
        cur.execute("DELETE FROM estoque_codigos WHERE id = ?", (chip_id,))
        cur.execute("UPDATE estoque SET quantidade = quantidade - 1 WHERE produto_id = ?", (payload.produto_id,))
        con.commit()

        # Separa o link da Imagem do QR Code e o Texto de Instruções
        partes = conteudo_bruto.split('||')
        qr_code_url = partes[0]
        instrucoes = partes[1] if len(partes) > 1 else "Escaneie o QR Code abaixo para ativar o seu e-SIM."

        # 4. DISPARA O QR CODE DIRETO NO CHAT DO TELEGRAM DO CLIENTE
        try:
            url_telegram_photo = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            payload_photo = {
                "chat_id": payload.chat_id,
                "photo": qr_code_url,
                "caption": f"🎉 **COMPRA REALIZADA COM SUCESSO!**\n\n{instrucoes}\n\n📱 **Plano:** {payload.produto_id.upper()}",
                "parse_mode": "Markdown"
            }
            requests.post(url_telegram_photo, data=payload_photo, timeout=10)
        except Exception as err_tg:
            logging.error(f"Erro ao enviar foto no chat do Telegram: {err_tg}")

        # 5. RETORNA PARA EXIBIR TAMBÉM NA TELA DO MINIAPP
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

@app.post("/api/admin/adicionar-estoque")
async def admin_adicionar_estoque(payload: AdminAuthAddEsimPayload):
    # BLINDAGEM DE SEGURANÇA: Valida Usuário E Senha no Servidor
    if payload.usuario_admin != USUARIO_ADMIN_MINISITE or payload.senha_admin != SENHA_ADMIN_MINISITE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Acesso Negado: Credenciais Administrativas Inválidas!"
        )

    conteudo_final = f"{payload.conteudo_esim}||{payload.texto_instrucoes}"

    con = conectar_banco()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO estoque_codigos (produto_id, conteudo_esim) VALUES (?, ?)",
            (payload.produto_id, conteudo_final)
        )
        cur.execute(
            "UPDATE estoque SET quantidade = quantidade + 1 WHERE produto_id = ?",
            (payload.produto_id,)
        )
        con.commit()
        return {
            "status": "sucesso", 
            "mensagem": f"e-SIM adicionado com sucesso ao estoque de {payload.produto_id.upper()}!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()

# 🤖 HANDLERS DO BOT DO TELEGRAM
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
        saldo = 0.0
        est = {}
    finally:
        con.close()

    url_miniapp = "https://thallisimports-maker.github.io/bot-esim-yure/"
    banner_url = "https://chatgpt.com/s/m_6aab5a7bf33c81919a3625a128148666"  # Substitui pelo teu link de banner

    texto = f"Olá, {first_name}!\n\n📥 **Carteira Saldo Virtual:** R$ {saldo:.2f}\n\nEscolha o seu plano de e-SIM abaixo para comprar instantaneamente:"
    
    botoes = [
        [InlineKeyboardButton("📱 ABRIR LOJA / CARTEIRA (MINIAPP)", web_app=WebAppInfo(url=url_miniapp))],
        [InlineKeyboardButton(f"Vivo 30GB - R$ 25 ({est.get('vivo_30gb', 0)} un)", callback_data="buy_vivo_30gb")],
        [InlineKeyboardButton(f"Tim 40GB - R$ 30 ({est.get('tim_40gb', 0)} un)", callback_data="buy_tim_40gb")],
        [InlineKeyboardButton(f"Claro 40GB - R$ 35 ({est.get('claro_40gb', 0)} un)", callback_data="buy_claro_40gb")]
    ]
    
    await context.bot.send_photo(chat_id=chat_id, photo=banner_url, caption=texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

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
    
    thread_api = threading.Thread(target=rodar_fastapi, daemon=True)
    thread_api.start()

    telegram_app = Application.builder().token(TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(processar_compra, pattern="^buy_"))
    telegram_app.add_handler(CommandHandler("pix", generar_fluxo_pix))
    
    print("\n🤖 [STATUS] Servidor unificado FastAPI + Telegram rodando perfeitamente!")
    
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
