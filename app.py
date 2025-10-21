from flask import Flask, request
import asyncio
import nest_asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import os
import json

nest_asyncio.apply()

app = Flask(__name__)

from config import TELEGRAM_TOKEN
import database as db
from bot import (
    start, button_handler, handle_message, callback_handler, 
    admin_command, show_admin_panel
)

# Создаём приложение бота
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Асинхронный цикл
loop = asyncio.get_event_loop()

# Инициализация базы и бота
loop.run_until_complete(db.init_db())
loop.run_until_complete(application.initialize())

# Регистрируем хэндлеры
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_command))
application.add_handler(
    MessageHandler(
        filters.Regex(
            '^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'
        ),
        button_handler
    )
)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(callback_handler))

# Главная страница
@app.route('/')
def index():
    return 'MaxSaver Bot is running!', 200

# Вебхук для Telegram
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, application.bot)
        loop.create_task(application.process_update(update))
        return 'OK', 200
    except Exception as e:
        print(f"Error processing update: {e}")
        return 'Error', 500

# Проверка "живости"
@app.route('/ping')
def ping():
    return {'status': 'ok', 'message': 'Bot is alive'}, 200

# Информация о вебхуке
@app.route('/webhook_info')
def webhook_info():
    import requests
    response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo")
    return response.json(), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
