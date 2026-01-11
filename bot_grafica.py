import logging
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler
from flask import Flask
from threading import Thread
from supabase import create_client, Client # Nova biblioteca

# --- Configuração do Web Server (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Supabase Online!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Configurações do Bot ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

NOME, QUANTIDADE, MATERIAL, DATA_PEDIDO = range(4)

# --- Conexão Supabase ---
def conectar_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        raise ValueError("ERRO: As variáveis SUPABASE_URL e SUPABASE_KEY são obrigatórias.")
    
    return create_client(url, key)

# --- Lógica de Negócio ---
def calcular_prazo_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5: # 0=Segunda ... 4=Sexta
            dias_adicionados += 1
    return data_atual

def salvar_no_banco(dados):
    try:
        supabase = conectar_supabase()
        
        # Prepara o dicionário para enviar ao banco
        # As chaves aqui devem ser IGUAIS aos nomes das colunas no Supabase
        payload = {
            "cliente": dados['Nome'],
            "quantidade": dados['Quantidade'],
            "material": dados['Material'],
            "data_pedido": dados['Data Pedido'],
            "data_entrega": dados['Data Entrega']
        }
        
        # Insere na tabela 'pedidos'
        response = supabase.table("pedidos").insert(payload).execute()
        
        return "Sucesso"
    except Exception as e:
        print(f"Erro Supabase: {e}")
        return f"ERRO: {str(e)}"

# --- Fluxo de Conversa ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Olá! Bot da Gráfica (Supabase Edition).\n\nQual o **Nome do Cliente**?")
    return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nome'] = update.message.text
    await update.message.reply_text("Qual a **Quantidade**?")
    return QUANTIDADE

async def receber_quantidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['quantidade'] = update.message.text
    await update.message.reply_text("Qual o **Material**?")
    return MATERIAL

async def receber_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['material'] = update.message.text
    await update.message.reply_text("Data do Pedido (DD/MM/AAAA):")
    return DATA_PEDIDO

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto_data = update.message.text
        data_pedido = datetime.strptime(texto_data, "%d/%m/%Y")
        data_entrega = calcular_prazo_uteis(data_pedido, 7)
        
        # Organiza os dados
        dados_pedido = {
            'Nome': context.user_data['nome'],
            'Quantidade': context.user_data['quantidade'],
            'Material': context.user_data['material'],
            'Data Pedido': data_pedido.strftime("%d/%m/%Y"),
            'Data Entrega': data_entrega.strftime("%d/%m/%Y")
        }
        
        await update.message.reply_text("⏳ Salvando no banco de dados...")
        
        # Salva no Supabase
        resultado = salvar_no_banco(dados_pedido)
        
        if resultado == "Sucesso":
            await update.message.reply_text(
                f"✅ **Pedido Salvo!**\n\n"
                f"👤 Cliente: {dados_pedido['Nome']}\n"
                f"🚚 **Entrega: {dados_pedido['Data Entrega']}**"
            )
        else:
            await update.message.reply_text(f"❌ Erro ao salvar:\n`{resultado}`", parse_mode="Markdown")
            
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM/AAAA (ex: 12/05/2026).")
        return DATA_PEDIDO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operação cancelada.")
    return ConversationHandler.END

if __name__ == '__main__':
    keep_alive()
    
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    
    if not TOKEN:
        print("ERRO: Token não encontrado.")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                NOME: [MessageHandler(filters.TEXT, receber_nome)],
                QUANTIDADE: [MessageHandler(filters.TEXT, receber_quantidade)],
                MATERIAL: [MessageHandler(filters.TEXT, receber_material)],
                DATA_PEDIDO: [MessageHandler(filters.TEXT, receber_data)],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        application.add_handler(conv_handler)
        
        print("Bot Supabase rodando...")
        application.run_polling()
