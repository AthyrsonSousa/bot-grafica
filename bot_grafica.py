import logging
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler
from flask import Flask
from threading import Thread

# --- Configuração do Web Server (Para manter o Render acordado) ---
app = Flask('')

@app.route('/')
def home():
    return "Estou vivo! O Bot está rodando."

def run():
    # Pega a porta que o Render definir ou usa 8080
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

def conectar_gsheets():
    # AQUI ESTÁ O TRUQUE: Pegamos as credenciais da variável de ambiente, não de um arquivo
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if not creds_json:
        raise ValueError("A variável GOOGLE_CREDENTIALS não foi encontrada!")

    creds_dict = json.loads(creds_json)
    
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Substitua pelo nome da sua planilha
    sheet = client.open("Controle Grafica").sheet1 
    return sheet

def calcular_prazo_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_adicionados += 1
    return data_atual

def salvar_no_google(dados):
    try:
        sheet = conectar_gsheets()
        nova_linha = [
            dados['Nome'],
            dados['Quantidade'],
            dados['Material'],
            dados['Data Pedido'],
            dados['Data Entrega']
        ]
        sheet.append_row(nova_linha)
        return "Sucesso"  # Retorna texto de sucesso
    except Exception as e:
        print(f"Erro detalhado: {e}")
        return f"ERRO: {str(e)}"  # Retorna o texto do erro real

# --- Fluxo do Bot (Igual ao anterior) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Olá! Bot da Gráfica online. Qual o **Nome do Cliente**?")
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
        data_pedido = datetime.strptime(update.message.text, "%d/%m/%Y")
        data_entrega = calcular_prazo_uteis(data_pedido, 7)
        
        dados = {
            'Nome': context.user_data['nome'],
            'Quantidade': context.user_data['quantidade'],
            'Material': context.user_data['material'],
            'Data Pedido': data_pedido.strftime("%d/%m/%Y"),
            'Data Entrega': data_entrega.strftime("%d/%m/%Y")
        }
        
        await update.message.reply_text("⏳ Tentando salvar no Google Sheets...")
        
        # Chama a função e guarda o resultado (que pode ser Sucesso ou Erro)
        resultado = salvar_no_google(dados)
        
        if resultado == "Sucesso":
            await update.message.reply_text(f"✅ Salvo com sucesso!\nEntrega: {dados['Data Entrega']}")
        else:
            # AQUI ESTÁ O SEGREDO: Ele vai te mostrar o erro técnico
            await update.message.reply_text(f"❌ Ocorreu um erro técnico:\n\n`{resultado}`", parse_mode="Markdown")
            
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Data inválida. Use DD/MM/AAAA.")
        return DATA_PEDIDO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

if __name__ == '__main__':
    # Inicia o servidor web falso
    keep_alive()
    
    # Pega o Token da variável de ambiente
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    
    # --- ÁREA DE DEBUG (O ESPIÃO) ---
    print("--- INICIANDO DEBUG DO TOKEN ---")
    if TOKEN is None:
        print("ERRO CRÍTICO: A variável TELEGRAM_TOKEN não existe ou está vazia!")
    else:
        print(f"DEBUG: O Token foi lido com sucesso.")
        print(f"DEBUG: Tamanho do Token: {len(TOKEN)} caracteres")
        # Mostra o primeiro e ultimo caractere para vermos se tem aspas ou espaços
        print(f"DEBUG: O Token começa com: '{TOKEN[:2]}'") 
        print(f"DEBUG: O Token termina com: '{TOKEN[-2:]}'")
        
        # Verifica se tem espaços em branco
        if " " in TOKEN:
             print("ERRO CRÍTICO: O Token contém espaços em branco! Remova-os no Render.")
    print("--- FIM DO DEBUG ---")
    # -------------------------------

    # Se o token for inválido, o código vai quebrar na linha abaixo
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
    application.run_polling()

