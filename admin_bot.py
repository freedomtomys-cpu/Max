import asyncio
import nest_asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import logging
from datetime import datetime, timedelta
import random
import string
import aiosqlite

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from config import ADMIN_BOT_TOKEN, ADMIN_BOT_PASSWORD_1, ADMIN_BOT_PASSWORD_2, ADMIN_BOT_ID
from database import get_all_user_ids

DATABASE_FILE = 'bot_database.db'
SESSION_TIMEOUT = 300

async def check_session(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT session_active, last_active FROM admin_sessions WHERE admin_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] != 1:
                return False
            
            last_active = datetime.fromisoformat(row[1])
            if (datetime.now() - last_active).total_seconds() > SESSION_TIMEOUT:
                await db.execute(
                    'UPDATE admin_sessions SET session_active = 0 WHERE admin_id = ?',
                    (user_id,)
                )
                await db.commit()
                return False
            
            await db.execute(
                'UPDATE admin_sessions SET last_active = ? WHERE admin_id = ?',
                (datetime.now().isoformat(), user_id)
                )
            await db.commit()
            return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id != ADMIN_BOT_ID:
        await update.message.reply_text("❌ У вас нет доступа к этому боту.")
        return
    
    keyboard = [['Бот']]
    from telegram import ReplyKeyboardMarkup
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 Добро пожаловать в админ-панель управления ботом!",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if user.id != ADMIN_BOT_ID:
        return
    
    if text == 'Бот':
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute('''
                INSERT OR REPLACE INTO admin_sessions (admin_id, session_active, auth_step, last_active)
                VALUES (?, 0, 0, ?)
            ''', (user.id, datetime.now().isoformat()))
            await db.commit()
        
        context.user_data['awaiting_password'] = 1
        await update.message.reply_text("🔐 Введите первый пароль:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id != ADMIN_BOT_ID:
        return
    
    text = update.message.text
    
    if context.user_data.get('awaiting_password') == 1:
        if text == ADMIN_BOT_PASSWORD_1:
            context.user_data['awaiting_password'] = 2
            await update.message.reply_text("✅ Первый пароль верен.\n🔐 Введите второй пароль:")
        else:
            await update.message.reply_text("❌ Неверный пароль. Попробуйте снова.")
        return
    
    elif context.user_data.get('awaiting_password') == 2:
        if text == ADMIN_BOT_PASSWORD_2:
            async with aiosqlite.connect(DATABASE_FILE) as db:
                await db.execute(
                    'UPDATE admin_sessions SET session_active = 1, last_active = ? WHERE admin_id = ?',
                    (datetime.now().isoformat(), user.id)
                )
                await db.commit()
            
            context.user_data.pop('awaiting_password', None)
            
            keyboard = [
                [InlineKeyboardButton("📢 Push-уведомления", callback_data="push_notification")],
                [InlineKeyboardButton("👥 Спонсоры", callback_data="sponsors")],
                [InlineKeyboardButton("🗑 Удалить push", callback_data="delete_push")],
                [InlineKeyboardButton("❌ Убрать спонсоров", callback_data="remove_sponsors")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ Авторизация успешна!\n\n"
                "⏰ *Тайм-аут сессии: 5 минут*\n\n"
                "Выберите действие:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            context.user_data.pop('awaiting_password', None)
            await update.message.reply_text("❌ Неверный пароль. Начните сначала с кнопки 'Бот'.")
        return
    
    if not await check_session(user.id):
        await update.message.reply_text(
            "⏰ Сессия истекла.\n\n"
            "Нажмите кнопку 'Бот' для повторной авторизации."
        )
        return
    
    if context.user_data.get('state') == 'awaiting_push_text':
        context.user_data['push_text'] = text
        context.user_data['state'] = 'awaiting_push_lifetime'
        await update.message.reply_text(
            "⏰ Введите время жизни сообщения:\n\n"
            "• `ever` — сообщение не удаляется\n"
            "• `24 часа`\n"
            "• `4 часа 6 минут 9 секунд`\n"
            "• `1 час 10 минут`\n\n"
            "Формат: часы, минуты, секунды",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif context.user_data.get('state') == 'awaiting_push_lifetime':
        push_text = context.user_data.get('push_text')
        
        if text.lower() == 'ever':
            lifetime = -1
        else:
            lifetime = parse_time_string(text)
            if lifetime is None:
                await update.message.reply_text("❌ Неверный формат времени. Попробуйте снова.")
                return
        
        push_id = generate_push_id()
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute('''
                INSERT INTO push_messages (id, text, lifetime, active)
                VALUES (?, ?, ?, 1)
            ''', (push_id, push_text, lifetime))
            await db.commit()
        
        await broadcast_message(push_text, push_id, lifetime, context.bot)
        
        context.user_data.pop('state', None)
        context.user_data.pop('push_text', None)
        
        await update.message.reply_text(
            f"✅ Push-уведомление опубликовано!\n\n"
            f"🆔 Уникальный код: `{push_id}`\n"
            f"📝 Текст: {push_text[:50]}{'...' if len(push_text) > 50 else ''}\n"
            f"⏰ Время жизни: {'Бессрочно' if lifetime == -1 else f'{lifetime} секунд'}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif context.user_data.get('state') == 'awaiting_sponsors_count':
        try:
            count = int(text)
            if count <= 0 or count > 10:
                await update.message.reply_text("❌ Количество должно быть от 1 до 10.")
                return
            
            context.user_data['sponsors_count'] = count
            context.user_data['sponsors_links'] = []
            context.user_data['current_sponsor'] = 1
            context.user_data['state'] = 'awaiting_sponsor_link'
            
            await update.message.reply_text(f"✅ Будет добавлено {count} спонсоров.\n\n📎 Отправьте ссылку для спонсора #1:")
        except ValueError:
            await update.message.reply_text("❌ Введите число.")
    
    elif context.user_data.get('state') == 'awaiting_sponsor_link':
        sponsors_count = context.user_data['sponsors_count']
        current = context.user_data['current_sponsor']
        
        if not text.startswith('http'):
            await update.message.reply_text("❌ Ссылка должна начинаться с http:// или https://")
            return
        
        context.user_data['sponsors_links'].append(text)
        
        if current < sponsors_count:
            context.user_data['current_sponsor'] += 1
            await update.message.reply_text(f"✅ Ссылка #{current} сохранена.\n\n📎 Отправьте ссылку для спонсора #{current + 1}:")
        else:
            async with aiosqlite.connect(DATABASE_FILE) as db:
                for idx, link in enumerate(context.user_data['sponsors_links'], 1):
                    await db.execute('''
                        INSERT INTO sponsors (link, position, active)
                        VALUES (?, ?, 1)
                    ''', (link, idx))
                await db.commit()
            
            context.user_data.pop('state', None)
            context.user_data.pop('sponsors_count', None)
            context.user_data.pop('sponsors_links', None)
            context.user_data.pop('current_sponsor', None)
            
            await update.message.reply_text(
                f"✅ Все {sponsors_count} спонсоров успешно добавлены!\n\n"
                "Они будут отображаться в основном боте."
            )
    
    elif context.user_data.get('state') == 'awaiting_push_delete_code':
        async with aiosqlite.connect(DATABASE_FILE) as db:
            async with db.execute('SELECT text FROM push_messages WHERE id = ? AND active = 1', (text,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    await db.execute('UPDATE push_messages SET active = 0 WHERE id = ?', (text,))
                    await db.commit()
                    
                    context.user_data.pop('state', None)
                    await update.message.reply_text(
                        f"✅ Push-уведомление `{text}` удалено!\n\n"
                        f"Текст был: {row[0][:50]}...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text(f"❌ Push с кодом `{text}` не найден.", parse_mode=ParseMode.MARKDOWN)
    
    elif context.user_data.get('state') == 'awaiting_sponsor_remove':
        if text.lower() == 'all':
            async with aiosqlite.connect(DATABASE_FILE) as db:
                async with db.execute('SELECT COUNT(*) FROM sponsors WHERE active = 1') as cursor:
                    row = await cursor.fetchone()
                    count = row[0] if row else 0
                
                await db.execute('UPDATE sponsors SET active = 0')
                await db.commit()
            
            context.user_data.pop('state', None)
            await update.message.reply_text(f"✅ Удалено {count} спонсоров.")
        
        elif text.lower() == 'one':
            context.user_data['state'] = 'awaiting_sponsor_number'
            await update.message.reply_text("🔢 Введите номер спонсора для удаления:")
        else:
            await update.message.reply_text("❌ Введите 'all' или 'one'.")
    
    elif context.user_data.get('state') == 'awaiting_sponsor_number':
        try:
            number = int(text)
            
            async with aiosqlite.connect(DATABASE_FILE) as db:
                async with db.execute(
                    'SELECT id FROM sponsors WHERE position = ? AND active = 1',
                    (number,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        await db.execute('UPDATE sponsors SET active = 0 WHERE id = ?', (row[0],))
                        
                        async with db.execute('SELECT id, position FROM sponsors WHERE active = 1 ORDER BY position') as cursor2:
                            rows = await cursor2.fetchall()
                            for idx, (sponsor_id, _) in enumerate(rows, 1):
                                await db.execute('UPDATE sponsors SET position = ? WHERE id = ?', (idx, sponsor_id))
                        
                        await db.commit()
                        
                        context.user_data.pop('state', None)
                        await update.message.reply_text(f"✅ Спонсор #{number} удален. Номера обновлены.")
                    else:
                        await update.message.reply_text(f"❌ Спонсор #{number} не найден.")
        except ValueError:
            await update.message.reply_text("❌ Введите число.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if user.id != ADMIN_BOT_ID:
        return
    
    if not await check_session(user.id):
        await query.edit_message_text(
            "⏰ Сессия истекла.\n\n"
            "Нажмите кнопку 'Бот' для повторной авторизации."
        )
        return
    
    data = query.data
    
    if data == 'push_notification':
        context.user_data['state'] = 'awaiting_push_text'
        await query.edit_message_text(
            "📢 *Push-уведомление*\n\n"
            "📝 Введите текст сообщения:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == 'sponsors':
        context.user_data['state'] = 'awaiting_sponsors_count'
        await query.edit_message_text(
            "👥 *Спонсоры*\n\n"
            "🔢 Введите количество спонсоров (1-10):",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == 'delete_push':
        context.user_data['state'] = 'awaiting_push_delete_code'
        await query.edit_message_text(
            "🗑 *Удалить push*\n\n"
            "🆔 Введите уникальный код сообщения:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == 'remove_sponsors':
        context.user_data['state'] = 'awaiting_sponsor_remove'
        await query.edit_message_text(
            "❌ *Убрать спонсоров*\n\n"
            "Введите:\n"
            "• `all` — удалить всех спонсоров\n"
            "• `one` — удалить одного спонсора",
            parse_mode=ParseMode.MARKDOWN
        )

def parse_time_string(time_str: str) -> Optional[int]:
    try:
        total_seconds = 0
        parts = time_str.lower().split()
        
        i = 0
        while i < len(parts):
            try:
                value = int(parts[i])
                unit = parts[i + 1] if i + 1 < len(parts) else ''
                
                if 'час' in unit or 'hour' in unit:
                    total_seconds += value * 3600
                elif 'мин' in unit or 'min' in unit:
                    total_seconds += value * 60
                elif 'сек' in unit or 'sec' in unit:
                    total_seconds += value
                
                i += 2
            except (ValueError, IndexError):
                i += 1
        
        return total_seconds if total_seconds > 0 else None
    except:
        return None

def generate_push_id() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

async def broadcast_message(text: str, push_id: str, lifetime: int, bot):
    user_ids = await get_all_user_ids()
    
    for user_id in user_ids:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"📢 *Объявление*\n\n{text}",
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send push to {user_id}: {e}")
    
    if lifetime > 0:
        asyncio.create_task(auto_delete_push(push_id, lifetime))

async def auto_delete_push(push_id: str, lifetime: int):
    await asyncio.sleep(lifetime)
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('UPDATE push_messages SET active = 0 WHERE id = ?', (push_id,))
        await db.commit()
    logger.info(f"Push {push_id} auto-deleted after {lifetime} seconds")

def main():
    application = Application.builder().token(ADMIN_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex('^Бот$'), button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logger.info("Админ-бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
