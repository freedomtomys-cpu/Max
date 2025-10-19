from flask import Flask, request
import asyncio
import nest_asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import os
import json

nest_asyncio.apply()

# Flask-приложение
app = Flask(__name__)

# Импорты бота
from config import TELEGRAM_TOKEN
import database as db
from bot import start, button_handler, handle_message, callback_handler, admin_command, show_admin_panel

# Создаём глобальный event loop
loop = asyncio.get_event_loop()

# Telegram Application
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Инициализация базы и бота в фоне, чтобы Flask стартовал мгновенно
async def init_bot():
    await db.init_db()
    await application.initialize()

loop.create_task(init_bot())

# Обработчики команд и сообщений
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_command))
application.add_handler(MessageHandler(filters.Regex(
    '^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'
), button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(callback_handler))

# Главная страница
@app.route('/')
def index():
    return 'MaxSaver Bot is running on Scalingo!'

# Webhook для Telegram
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    json_data = json.loads(json_str)
    update = Update.de_json(json_data, application.bot)
    loop.create_task(application.process_update(update))
    return 'OK'

# Проверка работы
@app.route('/ping')
def ping():
    return {'status': 'ok', 'message': 'Bot is alive'}, 200

# Локальный запуск для теста
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

