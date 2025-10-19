from flask import Flask, request
import asyncio
import nest_asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import os
import json

nest_asyncio.apply()

# Инициализация Flask
app = Flask(__name__)

# Импорты твоего бота и конфигов
from config import TELEGRAM_TOKEN
import database as db
from bot import start, button_handler, handle_message, callback_handler, admin_command, show_admin_panel

# Создаем глобальный event loop для Scalingo
loop = asyncio.get_event_loop()

# Создаем Telegram Application, но без run_until_complete на старте
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Инициализация базы и бота в отдельной задаче, чтобы Flask стартовал сразу
async def init_bot():
    await db.init_db()
    await application.initialize()

# Запускаем инициализацию в фоне
loop.create_task(init_bot())

# Добавляем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_command))
application.add_handler(MessageHandler(filters.Regex(
    '^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'
), button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(callback_handler))

# Основной маршрут
@app.route('/')
def index():
    return 'MaxSaver Bot is running on Scalingo!'

# Webhook для Telegram
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    json_data = json.loads(json_str)
    update = Update.de_json(json_data, application.bot)
    # Используем глобальный loop вместо asyncio.run()
    loop.create_task(application.process_update(update))
    return 'OK'

# Доп. маршрут для проверки
@app.route('/ping')
def ping():
    return {'status': 'ok', 'message': 'Bot is alive'}, 200

# Точка входа для локального теста
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
