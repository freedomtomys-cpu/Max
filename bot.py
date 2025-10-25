import asyncio
import nest_asyncio
import os
import uuid
import re
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import database as db
import downloader
import payments
import referral_system as ref
from config import TELEGRAM_TOKEN, PACKAGES, FREE_DOWNLOAD_LIMIT, ADMIN_IDS, BOT_USERNAME
import logging

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def delete_message_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 20):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def delete_push_after_timeout(context: ContextTypes.DEFAULT_TYPE, message_id: str, timeout: int):
    await asyncio.sleep(timeout)
    
    recipients = await db.get_push_recipients(message_id)
    for recipient in recipients:
        try:
            await context.bot.delete_message(
                chat_id=recipient['user_id'],
                message_id=recipient['message_id']
            )
        except:
            pass
    
    await db.delete_push_message(message_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user.id, user.username)
    
    if await db.is_user_blocked(user.id):
        await update.message.reply_text(
            "🚫 *Доступ заблокирован*\n\n"
            "Вы были заблокированы администратором.\n"
            "Для получения информации обратитесь в поддержку.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    referred_by = None
    if context.args and len(context.args) > 0:
        ref_code = context.args[0]
        if ref_code.startswith('ref'):
            ref_code = ref_code[3:]
            referrer_id = await ref.get_user_by_referral_code(ref_code)
            if referrer_id and referrer_id != user.id:
                referred_by = referrer_id
    
    await ref.create_referral_account(user.id, referred_by)
    
    if user.id in ADMIN_IDS:
        keyboard = [
            ['📌 Pinterest', '🎵 TikTok'],
            ['📦 Массовая загрузка'],
            ['💎 Plus+', '👤 My Account'],
            ['🔧 Admin Panel']
        ]
    else:
        keyboard = [
            ['📌 Pinterest', '🎵 TikTok'],
            ['📦 Массовая загрузка'],
            ['💎 Plus+', '👤 My Account']
        ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = "⚡ *Привет! Я — MaxSaver* ⚡\n\n" \
        "Скачиваю видео и изображения из *TikTok* и *Pinterest* без водяных знаков:\n" \
        "✅ Быстро и качественно\n" \
        "✅ Поддержка до 4K\n" \
        "✅ Скачивание аудио в MP3\n\n" \
        "📲 *Просто отправь ссылку* — и получишь готовый файл!"
    
    if referred_by:
        welcome_text += "\n\n🎁 *Ты получил 10 монет* за регистрацию по реферальной ссылке!"
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if await db.is_user_blocked(user.id):
        await update.message.reply_text(
            "🚫 *Доступ заблокирован*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if text in ['📌 Pinterest', '🎵 TikTok']:
        await update.message.reply_text(
            "📎 *Отлично!* Теперь отправь мне ссылку 🎥\n\n"
            "Поддерживаются:\n"
            "• TikTok (без водяного знака)\n"
            "• Pinterest (видео и изображения)\n\n"
            "Просто вставь ссылку сюда 👇",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['waiting_for_link'] = text
    
    elif text == '📦 Массовая загрузка':
        has_mass = await db.has_feature(user.id, 'mass_download')
        if not has_mass:
            keyboard = [[InlineKeyboardButton("💎 Подключить функцию", callback_data="buy_mass_download")]]
            await update.message.reply_text(
                "🔒 *Массовая загрузка — премиум функция*\n\n"
                "С ней ты сможешь:\n"
                "📦 Скачивать до 10 видео одновременно\n"
                "⚡ Экономить время\n"
                "🚀 Отправлять все ссылки одним сообщением\n\n"
                "Просто отправь несколько ссылок через пробел или с новой строки!\n\n"
                "💰 *Цена:* 75 ₽ на месяц",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "📦 *Массовая загрузка активна!*\n\n"
                "Отправь мне несколько ссылок одним сообщением:\n\n"
                "*Пример:*\n"
                "`https://www.tiktok.com/@user/video/123\n"
                "https://www.tiktok.com/@user/video/456\n"
                "https://pin.it/abc123`\n\n"
                "✅ До 10 ссылок за раз\n"
                "✅ TikTok и Pinterest\n"
                "✅ Все видео скачаются автоматически",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text == '💎 Plus+':
        await show_packages(update, context)
    
    elif text == '👤 My Account':
        await show_account(update, context)
    
    elif text == '🔧 Admin Panel' and user.id in ADMIN_IDS:
        await show_admin_panel(update, context)

async def show_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Full — 149 ₽ / месяц", callback_data="buy_full")],
        [InlineKeyboardButton("Full+ — 1099 ₽ / год", callback_data="buy_full_plus")],
        [InlineKeyboardButton("4K + Безлимит — 99 ₽", callback_data="buy_4k_unlimited")],
        [InlineKeyboardButton("Массовая загрузка — 75 ₽", callback_data="buy_mass_download")],
        [InlineKeyboardButton("Безлимит на видео — 75 ₽", callback_data="buy_unlimited")],
        [InlineKeyboardButton("4K — 75 ₽", callback_data="buy_4k")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💎 *Раздел Plus+*\n\n"
        "Получи дополнительные возможности:\n"
        "🚀 Безлимитное скачивание\n"
        "🎬 Поддержка 4K видео\n"
        "📦 Массовая загрузка\n\n"
        "Выбери подходящий пакет 👇",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subs = await db.get_user_subscriptions(user.id)
    features = await db.get_active_features(user.id)
    
    username_display = f"@{user.username}" if user.username else "Не указан"
    
    text = f"👤 *Мой аккаунт*\n\n"
    text += f"Ник: {escape_markdown(username_display)}\n"
    text += f"ID: `{user.id}`\n\n"
    
    if subs:
        text += "*✅ Активные функции:*\n"
        feature_names = {
            '4k': '4K',
            'mass_download': 'Массовая загрузка',
            'unlimited': 'Безлимит'
        }
        
        shown_features = set()
        for sub in subs:
            feature = sub['feature']
            if feature not in shown_features:
                expires = sub['expires_at'].split()[0] if ' ' in sub['expires_at'] else sub['expires_at']
                expires_parts = expires.split('-')
                if len(expires_parts) == 3:
                    expires = f"{expires_parts[2]}.{expires_parts[1]}.{expires_parts[0]}"
                text += f"• {feature_names.get(feature, feature)} — до {expires}\n"
                shown_features.add(feature)
        
        all_features = {'4k', 'mass_download', 'unlimited'}
        unavailable = all_features - shown_features
        if unavailable:
            text += "\n*🔒 Недоступные функции:*\n"
            for feature in unavailable:
                text += f"• {feature_names.get(feature, feature)}\n"
    else:
        text += "У вас пока нет активных функций.\n\n"
        text += "💡 Открой раздел *💎Plus\\+*, чтобы получить:\n"
        text += "• Безлимитное скачивание\n"
        text += "• Видео в качестве 4K\n"
        text += "• Массовую загрузку"
    
    keyboard = [[InlineKeyboardButton("🎁 Реферальная программа", callback_data="referral_system")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if await db.is_user_blocked(user.id):
        await update.message.reply_text(
            "🚫 *Доступ заблокирован*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if text.startswith('push:') and user.id in ADMIN_IDS:
        push_text = text[5:].strip()
        if not push_text:
            await update.message.reply_text(
                "❌ Текст сообщения не может быть пустым!\n\n"
                "Используй формат: `push:текст сообщения`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        context.user_data['push_text'] = push_text
        context.user_data['admin_action'] = 'push_lifetime'
        await update.message.reply_text(
            "✅ Текст сохранен!\n\n"
            "Теперь укажи время жизни сообщения в формате `ЧЧ:ММ`:\n\n"
            "*Примеры:*\n"
            "• `ever` - не удалять никогда\n"
            "• `00:05` - 5 минут\n"
            "• `01:30` - 1 час 30 минут\n"
            "• `24:00` - 24 часа\n"
            "• `48:30` - 48 часов 30 минут\n"
            "• `73:00` - 73 часа",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if user.id in ADMIN_IDS and 'admin_action' in context.user_data:
        action = context.user_data.pop('admin_action')
        parts = text.strip().split()
        
        try:
            if action == 'push_lifetime':
                push_text = context.user_data.pop('push_text', '')
                lifetime_str = text.strip().lower()
                
                if lifetime_str == 'ever':
                    lifetime = -1
                else:
                    if ':' in lifetime_str:
                        try:
                            parts = lifetime_str.split(':')
                            if len(parts) == 2:
                                hours = int(parts[0])
                                minutes = int(parts[1])
                                lifetime = hours * 3600 + minutes * 60
                            else:
                                await update.message.reply_text(
                                    "❌ Неверный формат!\n\n"
                                    "Используй формат `ЧЧ:ММ` (например: `24:30` или `00:05`)\n"
                                    "Или `ever` для постоянного сообщения",
                                    parse_mode=ParseMode.MARKDOWN
                                )
                                return
                        except ValueError:
                            await update.message.reply_text(
                                "❌ Неверный формат!\n\n"
                                "Используй формат `ЧЧ:ММ` (например: `24:30` или `00:05`)\n"
                                "Или `ever` для постоянного сообщения",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            return
                    else:
                        await update.message.reply_text(
                            "❌ Неверный формат!\n\n"
                            "Используй формат `ЧЧ:ММ` (например: `24:30` или `00:05`)\n"
                            "Или `ever` для постоянного сообщения",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return
                
                message_id = str(uuid.uuid4())[:8]
                await db.create_push_message(message_id, push_text, lifetime)
                
                user_ids = await db.get_all_user_ids()
                sent_count = 0
                for uid in user_ids:
                    try:
                        msg = await context.bot.send_message(
                            chat_id=uid,
                            text=push_text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        await db.save_push_recipient(message_id, uid, msg.message_id)
                        sent_count += 1
                        if sent_count % 30 == 0:
                            await asyncio.sleep(1)
                    except:
                        pass
                
                await update.message.reply_text(
                    f"✅ Push отправлен!\n\n"
                    f"📊 Отправлено: {sent_count} пользователям\n"
                    f"🆔 ID сообщения: `{message_id}`\n\n"
                    f"Используй этот ID для удаления сообщения",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                if lifetime > 0:
                    asyncio.create_task(delete_push_after_timeout(context, message_id, lifetime))
                return
            
            elif action == 'delete_push':
                message_id = text.strip()
                push_msg = await db.get_push_message(message_id)
                if push_msg:
                    recipients = await db.get_push_recipients(message_id)
                    deleted_count = 0
                    for recipient in recipients:
                        try:
                            await context.bot.delete_message(
                                chat_id=recipient['user_id'],
                                message_id=recipient['message_id']
                            )
                            deleted_count += 1
                        except:
                            pass
                    
                    await db.delete_push_message(message_id)
                    await update.message.reply_text(
                        f"✅ Push уведомление `{message_id}` удалено\n"
                        f"Удалено сообщений: {deleted_count}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("❌ Push уведомление не найдено или уже удалено")
                return
            
            elif action == 'add_sponsors':
                text_input = text.strip()
                
                if text_input.startswith('S:'):
                    try:
                        sponsor_count = int(text_input[2:].strip())
                        context.user_data['sponsor_count'] = sponsor_count
                        context.user_data['sponsor_links'] = []
                        context.user_data['admin_action'] = 'add_sponsor_link'
                        await update.message.reply_text(
                            f"📝 Отправь ссылку для спонсора №1 из {sponsor_count} в формате:\n"
                            f"`W:ссылка_на_канал`"
                        )
                    except ValueError:
                        await update.message.reply_text(
                            "❌ Неверный формат!\n\n"
                            "Используй: `S:число` (например, S:3)",
                            parse_mode=ParseMode.MARKDOWN
                        )
                else:
                    await update.message.reply_text(
                        "❌ Неверный формат!\n\n"
                        "Используй: `S:число` для указания количества спонсоров\n"
                        "Например: `S:3`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                return
            
            elif action == 'add_sponsor_link':
                text_input = text.strip()
                
                if text_input.startswith('W:'):
                    link = text_input[2:].strip()
                    if not link:
                        await update.message.reply_text("❌ Ссылка не может быть пустой!")
                        return
                    
                    context.user_data['sponsor_links'].append(link)
                    current = len(context.user_data['sponsor_links'])
                    total = context.user_data['sponsor_count']
                    
                    if current < total:
                        context.user_data['admin_action'] = 'add_sponsor_link'
                        await update.message.reply_text(
                            f"📝 Отправь ссылку для спонсора №{current + 1} из {total} в формате:\n"
                            f"`W:ссылка_на_канал`"
                        )
                        return
                    else:
                        for link in context.user_data['sponsor_links']:
                            await db.add_sponsor(link)
                        
                        context.user_data.pop('sponsor_count', None)
                        context.user_data.pop('sponsor_links', None)
                        
                        await update.message.reply_text(
                            f"✅ Добавлено {total} спонсоров!\n\n"
                            "Теперь пользователи будут видеть кнопки подписки перед скачиванием."
                        )
                        return
                else:
                    await update.message.reply_text(
                        "❌ Неверный формат!\n\n"
                        "Используй: `W:ссылка` для указания ссылки на канал\n"
                        "Например: `W:https://t.me/channel`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            elif action == 'remove_sponsors':
                choice = text.strip().lower()
                if choice == 'all':
                    await db.delete_all_sponsors()
                    await update.message.reply_text("✅ Все спонсоры удалены")
                elif choice == 'one':
                    context.user_data['admin_action'] = 'remove_sponsor_number'
                    sponsors = await db.get_active_sponsors()
                    if sponsors:
                        text_msg = "Текущие спонсоры:\n\n"
                        for s in sponsors:
                            text_msg += f"Спонсор №{s['position']}: {s['link']}\n"
                        text_msg += "\nОтправь номер спонсора для удаления:"
                        await update.message.reply_text(text_msg)
                    else:
                        await update.message.reply_text("❌ Нет активных спонсоров")
                    return
                else:
                    await update.message.reply_text("❌ Используй `all` или `one`", parse_mode=ParseMode.MARKDOWN)
                return
            
            elif action == 'remove_sponsor_number':
                sponsor_num = int(text.strip())
                sponsors = await db.get_active_sponsors()
                sponsor_to_delete = next((s for s in sponsors if s['position'] == sponsor_num), None)
                if sponsor_to_delete:
                    await db.delete_sponsor(sponsor_to_delete['id'])
                    await update.message.reply_text(f"✅ Спонсор №{sponsor_num} удален")
                else:
                    await update.message.reply_text(f"❌ Спонсор №{sponsor_num} не найден")
                return
            
            elif action == 'user_info' and len(parts) >= 1:
                target_id = int(parts[0])
                user_info = await db.get_user_info(target_id)
                if user_info:
                    subs = await db.get_user_subscriptions(target_id)
                    ref_info = await ref.get_referral_info(target_id)
                    blocked_status = "🚫 Заблокирован" if user_info['is_blocked'] else "✅ Активен"
                    username = f"@{user_info['username']}" if user_info['username'] else "Не указан"
                    
                    info_text = f"👤 *Информация о пользователе:*\n\n"
                    info_text += f"ID: `{target_id}`\n"
                    info_text += f"Ник: {escape_markdown(username)}\n"
                    info_text += f"Статус: {blocked_status}\n"
                    info_text += f"Первое посещение: {user_info['first_seen']}\n\n"
                    
                    if ref_info:
                        info_text += f"💰 *Баланс монет:* {ref_info['coins_balance']}\n"
                        info_text += f"👥 *Рефералов:* {ref_info['total_referrals']}\n\n"
                    
                    if subs:
                        info_text += "*Активные подписки:*\n"
                        for sub in subs:
                            info_text += f"• {sub['feature']} - до {sub['expires_at']}\n"
                    else:
                        info_text += "Подписок нет"
                    
                    await update.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ Пользователь не найден")
                return
            
            elif action == 'block' and len(parts) >= 1:
                target_id = int(parts[0])
                await db.block_user(target_id)
                await update.message.reply_text(f"🚫 Пользователь {target_id} заблокирован")
                return
            
            elif action == 'unblock' and len(parts) >= 1:
                target_id = int(parts[0])
                await db.unblock_user(target_id)
                await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован")
                return
            
            elif action == 'give_package' and len(parts) >= 2:
                target_id = int(parts[0])
                package_key = parts[1]
                package = PACKAGES.get(package_key)
                
                if package:
                    existing_subs = await db.get_user_subscriptions(target_id)
                    has_features = set()
                    for sub in existing_subs:
                        has_features.add(sub['feature'])
                    
                    new_features = set(package['features'])
                    already_has = new_features & has_features
                    
                    if already_has:
                        features_list = ', '.join(already_has)
                        await update.message.reply_text(
                            f"ℹ️ У пользователя {target_id} уже есть функции: {features_list}\n\n"
                            f"Пакет {package['name']} все равно выдан, время продлено."
                        )
                    
                    await db.add_subscription(target_id, package['features'], package['duration_days'])
                    
                    try:
                        await context.bot.send_message(
                            chat_id=target_id,
                            text=f"🎁 *Поздравляем!*\n\n"
                                 f"Тебе был выдан пакет *{package['name']}*!\n"
                                 f"Все функции активированы и готовы к использованию! ⚡",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
                    
                    await update.message.reply_text(f"✅ Пакет {package['name']} выдан пользователю {target_id}")
                else:
                    await update.message.reply_text("❌ Неизвестный пакет")
                return
            
            elif action == 'remove_feature' and len(parts) >= 2:
                target_id = int(parts[0])
                feature = parts[1]
                await db.remove_user_feature(target_id, feature)
                await update.message.reply_text(f"✅ Функция {feature} удалена у пользователя {target_id}")
                return
            
            elif action == 'removeall' and len(parts) >= 1:
                target_id = int(parts[0])
                await db.remove_all_user_features(target_id)
                await update.message.reply_text(f"✅ Все функции удалены у пользователя {target_id}")
                return
            
            elif action == 'extend' and len(parts) >= 3:
                target_id = int(parts[0])
                feature = parts[1]
                days = int(parts[2])
                await db.update_subscription_expiry(target_id, feature, days)
                await update.message.reply_text(f"✅ Функция {feature} продлена на {days} дней для пользователя {target_id}")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат данных. Попробуй снова.")
            return
    
    urls = downloader.extract_urls(text)
    
    if not urls:
        msg = await update.message.reply_text(
            "🤔 *Не понял тебя...*\n\n"
            "Отправь мне ссылку на видео с:\n"
            "• TikTok\n"
            "• Pinterest\n\n"
            "Или воспользуйся меню ниже 👇",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 20))
        return
    
    has_mass = await db.has_feature(user.id, 'mass_download')
    
    if len(urls) > 1 and not has_mass:
        msg = await update.message.reply_text(
            "🚫 *Массовая загрузка* — это функция премиум!\n\n"
            "С ней ты сможешь:\n"
            "📦 Скачивать несколько видео одновременно\n"
            "⚡ Экономить время\n\n"
            "Подключи функцию в разделе 💎*Plus+*",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 20))
        return
    
    if len(urls) > 10:
        msg = await update.message.reply_text(
            "⚠️ *Слишком много ссылок!*\n\n"
            "Максимум: *10 видео* за раз\n"
            "Сейчас: *{} видео*\n\n"
            "Разбей ссылки на несколько сообщений 👇".format(len(urls)),
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 20))
        return
    
    if len(urls) > 1:
        keyboard = [
            [InlineKeyboardButton("🎥 HD качество (720p)", callback_data=f"mass_quality_hd")],
            [InlineKeyboardButton("📱 Среднее качество (480p)", callback_data=f"mass_quality_medium")],
            [InlineKeyboardButton("🔽 Низкое качество (360p)", callback_data=f"mass_quality_low")],
            [InlineKeyboardButton("🎧 Только аудио (MP3)", callback_data=f"mass_quality_audio")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        context.user_data['mass_urls'] = urls
        
        await update.message.reply_text(
            f"📦 *Массовая загрузка*\n\n"
            f"Найдено видео: *{len(urls)}*\n\n"
            f"Выбери единое качество для всех видео 👇",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        for url in urls:
            await process_video_url(update, context, url)

async def process_mass_download_video(query, context: ContextTypes.DEFAULT_TYPE, url: str, quality: str):
    user = query.from_user
    
    if not downloader.is_valid_url(url):
        return
    
    info = await downloader.extract_video_info_async(url)
    if not info:
        return
    
    try:
        audio_only = quality == 'audio'
        filename = await downloader.download_video(url, quality if quality != 'audio' else None, audio_only)
        
        if filename and os.path.exists(filename):
            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            
            if file_size_mb > 2000:
                os.remove(filename)
                return
            
            platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
            await db.add_download(user.id, platform)
            await ref.process_download_coins(user.id)
            
            try:
                if audio_only:
                    with open(filename, 'rb') as audio_file:
                        await query.message.reply_audio(
                            audio=audio_file,
                            caption="✅ *Готово!*\n\n🎧 Вот твой аудиофайл",
                            parse_mode=ParseMode.MARKDOWN,
                            read_timeout=300,
                            write_timeout=300
                        )
                elif file_size_mb > 50:
                    await query.message.reply_document(
                        document=open(filename, 'rb'),
                        caption=f"✅ *Готово!*\n\n🎬 Видео ({file_size_mb:.1f} MB)",
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=1800,
                        write_timeout=1800
                    )
                else:
                    with open(filename, 'rb') as video_file:
                        await query.message.reply_video(
                            video=video_file,
                            caption="✅ *Готово!*",
                            parse_mode=ParseMode.MARKDOWN,
                            supports_streaming=True,
                            read_timeout=300,
                            write_timeout=300
                        )
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")
            finally:
                if os.path.exists(filename):
                    os.remove(filename)
    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")

async def check_sponsors_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    sponsors = await db.get_active_sponsors()
    if not sponsors:
        return True
    
    current_sponsors_ids = '_'.join([str(s['id']) for s in sponsors])
    
    checked_sponsors = await db.check_user_subscribed_sponsors(user_id)
    if checked_sponsors == current_sponsors_ids:
        return True
    
    keyboard = []
    for sponsor in sponsors:
        keyboard.append([InlineKeyboardButton(f"✅ Спонсор №{sponsor['position']}", url=sponsor['link'])])
    keyboard.append([InlineKeyboardButton("✅ Проверить подписку", callback_data=f"check_sponsor_{user_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📢 *Подпишись на наших спонсоров*\n\n"
        "Для продолжения скачивания подпишись на каналы и нажми кнопку проверки:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    return False

async def process_video_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user = update.effective_user
    
    sponsors_ok = await check_sponsors_subscription(update, context, user.id)
    if not sponsors_ok:
        return
    
    if not downloader.is_valid_url(url):
        msg = await update.message.reply_text(
            "⚠️ *Эта ссылка не поддерживается*\n\n"
            "Я работаю только с:\n"
            "✅ TikTok\n"
            "✅ Pinterest\n\n"
            "Проверь ссылку и попробуй снова!",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 20))
        return
    
    info = await downloader.extract_video_info_async(url)
    if not info:
        msg = await update.message.reply_text(
            "🚫 *Ошибка при обработке контента*\n\n"
            "Возможные причины:\n"
            "• Контент недоступен или удален\n"
            "• Проблемы с сервером TikTok/Pinterest\n\n"
            "⚙️ Попробуй снова через минуту или отправь другую ссылку",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 30))
        return
    
    has_unlimited = await db.has_feature(user.id, 'unlimited')
    if not has_unlimited:
        download_count = await db.get_download_count_24h(user.id)
        if download_count >= FREE_DOWNLOAD_LIMIT:
            keyboard = [[InlineKeyboardButton("💎 Открыть Plus+", callback_data="show_packages")]]
            msg = await update.message.reply_text(
                f"⚠️ *Лимит бесплатных загрузок исчерпан!*\n\n"
                f"Бесплатный тариф: *{FREE_DOWNLOAD_LIMIT} видео* за 24 часа\n\n"
                "🚀 Хочешь безлимит?\n"
                "Подключи пакет 💎*Plus+* и скачивай сколько хочешь!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            asyncio.create_task(delete_message_later(context, update.effective_chat.id, msg.message_id, 30))
            return
    
    download_id = str(uuid.uuid4())[:8]
    await db.store_pending_download(download_id, url, user.id)
    
    keyboard = []
    has_4k = await db.has_feature(user.id, '4k')
    
    if info['platform'] == 'tiktok':
        if info.get('formats'):
            for fmt in info['formats']:
                quality_id = fmt['format_id']
                quality_name = fmt['quality']
                keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality_name} (без водяного знака)", callback_data=f"dl_{quality_id}_{download_id}")])
        else:
            keyboard.append([InlineKeyboardButton("🎥 Видео (без водяного знака)", callback_data=f"dl_hd_{download_id}")])
        keyboard.append([InlineKeyboardButton("🎧 Аудио (MP3)", callback_data=f"dl_audio_{download_id}")])
    else:
        for fmt in info['formats']:
            quality = fmt['quality']
            if '2160' in quality or '4k' in quality.lower():
                keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality} 💎", callback_data=f"dl_{quality}_{download_id}" if has_4k else f"need_4k")])
            else:
                keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality}", callback_data=f"dl_{quality}_{download_id}")])
        
        keyboard.append([InlineKeyboardButton("🎧 Аудио (MP3)", callback_data=f"dl_audio_{download_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    duration_str = downloader.format_duration(info['duration']) if info['duration'] else "Неизвестно"
    
    text = f"🎬 *Видео найдено!*\n\n"
    text += f"📝 *Название:*\n{info['title'][:80]}{'...' if len(info['title']) > 80 else ''}\n\n"
    text += f"⏱ *Длительность:* {duration_str}\n\n"
    text += "Выбери формат для скачивания 👇"
    
    if info['thumbnail']:
        try:
            preview_msg = await update.message.reply_photo(
                photo=info['thumbnail'],
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            context.user_data[f'preview_{url}'] = preview_msg.message_id
        except:
            preview_msg = await update.message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            context.user_data[f'preview_{url}'] = preview_msg.message_id
    else:
        preview_msg = await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        context.user_data[f'preview_{url}'] = preview_msg.message_id

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if await db.is_user_blocked(user.id):
        await query.answer("🚫 Доступ заблокирован", show_alert=True)
        return
    
    if data.startswith('buy_'):
        package_key = data.replace('buy_', '')
        package = PACKAGES.get(package_key)
        
        if package:
            features_text = ""
            if '4k' in package['features']:
                features_text += "✅ Скачивание 4K\n"
            if 'unlimited' in package['features']:
                features_text += "✅ Безлимит скачиваний\n"
            if 'mass_download' in package['features']:
                features_text += "✅ Массовая загрузка\n"
            
            duration = f"{package['duration_days'] // 30} месяц" if package['duration_days'] == 30 else "год"
            
            payment_info = payments.create_payment(
                package['price'],
                f"{package['name']} - {user.id}",
                user.id
            )
            
            if payment_info:
                await db.create_payment(user.id, package_key, package['price'], payment_info['id'])
                
                keyboard = [
                    [InlineKeyboardButton("💳 Оплатить", url=payment_info['confirmation_url'])],
                    [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_{payment_info['id']}")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                text = f"✨ *Пакет {package['name']}*\n\n"
                text += "*Что включено:*\n"
                text += features_text
                text += f"\n💰 *Цена:* {package['price']} ₽ / {duration}"
                
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.edit_message_text("Ошибка создания платежа. Попробуйте позже.")
    
    elif data.startswith('check_sponsor_'):
        user_id_str = data.replace('check_sponsor_', '')
        user_id_int = int(user_id_str)
        sponsors = await db.get_active_sponsors()
        current_sponsors_ids = '_'.join([str(s['id']) for s in sponsors])
        
        await db.store_user_subscription_check(user_id_int, current_sponsors_ids)
        
        await query.answer("✅ Проверка пройдена! Теперь можешь скачивать видео", show_alert=True)
        try:
            await query.message.delete()
        except:
            pass
    
    elif data.startswith('check_'):
        payment_id = data.replace('check_', '')
        payment_info = payments.check_payment_status(payment_id)
        status = payment_info['status']
        paid = payment_info['paid']
        
        if status == 'succeeded' and paid:
            payment_data = await db.get_payment(payment_id)
            if payment_data and payment_data['status'] != 'succeeded':
                package_key = payment_data['package_key']
                package = PACKAGES.get(package_key)
                
                if package:
                    await db.add_subscription(user.id, package['features'], package['duration_days'])
                    await db.update_payment_status(payment_id, 'succeeded')
                    
                    msg = await query.edit_message_text(
                        "✅ *Оплата успешна!*\n\n"
                        "🎉 Функция активирована\n"
                        "Можешь пользоваться прямо сейчас! ⚡",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    asyncio.create_task(delete_message_later(context, query.message.chat_id, msg.message_id, 15))
            else:
                await query.edit_message_text(
                    "✅ *Подписка уже активирована!*\n\n"
                    "Вы уже оплатили этот пакет ранее.",
                    parse_mode=ParseMode.MARKDOWN
                )
        elif (status == 'pending' or status == 'waiting_for_capture') and paid:
            await query.edit_message_text(
                "⏳ *Оплата обрабатывается*\n\n"
                "Платёж оплачен и обрабатывается банком.\n"
                "Подожди немного и нажми 'Проверить оплату' снова.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif status == 'canceled':
            await query.edit_message_text(
                "❌ *Платёж отменён*\n\n"
                "Платёж был отменён.\n"
                "Попробуй оплатить снова, нажав кнопку 'Оплатить'.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif status == 'error':
            await query.edit_message_text(
                "⚠️ *Ошибка платежа*\n\n"
                "Произошла ошибка при обработке платежа.\n"
                "Попробуй создать новый платёж.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(
                "❌ *Платёж не оплачен*\n\n"
                "Платёж ещё не был оплачен.\n\n"
                "1️⃣ Сначала нажми кнопку '💳 Оплатить'\n"
                "2️⃣ Оплати через форму ЮКассы\n"
                "3️⃣ Вернись и нажми '🔄 Проверить оплату'",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data == 'need_4k':
        await query.answer("⚠️ 4K доступно только с подпиской!\n\nПодключи пакет 💎4K или Full в разделе Plus+", show_alert=True)
    
    elif data.startswith('mass_quality_'):
        quality_type = data.replace('mass_quality_', '')
        urls = context.user_data.get('mass_urls', [])
        
        if not urls:
            await query.answer("❌ Ошибка: список URL не найден", show_alert=True)
            return
        
        quality_map = {
            'hd': '720p',
            'medium': '480p',
            'low': '360p',
            'audio': 'audio'
        }
        
        selected_quality = quality_map.get(quality_type, 'hd')
        
        await query.edit_message_text(
            f"📦 *Массовая загрузка*\n\n"
            f"Найдено видео: *{len(urls)}*\n"
            f"Обработано: 0/{len(urls)}\n\n"
            f"⏳ Начинаем загрузку...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        status_msg = query.message
        
        for idx, url in enumerate(urls, 1):
            try:
                await status_msg.edit_text(
                    f"📦 *Массовая загрузка*\n\n"
                    f"Найдено видео: *{len(urls)}*\n"
                    f"Обработано: {idx-1}/{len(urls)}\n\n"
                    f"⏳ Загружаю видео {idx}...",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            await process_mass_download_video(query, context, url, selected_quality)
        
        try:
            await status_msg.edit_text(
                f"✅ *Массовая загрузка завершена!*\n\n"
                f"Всего загружено: *{len(urls)} видео*\n\n"
                f"Все файлы отправлены выше 👆",
                parse_mode=ParseMode.MARKDOWN
            )
            asyncio.create_task(delete_message_later(context, status_msg.chat_id, status_msg.message_id, 30))
        except:
            pass
        
        context.user_data.pop('mass_urls', None)
    
    elif data == 'referral_system':
        ref_info = await ref.get_referral_info(user.id)
        if ref_info:
            ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{ref_info['referral_code']}"
            
            text = "🎁 *Приглашай и получай монеты!*\n\n"
            text += "Делись своей ссылкой, зови друзей и открывай функции бесплатно.\n\n"
            text += f"💰 Твой баланс: *{ref_info['coins_balance']}* монет\n"
            text += f"👥 Всего приглашено: *{ref_info['total_referrals']}*\n"
            text += f"💎 Всего заработано: *{ref_info['total_earned_coins']}* монет\n"
            text += f"🎁 Заработано от рефералов: *{int(ref_info['earned_from_referrals'])}* монет\n"
            text += f"🛒 Покупок на сумму: *{ref_info['total_spent_coins']}* монет\n\n"
            text += f"📎 *Твоя ссылка:*\n`{ref_link}`\n\n"
            text += "Выбери награду 👇"
            
            keyboard = [
                [InlineKeyboardButton("💎 Полный пакет на год — 17 599 монет", callback_data="ref_buy_full_year")],
                [InlineKeyboardButton("💎 Полный пакет на месяц — 2 600 монет", callback_data="ref_buy_full_month")],
                [InlineKeyboardButton("🎬 4K + Безлимит — 1 800 монет", callback_data="ref_buy_4k_unlimited")],
                [InlineKeyboardButton("📦 Массовая загрузка — 360 монет", callback_data="ref_buy_mass")],
                [InlineKeyboardButton("💡 Как приглашать друзей", callback_data="ref_how_to")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.answer("Ошибка: аккаунт не найден", show_alert=True)
    
    elif data == 'ref_how_to':
        text = "📚 *Как приглашать друзей и зарабатывать монеты*\n\n"
        text += "1️⃣ *PR GRAM*\n"
        text += "Добавь свою ссылку на платформах вроде [PR GRAM](https://t.me/gram_piarbot?start=1459753369), где участники обмениваются подписками и входами в ботов.\n\n"
        text += "2️⃣ *Друзья и знакомые*\n"
        text += "Просто отправь ссылку тем, кто ещё не знает про бота. Например: «Смотри, этот бот скачивает видео из TikTok и Pinterest, попробуй по моей ссылке».\n\n"
        text += "3️⃣ *Телеграм-чаты и группы*\n"
        text += "Делись ссылкой в тематических чатах, где обсуждают видео, TikTok, Pinterest, загрузки и т.д.\n\n"
        text += "4️⃣ *TikTok и соцсети*\n"
        text += "Сними короткий ролик о том, как ты пользуешься ботом, добавь ссылку в описании или комментарии.\n\n"
        text += "💰 *Бонусы и вознаграждения:*\n"
        text += "• За приглашение нового пользователя — *+20 монет*\n"
        text += "• За скачанное видео — *+1 монета*\n"
        text += "• За скачанное видео другом — *+0.5 монеты*\n"
        text += "• Приглашённому пользователю при старте — *+10 монет*"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="referral_system")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
    
    elif data.startswith('ref_buy_'):
        print(f"DEBUG: Processing ref_buy_ callback: {data}")
        try:
            ref_info = await ref.get_referral_info(user.id)
            print(f"DEBUG: ref_info = {ref_info}")
            if not ref_info:
                print("DEBUG: No ref_info found")
                await query.edit_message_text("❌ Ошибка: аккаунт не найден")
                return
            
            package_map = {
                'ref_buy_full_year': {'name': 'Полный пакет на год', 'cost': 17599, 'features': ['4k', 'unlimited', 'mass_download'], 'days': 365},
                'ref_buy_full_month': {'name': 'Полный пакет на месяц', 'cost': 2600, 'features': ['4k', 'unlimited', 'mass_download'], 'days': 30},
                'ref_buy_4k_unlimited': {'name': '4K + Безлимит', 'cost': 1800, 'features': ['4k', 'unlimited'], 'days': 30},
                'ref_buy_mass': {'name': 'Массовая загрузка', 'cost': 360, 'features': ['mass_download'], 'days': 30},
            }
            
            package = package_map.get(data)
            print(f"DEBUG: package = {package}")
            if not package:
                await query.edit_message_text("❌ Ошибка: пакет не найден")
                return
            
            current_balance = ref_info['coins_balance']
            print(f"DEBUG: current_balance={current_balance}, cost={package['cost']}")
            if current_balance < package['cost']:
                print("DEBUG: Not enough coins")
                await query.edit_message_text(
                    f"❌ *Недостаточно монет!*\n\n"
                    f"Нужно: {package['cost']} монет\n"
                    f"У вас: {current_balance} монет\n"
                    f"Не хватает: {package['cost'] - current_balance} монет\n\n"
                    f"Продолжай приглашать друзей и зарабатывай монеты! 💰",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            print("DEBUG: Attempting to spend coins")
            success = await ref.spend_coins(user.id, package['cost'], f"Покупка {package['name']}")
            print(f"DEBUG: spend_coins result = {success}")
            if success:
                print("DEBUG: Adding subscriptions")
                for feature in package['features']:
                    await db.add_subscription(user.id, [feature], package['days'])
                
                new_balance = current_balance - package['cost']
                print(f"DEBUG: Purchase successful, new_balance = {new_balance}")
                await query.edit_message_text(
                    f"🎉 *Поздравляем!*\n\n"
                    f"Ты успешно приобрел *{package['name']}* за {package['cost']} монет!\n\n"
                    f"💰 Новый баланс: {new_balance} монет\n\n"
                    f"Функция активирована и готова к использованию! ⚡\n\n"
                    f"Чтобы вернуться в главное меню, используй /start",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                print("DEBUG: Failed to spend coins")
                await query.edit_message_text("❌ Ошибка при списании монет. Попробуйте снова.")
        except Exception as e:
            print(f"ERROR in ref_buy handler: {e}")
            import traceback
            traceback.print_exc()
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")
    
    elif data == 'show_packages':
        keyboard = [
            [InlineKeyboardButton("Full — 149 ₽ / месяц", callback_data="buy_full")],
            [InlineKeyboardButton("Full+ — 1099 ₽ / год", callback_data="buy_full_plus")],
            [InlineKeyboardButton("4K + Безлимит — 99 ₽", callback_data="buy_4k_unlimited")],
            [InlineKeyboardButton("Массовая загрузка — 75 ₽", callback_data="buy_mass_download")],
            [InlineKeyboardButton("Безлимит на видео — 75 ₽", callback_data="buy_unlimited")],
            [InlineKeyboardButton("4K — 75 ₽", callback_data="buy_4k")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💎 *Раздел Plus+*\n\n"
            "Получи дополнительные возможности:\n"
            "🚀 Безлимитное скачивание\n"
            "🎬 Поддержка 4K видео\n"
            "📦 Массовая загрузка\n\n"
            "Выбери подходящий пакет 👇",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data.startswith('dl_'):
        parts = data.split('_', 2)
        
        download_id = parts[2] if len(parts) > 2 else parts[1]
        pending = await db.get_pending_download(download_id)
        
        if not pending:
            await query.answer("Ошибка: ссылка не найдена. Попробуй отправить ссылку снова.", show_alert=True)
            return
        
        url = pending['url']
        
        if parts[1] == 'audio':
            quality = None
            audio_only = True
        elif parts[1] == 'video':
            quality = None
            audio_only = False
        else:
            quality = parts[1]
            audio_only = False
        
        await db.delete_pending_download(download_id)
        
        if url:
            try:
                await query.message.delete()
            except:
                pass
            
            loading_msg = await query.message.reply_text(
                "⏳ *Скачиваю видео...*\n\n"
                "⚡ Обычно это занимает 5-15 секунд\n"
                "Пожалуйста, подожди немного...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            try:
                filename = await downloader.download_video(url, quality, audio_only)
                
                if filename and os.path.exists(filename):
                    # Проверка размера файла
                    file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                    logger.info(f"Downloaded file size: {file_size_mb:.2f} MB")
                    
                    # Для очень больших файлов (>2GB) - технический лимит
                    if file_size_mb > 2000:
                        os.remove(filename)
                        await loading_msg.edit_text(
                            f"⚠️ *Файл слишком большой!*\n\n"
                            f"📦 Размер: *{file_size_mb:.1f} MB*\n"
                            f"🚫 Максимальный лимит: *2000 MB*\n\n"
                            f"💡 Выбери меньшее качество (720p, 480p или 360p)",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        asyncio.create_task(delete_message_later(context, query.message.chat_id, loading_msg.message_id, 40))
                        return
                    
                    platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
                    await db.add_download(user.id, platform)
                    
                    await ref.process_download_coins(user.id)
                    
                    try:
                        if audio_only:
                            logger.info("Отправка аудио файла...")
                            with open(filename, 'rb') as audio_file:
                                await query.message.reply_audio(
                                    audio=audio_file,
                                    caption="✅ *Готово!*\n\n🎧 Вот твой аудиофайл в формате MP3\n\nСпасибо, что пользуешься ⚡*MaxSaver*",
                                    parse_mode=ParseMode.MARKDOWN,
                                    read_timeout=300,
                                    write_timeout=300
                                )
                            logger.info("Аудио файл успешно отправлен")
                        elif file_size_mb > 50:
                            # Большие видео отправляем как документ (лимит 2GB вместо 50MB)
                            logger.info(f"Отправка большого видео как документ ({file_size_mb:.1f} MB)...")
                            
                            # Для очень больших файлов показываем прогресс
                            if file_size_mb > 500:
                                await loading_msg.edit_text(
                                    f"📤 *Отправка файла ({file_size_mb:.1f} MB)*\n\n"
                                    f"⏳ Это может занять несколько минут\n"
                                    f"Пожалуйста, не закрывайте чат...",
                                    parse_mode=ParseMode.MARKDOWN
                                )
                            
                            # Отправляем файл по пути для больших размеров (не загружаем в память)
                            await query.message.reply_document(
                                document=open(filename, 'rb'),
                                caption=f"✅ *Готово!*\n\n🎬 Видео ({file_size_mb:.1f} MB)\n\n📦 Отправлено как документ из-за большого размера\nВидео можно смотреть прямо в Telegram!\n\nСпасибо, что пользуешься ⚡*MaxSaver*",
                                parse_mode=ParseMode.MARKDOWN,
                                read_timeout=1800,
                                write_timeout=1800,
                                connect_timeout=300,
                                pool_timeout=300
                            )
                            logger.info("Документ успешно отправлен")
                        else:
                            # Маленькие видео отправляем как видео
                            logger.info("Отправка видео...")
                            with open(filename, 'rb') as video_file:
                                await query.message.reply_video(
                                    video=video_file,
                                    caption="✅ *Готово!*\n\n🎬 Вот твоё видео без водяных знаков\n\nСпасибо, что пользуешься ⚡*MaxSaver*",
                                    parse_mode=ParseMode.MARKDOWN,
                                    supports_streaming=True,
                                    read_timeout=300,
                                    write_timeout=300
                                )
                            logger.info("Видео успешно отправлено")
                    except Exception as send_error:
                        logger.error(f"Ошибка при отправке файла: {str(send_error)}", exc_info=True)
                        await loading_msg.edit_text(
                            "🚫 *Ошибка при отправке файла*\n\n"
                            "Возможно, файл слишком большой или проблемы с сетью.\n"
                            "Попробуй выбрать меньшее качество.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        raise
                    finally:
                        if os.path.exists(filename):
                            logger.info(f"Удаление временного файла: {filename}")
                            os.remove(filename)
                    
                    try:
                        await loading_msg.delete()
                    except Exception as del_error:
                        logger.warning(f"Не удалось удалить сообщение загрузки: {del_error}")
                else:
                    await loading_msg.edit_text(
                        "🚫 *Ошибка при загрузке*\n\n"
                        "Возможные причины:\n"
                        "• Видео недоступно\n"
                        "• Слишком большой размер файла\n"
                        "• Проблемы на сервере\n\n"
                        "⚙️ Попробуй позже или выбери другое качество",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    asyncio.create_task(delete_message_later(context, query.message.chat_id, loading_msg.message_id, 30))
            except Exception as e:
                print(f"Download error: {e}")
                await loading_msg.edit_text(
                    "🚫 *Ошибка при загрузке*\n\n"
                    "Возможные причины:\n"
                    "• Видео недоступно\n"
                    "• Слишком большой размер файла\n"
                    "• Проблемы на сервере\n\n"
                    "⚙️ Попробуй позже или выбери другое качество",
                    parse_mode=ParseMode.MARKDOWN
                )
                asyncio.create_task(delete_message_later(context, query.message.chat_id, loading_msg.message_id, 30))
    
    elif data.startswith('admin_') and user.id in ADMIN_IDS:
        if data == 'admin_send_push':
            await query.edit_message_text(
                "📢 *Отправить Push уведомление*\n\n"
                "Отправь сообщение в формате:\n"
                "`push:текст вашего сообщения`\n\n"
                "Пример:\n"
                "`push:Новое обновление бота! Добавлена поддержка 4K видео`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == 'admin_delete_push':
            await query.edit_message_text(
                "🗑 *Удалить Push уведомление*\n\n"
                "Отправь ID сообщения:",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'delete_push'
        elif data == 'admin_add_sponsors':
            await query.edit_message_text(
                "👥 *Добавить спонсоров*\n\n"
                "Сначала укажи количество спонсоров в формате:\n"
                "`S:число`\n\n"
                "Например: `S:3` для добавления 3 спонсоров",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'add_sponsors'
        elif data == 'admin_remove_sponsors':
            await query.edit_message_text(
                "❌ *Убрать спонсоров*\n\n"
                "Выбери вариант:\n"
                "• `all` - удалить всех\n"
                "• `one` - удалить одного",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'remove_sponsors'
        elif data == 'admin_stats':
            stats = await db.get_statistics()
            users_count = await db.get_all_users_count()
            active_subs = await db.get_active_subscriptions_count()
            await query.edit_message_text(
                f"📊 *Статистика бота:*\n\n"
                f"👥 Всего пользователей: *{users_count}*\n"
                f"💎 Активных подписок: *{active_subs}*\n"
                f"📥 Всего скачиваний: *{stats['total_downloads']}*\n"
                f"💰 Общая сумма покупок: *{stats['total_revenue']:.2f} ₽*",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == 'admin_user_info':
            await query.edit_message_text(
                "👤 *Информация о пользователе*\n\n"
                "Отправь ID пользователя:",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'user_info'
        elif data == 'admin_block':
            await query.edit_message_text(
                "🚫 *Блокировка пользователя*\n\n"
                "Отправь ID пользователя для блокировки:",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'block'
        elif data == 'admin_unblock':
            await query.edit_message_text(
                "✅ *Разблокировка пользователя*\n\n"
                "Отправь ID пользователя для разблокировки:",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'unblock'
        elif data == 'admin_give_package':
            await query.edit_message_text(
                "💎 *Выдать пакет*\n\n"
                "Отправь данные в формате:\n"
                "`user_id package`\n\n"
                "*Доступные пакеты:* full, full\\_plus, 4k\\_unlimited, mass\\_download, unlimited, 4k",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'give_package'
        elif data == 'admin_remove_feature':
            await query.edit_message_text(
                "❌ *Удалить функцию*\n\n"
                "Отправь данные в формате:\n"
                "`user_id feature`\n\n"
                "*Доступные функции:* 4k, unlimited, mass\\_download",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'remove_feature'
        elif data == 'admin_removeall':
            await query.edit_message_text(
                "🗑 *Удалить все функции*\n\n"
                "Отправь ID пользователя:",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'removeall'
        elif data == 'admin_extend':
            await query.edit_message_text(
                "⏰ *Продлить функцию*\n\n"
                "Отправь данные в формате:\n"
                "`user_id feature days`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['admin_action'] = 'extend'

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Отправить Push уведомление", callback_data="admin_send_push")],
        [InlineKeyboardButton("🗑 Удалить Push уведомление", callback_data="admin_delete_push")],
        [InlineKeyboardButton("👥 Спонсоры", callback_data="admin_add_sponsors")],
        [InlineKeyboardButton("❌ Убрать спонсоров", callback_data="admin_remove_sponsors")],
        [InlineKeyboardButton("👤 Информация о пользователе", callback_data="admin_user_info")],
        [InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block")],
        [InlineKeyboardButton("✅ Разблокировать пользователя", callback_data="admin_unblock")],
        [InlineKeyboardButton("💎 Выдать пакет", callback_data="admin_give_package")],
        [InlineKeyboardButton("❌ Удалить функцию", callback_data="admin_remove_feature")],
        [InlineKeyboardButton("🗑 Удалить все функции", callback_data="admin_removeall")],
        [InlineKeyboardButton("⏰ Продлить функцию", callback_data="admin_extend")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔧 *Админ-панель*\n\n"
        "Выбери действие:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "🔧 *Команды админа:*\n\n"
            "*Статистика:*\n"
            "/admin stats \\- общая статистика\n\n"
            "*Управление пользователями:*\n"
            "/admin block \\[user\\_id\\] \\- заблокировать\n"
            "/admin unblock \\[user\\_id\\] \\- разблокировать\n"
            "/admin info \\[user\\_id\\] \\- информация о пользователе\n\n"
            "*Управление подписками:*\n"
            "/admin give \\[user\\_id\\] \\[package\\] \\- выдать пакет\n"
            "/admin remove \\[user\\_id\\] \\[feature\\] \\- удалить функцию\n"
            "/admin removeall \\[user\\_id\\] \\- удалить все функции\n"
            "/admin extend \\[user\\_id\\] \\[feature\\] \\[days\\] \\- продлить функцию\n\n"
            "*Доступные пакеты:* full, full\\_plus, 4k\\_unlimited, mass\\_download, unlimited, 4k\n"
            "*Доступные функции:* 4k, unlimited, mass\\_download",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    command = args[0]
    
    if command == 'stats':
        stats = await db.get_statistics()
        users_count = await db.get_all_users_count()
        active_subs = await db.get_active_subscriptions_count()
        await update.message.reply_text(
            f"📊 *Статистика бота:*\n\n"
            f"👥 Всего пользователей: *{users_count}*\n"
            f"💎 Активных подписок: *{active_subs}*\n"
            f"📥 Всего скачиваний: *{stats['total_downloads']}*\n"
            f"💰 Общая сумма покупок: *{stats['total_revenue']:.2f} ₽*",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif command == 'block' and len(args) > 1:
        target_id = int(args[1])
        await db.block_user(target_id)
        await update.message.reply_text(f"🚫 Пользователь {target_id} заблокирован")
    
    elif command == 'unblock' and len(args) > 1:
        target_id = int(args[1])
        await db.unblock_user(target_id)
        await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован")
    
    elif command == 'info' and len(args) > 1:
        target_id = int(args[1])
        user_info = await db.get_user_info(target_id)
        if user_info:
            subs = await db.get_user_subscriptions(target_id)
            ref_info = await ref.get_referral_info(target_id)
            blocked_status = "🚫 Заблокирован" if user_info['is_blocked'] else "✅ Активен"
            username = f"@{user_info['username']}" if user_info['username'] else "Не указан"
            
            info_text = f"👤 *Информация о пользователе:*\n\n"
            info_text += f"ID: `{target_id}`\n"
            info_text += f"Ник: {escape_markdown(username)}\n"
            info_text += f"Статус: {blocked_status}\n"
            info_text += f"Первое посещение: {user_info['first_seen']}\n\n"
            
            if ref_info:
                info_text += f"💰 *Баланс монет:* {ref_info['coins_balance']}\n"
                info_text += f"👥 *Рефералов:* {ref_info['total_referrals']}\n\n"
            
            if subs:
                info_text += "*Активные подписки:*\n"
                for sub in subs:
                    info_text += f"• {sub['feature']} - до {sub['expires_at']}\n"
            else:
                info_text += "Подписок нет"
            
            await update.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Пользователь не найден")
    
    elif command == 'give' and len(args) > 2:
        target_id = int(args[1])
        package_key = args[2]
        package = PACKAGES.get(package_key)
        
        if package:
            existing_subs = await db.get_user_subscriptions(target_id)
            has_features = set()
            for sub in existing_subs:
                has_features.add(sub['feature'])
            
            new_features = set(package['features'])
            already_has = new_features & has_features
            
            if already_has:
                features_list = ', '.join(already_has)
                await update.message.reply_text(
                    f"ℹ️ У пользователя {target_id} уже есть функции: {features_list}\n\n"
                    f"Пакет {package['name']} все равно выдан, время продлено."
                )
            
            await db.add_subscription(target_id, package['features'], package['duration_days'])
            
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎁 *Поздравляем!*\n\n"
                         f"Тебе был выдан пакет *{package['name']}*!\n"
                         f"Все функции активированы и готовы к использованию! ⚡",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            await update.message.reply_text(f"✅ Пакет {package['name']} выдан пользователю {target_id}")
        else:
            await update.message.reply_text("❌ Неизвестный пакет")
    
    elif command == 'remove' and len(args) > 2:
        target_id = int(args[1])
        feature = args[2]
        await db.remove_user_feature(target_id, feature)
        await update.message.reply_text(f"✅ Функция {feature} удалена у пользователя {target_id}")
    
    elif command == 'removeall' and len(args) > 1:
        target_id = int(args[1])
        await db.remove_all_user_features(target_id)
        await update.message.reply_text(f"✅ Все функции удалены у пользователя {target_id}")
    
    elif command == 'extend' and len(args) > 3:
        target_id = int(args[1])
        feature = args[2]
        days = int(args[3])
        await db.update_subscription_expiry(target_id, feature, days)
        await update.message.reply_text(f"✅ Функция {feature} продлена на {days} дней для пользователя {target_id}")

async def main():
    try:
        if not TELEGRAM_TOKEN:
            logger.error("TELEGRAM_TOKEN не установлен! Проверьте переменные окружения.")
            return
        
        logger.info("Инициализация базы данных...")
        await db.init_db()
        await ref.init_referral_tables()
        
        logger.info("Создание приложения Telegram...")
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("admin", admin_command))
        application.add_handler(MessageHandler(filters.Regex('^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'), button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(callback_handler))
        
        logger.info("Бот запущен и готов к работе!")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    asyncio.run(main())
