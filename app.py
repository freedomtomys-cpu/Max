from flask import Flask, request, jsonify
import asyncio
import nest_asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import os
import json
import threading

nest_asyncio.apply()

app = Flask(__name__)

from config import TELEGRAM_TOKEN
import database as db
from bot import start, button_handler, handle_message, callback_handler, admin_command, show_admin_panel

application = None
loop = None
init_complete = False

def run_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def initialize_bot():
    global application, init_complete
    await db.init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    await application.initialize()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(MessageHandler(filters.Regex(
        '^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'
    ), button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    await application.start()
    
    init_complete = True
    print("Bot initialized and started successfully!")

def init_app():
    global loop, application
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=run_async_loop, args=(loop,), daemon=True)
    thread.start()
    asyncio.run_coroutine_threadsafe(initialize_bot(), loop).result(timeout=30)

init_app()

@app.route('/')
def index():
    status = "initialized" if init_complete else "initializing"
    return f'MaxSaver Bot is running on Scalingo! Status: {status}'

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if not init_complete or not application or not loop:
        return jsonify({'status': 'bot not ready'}), 503
    
    json_str = request.get_data().decode('UTF-8')
    json_data = json.loads(json_str)
    update = Update.de_json(json_data, application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return 'OK'

@app.route('/ping')
def ping():
    return {'status': 'ok', 'message': 'Bot is alive', 'initialized': init_complete}, 200

@app.route('/setWebhook')
def set_webhook():
    webhook_url = request.args.get('url')
    if not webhook_url:
        return {'error': 'URL parameter required'}, 400
    
    try:
        import requests
        response = requests.get(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook',
            params={'url': f'{webhook_url}/{TELEGRAM_TOKEN}'}
        )
        return response.json()
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
