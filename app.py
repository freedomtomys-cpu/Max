from flask import Flask, request
import asyncio
import nest_asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import sys
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

application = Application.builder().token(TELEGRAM_TOKEN).build()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(db.init_db())
loop.run_until_complete(application.initialize())

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_command))
application.add_handler(MessageHandler(filters.Regex('^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'), button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(callback_handler))

@app.route('/')
def index():
    return 'MaxSaver Bot is running on Scalingo!'

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    json_data = json.loads(json_str)
    update = Update.de_json(json_data, application.bot)
    asyncio.run(application.process_update(update))
    return 'OK'

@app.route('/ping')
def ping():
    return {'status': 'ok', 'message': 'Bot is alive'}, 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
