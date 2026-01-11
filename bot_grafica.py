import logging
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler
from flask import Flask
from threading import Thread
from supabase import create_client, Client

# --- Web Server (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Grafica (Multi-itens) Online!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Configurações ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Estados da conversa
LOGIN, NOME, DATA_PEDIDO, MATERIAL, QUANTIDADE, DECISAO_MAIS_ITENS = range(6)

# --- Supabase ---
def conectar_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("Faltam variáveis do Supabase")
    return create_client(url, key)

# --- Segurança ---
def verificar_funcionario(user_id):
    try:
        supabase = conectar_supabase()
        response = supabase.table("funcionarios").select("*").eq("user_id", user_id).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Erro ao verificar funcionario: {e}")
        return False

def registrar_funcionario(user_id, username):
    try:
        supabase = conectar_supabase()
        supabase.table("funcionarios").insert({
            "user_id": user_id,
            "username": username
        }).execute()
        return True
    except Exception as e:
        print(f"Erro ao registrar: {e}")
        return False

# --- Lógica de Datas ---
def calcular_prazo_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5: # 0=Segunda ... 4=Sexta
            dias_adicionados += 1
    return data_atual

# --- Lógica de Salvamento em Lote ---
def salvar_carrinho_no_banco(context):
    try:
        supabase = conectar_supabase()
        dados_gerais = context.user_data
        carrinho = context.user_data['carrinho']
        
        lista_para_inserir = []
        
        # Prepara cada item do carrinho para ser uma linha no banco
        for item in carrinho:
            payload = {
                "cliente": dados_gerais['nome'],
                "data_pedido": dados_gerais['data_pedido'],
                "data_entrega": dados_gerais['data_entrega'],
                "usuario_telegram": dados_gerais['usuario_telegram'],
                "material": item['material'],
                "quantidade": item['quantidade']
            }
            lista_para_inserir.append(payload)
            
        # Insere todos de uma vez
        supabase.table("pedidos").insert(lista_para_inserir).execute()
        return "Sucesso"
    except Exception as e:
        return f"ERRO: {str(e)}"

# --- Fluxo do Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Limpa dados antigos
    context.user_data.clear()
    context.user_data['carrinho'] = []
    
    user = update.message.from_user
    
    if verificar_funcionario(user.id):
        await update.message.reply_text(
            f"👋 Olá, {user.first_name}!\n"
            "Vamos abrir um novo pedido (Multi-itens).\n\n"
            "Qual o **Nome do Cliente**?"
        )
        return NOME
    else:
        await update.message.reply_text(
            "🔒 **Acesso Restrito**\nDigite a senha de funcionário:"
        )
        return LOGIN

async def verificar_senha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    senha_digitada = update.message.text
    senha_correta = os.environ.get("SENHA_FUNCIONARIO")
    user = update.message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    if senha_digitada == senha_correta:
        registrar_funcionario(user.id, username)
        await update.message.reply_text("✅ Senha correta! Qual o **Nome do Cliente**?")
        return NOME
    else:
        await update.message.reply_text("❌ Senha incorreta. Tente novamente.")
        return LOGIN

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nome'] = update.message.text
    await update.message.reply_text("📅 Qual a **Data do Pedido** (DD/MM/AAAA)?")
    return DATA_PEDIDO

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto_data = update.message.text
        data_pedido = datetime.strptime(texto_data, "%d/%m/%Y")
        data_entrega = calcular_prazo_uteis(data_pedido, 7)
        
        user = update.message.from_user
        username = f"@{user.username}" if user.username else user.first_name
        
        # Salva os dados "fixos" do pedido
        context.user_data['data_pedido'] = data_pedido.strftime("%d/%m/%Y")
        context.user_data['data_entrega'] = data_entrega.strftime("%d/%m/%Y")
        context.user_data['usuario_telegram'] = username
        
        await update.message.reply_text(
            f"🗓️ Data registrada.\nEntrega prevista: {context.user_data['data_entrega']}\n\n"
            "Agora vamos aos itens.\n"
            "📦 **Digite o nome do 1º Material:**"
        )
        return MATERIAL
        
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use DD/MM/AAAA.")
        return DATA_PEDIDO

async def receber_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Guarda o material temporariamente
    context.user_data['temp_material'] = update.message.text
    await update.message.reply_text(f"🔢 Qual a **Quantidade** para '{update.message.text}'?")
    return QUANTIDADE

async def receber_quantidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qtd = update.message.text
    material = context.user_data['temp_material']
    
    # Adiciona ao carrinho
    context.user_data['carrinho'].append({
        'material': material,
        'quantidade': qtd
    })
    
    # Cria botões para Sim/Não
    teclado = [['SIM', 'NÃO']]
    reply_markup = ReplyKeyboardMarkup(teclado, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ Item adicionado: **{qtd}x {material}**\n\n"
        "➕ **Deseja adicionar mais algum material neste pedido?**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return DECISAO_MAIS_ITENS

async def decidir_mais_itens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resposta = update.message.text.upper()
    
    if resposta == 'SIM':
        await update.message.reply_text("📦 Digite o nome do **próximo Material**:", reply_markup=ReplyKeyboardRemove())
        return MATERIAL
    
    else:
        # Finalizar Pedido
        await update.message.reply_text("⏳ Finalizando e salvando pedido...", reply_markup=ReplyKeyboardRemove())
        
        resultado = salvar_carrinho_no_banco(context)
        
        carrinho = context.user_data['carrinho']
        resumo_itens = "\n".join([f"- {item['quantidade']}x {item['material']}" for item in carrinho])
        
        if resultado == "Sucesso":
            await update.message.reply_text(
                f"✅ **Pedido Salvo com Sucesso!**\n\n"
                f"👤 Cliente: {context.user_data['nome']}\n"
                f"🚚 Entrega: {context.user_data['data_entrega']}\n\n"
                f"🛒 **Itens:**\n{resumo_itens}\n\n"
                f"Digite /start para novo cliente."
            )
        else:
            await update.message.reply_text(f"❌ Erro ao salvar:\n{resultado}")
            
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operação cancelada.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

if __name__ == '__main__':
    keep_alive()
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    
    if TOKEN:
        application = ApplicationBuilder().token(TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, verificar_senha)],
                NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
                DATA_PEDIDO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data)],
                MATERIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_material)],
                QUANTIDADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_quantidade)],
                DECISAO_MAIS_ITENS: [MessageHandler(filters.Regex("^(SIM|sim|NÃO|não|NAO|nao)$"), decidir_mais_itens)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        application.add_handler(conv_handler)
        print("Bot Carrinho Rodando...")
        application.run_polling()
