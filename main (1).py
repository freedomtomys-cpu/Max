import os
import asyncio
import nest_asyncio
import uuid
import re
import logging
import json
import threading
import aiosqlite
import yt_dlp
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
from yookassa import Configuration, Payment

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
YOOKASSA_SECRET_KEY = os.getenv('YOOKASSA_SECRET_KEY', '')
YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID', '')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'MaxSaverBot')

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is required")
if not YOOKASSA_SECRET_KEY:
    raise ValueError("YOOKASSA_SECRET_KEY environment variable is required")
if not YOOKASSA_SHOP_ID:
    raise ValueError("YOOKASSA_SHOP_ID environment variable is required")

ADMIN_IDS = [6696647030, 1459753369]
FREE_DOWNLOAD_LIMIT = 55
DATABASE_FILE = 'bot_database.db'

PACKAGES = {
    'full': {
        'name': 'Full',
        'price': 149,
        'duration_days': 30,
        'features': ['4k', 'unlimited', 'mass_download']
    },
    'full_plus': {
        'name': 'Full+',
        'price': 1099,
        'duration_days': 365,
        'features': ['4k', 'unlimited', 'mass_download']
    },
    '4k_unlimited': {
        'name': '4K + Безлимит',
        'price': 99,
        'duration_days': 30,
        'features': ['4k', 'unlimited']
    },
    'mass_download': {
        'name': 'Массовая загрузка',
        'price': 75,
        'duration_days': 30,
        'features': ['mass_download']
    },
    'unlimited': {
        'name': 'Безлимит',
        'price': 75,
        'duration_days': 30,
        'features': ['unlimited']
    },
    '4k': {
        'name': '4K',
        'price': 75,
        'duration_days': 30,
        'features': ['4k']
    }
}

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

async def init_db():
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                platform TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                feature TEXT,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package_key TEXT,
                amount REAL,
                payment_id TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY,
                total_downloads INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS pending_downloads (
                download_id TEXT PRIMARY KEY,
                url TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('INSERT OR IGNORE INTO statistics (id) VALUES (1)')
        await db.commit()

async def add_user(user_id: int, username: Optional[str] = None):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username = ?',
            (user_id, username, username)
        )
        await db.commit()

async def is_user_blocked(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT is_blocked FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] == 1 if row else False

async def get_download_count_24h(user_id: int) -> int:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        time_24h_ago = datetime.now() - timedelta(hours=24)
        async with db.execute(
            'SELECT COUNT(*) FROM downloads WHERE user_id = ? AND download_time > ?',
            (user_id, time_24h_ago)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_download(user_id: int, platform: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT INTO downloads (user_id, platform) VALUES (?, ?)',
            (user_id, platform)
        )
        await db.execute(
            'UPDATE statistics SET total_downloads = total_downloads + 1 WHERE id = 1'
        )
        await db.commit()

async def get_active_features(user_id: int) -> List[str]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT DISTINCT feature FROM subscriptions WHERE user_id = ? AND expires_at > datetime("now")',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            features = []
            for row in rows:
                features.append(row[0])
            return features

async def has_feature(user_id: int, feature: str) -> bool:
    features = await get_active_features(user_id)
    return feature in features

async def get_user_subscriptions(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            '''SELECT feature, expires_at FROM subscriptions 
               WHERE user_id = ? AND expires_at > datetime("now")
               ORDER BY expires_at DESC''',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            subs = []
            for row in rows:
                subs.append({
                    'feature': row[0],
                    'expires_at': row[1]
                })
            return subs

async def add_subscription(user_id: int, features: List[str], duration_days: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        expires_at = datetime.now() + timedelta(days=duration_days)
        for feature in features:
            await db.execute(
                'INSERT INTO subscriptions (user_id, feature, expires_at) VALUES (?, ?, ?)',
                (user_id, feature, expires_at)
            )
        await db.commit()

async def create_payment_record(user_id: int, package_key: str, amount: float, payment_id: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT INTO payments (user_id, package_key, amount, payment_id, status) VALUES (?, ?, ?, ?, ?)',
            (user_id, package_key, amount, payment_id, 'pending')
        )
        await db.commit()

async def update_payment_status(payment_id: str, status: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'UPDATE payments SET status = ? WHERE payment_id = ?',
            (status, payment_id)
        )
        if status == 'succeeded':
            await db.execute(
                'UPDATE statistics SET total_revenue = total_revenue + (SELECT amount FROM payments WHERE payment_id = ?) WHERE id = 1',
                (payment_id,)
            )
        await db.commit()

async def get_payment(payment_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT user_id, package_key, amount, status FROM payments WHERE payment_id = ?',
            (payment_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'user_id': row[0],
                    'package_key': row[1],
                    'amount': row[2],
                    'status': row[3]
                }
            return None

async def get_statistics() -> Dict:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT total_downloads, total_revenue FROM statistics WHERE id = 1'
        ) as cursor:
            row = await cursor.fetchone()
            return {
                'total_downloads': row[0] if row else 0,
                'total_revenue': row[1] if row else 0
            }

async def block_user(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'UPDATE users SET is_blocked = 1 WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()

async def unblock_user(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'UPDATE users SET is_blocked = 0 WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()

async def store_pending_download(download_id: str, url: str, user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT OR REPLACE INTO pending_downloads (download_id, url, user_id) VALUES (?, ?, ?)',
            (download_id, url, user_id)
        )
        await db.commit()

async def get_pending_download(download_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT url, user_id FROM pending_downloads WHERE download_id = ?',
            (download_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'url': row[0], 'user_id': row[1]}
            return None

async def delete_pending_download(download_id: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'DELETE FROM pending_downloads WHERE download_id = ?',
            (download_id,)
        )
        await db.commit()

async def remove_user_feature(user_id: int, feature: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'DELETE FROM subscriptions WHERE user_id = ? AND feature = ?',
            (user_id, feature)
        )
        await db.commit()

async def remove_all_user_features(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'DELETE FROM subscriptions WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()

async def update_subscription_expiry(user_id: int, feature: str, new_days: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        new_expiry = datetime.now() + timedelta(days=new_days)
        await db.execute(
            'UPDATE subscriptions SET expires_at = ? WHERE user_id = ? AND feature = ?',
            (new_expiry, user_id, feature)
        )
        await db.commit()

async def get_user_info(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT username, first_seen, is_blocked FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'username': row[0],
                    'first_seen': row[1],
                    'is_blocked': row[2] == 1
                }
            return None

async def get_all_users_count() -> int:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT COUNT(*) FROM users') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_active_subscriptions_count() -> int:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE expires_at > datetime("now")'
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

def create_payment(amount: float, description: str, user_id: int) -> dict:
    try:
        idempotence_key = str(uuid.uuid4())
        
        payment = Payment.create({
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/{BOT_USERNAME}"
            },
            "capture": True,
            "description": description,
            "receipt": {
                "customer": {
                    "email": f"user{user_id}@telegram.user"
                },
                "items": [
                    {
                        "description": description,
                        "quantity": "1.00",
                        "amount": {
                            "value": str(amount),
                            "currency": "RUB"
                        },
                        "vat_code": 1
                    }
                ]
            },
            "metadata": {
                "user_id": str(user_id)
            }
        }, idempotence_key)
        
        return {
            'id': payment.id,
            'status': payment.status,
            'confirmation_url': payment.confirmation.confirmation_url,
            'amount': amount
        }
    except Exception as e:
        print(f"Error creating payment: {e}")
        return None

def check_payment_status(payment_id: str) -> dict:
    try:
        payment = Payment.find_one(payment_id)
        return {
            'status': payment.status,
            'paid': payment.paid
        }
    except Exception as e:
        print(f"Error checking payment: {e}")
        return {'status': 'error', 'paid': False}

async def extract_tiktok_info_api(url: str) -> Optional[Dict]:
    try:
        logger.info(f"Extracting TikTok info via API: {url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                'https://www.tikwm.com/api/',
                params={'url': url, 'hd': 1}
            )
            
            if response.status_code != 200:
                logger.error(f"TikWM API error: {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('code') != 0:
                logger.error(f"TikWM API returned error code: {data.get('code')}")
                return None
            
            video_data = data.get('data', {})
            
            title = video_data.get('title', 'TikTok Video')
            duration = video_data.get('duration', 0)
            thumbnail = video_data.get('cover', '')
            
            formats_list = []
            if video_data.get('hdplay'):
                formats_list.append({'quality': 'HD', 'format_id': 'hd', 'height': 1080})
            if video_data.get('play'):
                formats_list.append({'quality': 'SD', 'format_id': 'sd', 'height': 720})
            
            logger.info(f"Successfully extracted TikTok info: {title}")
            
            return {
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'platform': 'tiktok',
                'formats': formats_list,
                'url': url,
                'api_data': video_data
            }
    except Exception as e:
        logger.error(f"Error extracting TikTok info via API: {str(e)}", exc_info=True)
        return None

async def extract_video_info_async(url: str) -> Optional[Dict]:
    platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
    
    if platform == 'tiktok':
        return await extract_tiktok_info_api(url)
    
    try:
        ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'socket_timeout': 30,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }
        
        logger.info(f"Extracting info for {platform} video: {url}")
        
        def extract_sync():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_sync)
        
        formats_list = []
        if info.get('formats'):
            seen_heights = set()
            for f in info['formats']:
                height = f.get('height')
                if height and height not in seen_heights and f.get('vcodec') != 'none':
                    quality = f"{height}p"
                    formats_list.append({
                        'quality': quality,
                        'format_id': f['format_id'],
                        'height': height
                    })
                    seen_heights.add(height)
            
            formats_list.sort(key=lambda x: x['height'])
        
        thumbnail = info.get('thumbnail', '')
        title = info.get('title', 'Без названия')
        
        logger.info(f"Successfully extracted info: {title}")
        
        return {
            'title': title,
            'duration': info.get('duration', 0),
            'thumbnail': thumbnail,
            'platform': platform,
            'formats': formats_list,
            'url': url
        }
    except Exception as e:
        logger.error(f"Error extracting video info from {url}: {str(e)}", exc_info=True)
        return None

def is_valid_url(url: str) -> bool:
    pinterest_pattern = r'(https?://)?(www\.)?(pinterest\.com|pin\.it)/.+'
    tiktok_pattern = r'(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/.+'
    
    return bool(re.match(pinterest_pattern, url)) or bool(re.match(tiktok_pattern, url))

def extract_urls(text: str) -> List[str]:
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    return [url for url in urls if is_valid_url(url)]

async def download_tiktok_via_api(url: str, quality: Optional[str] = None, audio_only: bool = False) -> Optional[str]:
    try:
        logger.info(f"Downloading TikTok via API: {url}, quality={quality}, audio_only={audio_only}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                'https://www.tikwm.com/api/',
                params={'url': url, 'hd': 1}
            )
            
            if response.status_code != 200:
                logger.error(f"TikWM API error: {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('code') != 0:
                logger.error(f"TikWM API returned error code: {data.get('code')}")
                return None
            
            video_data = data.get('data', {})
            
            if audio_only:
                download_url = video_data.get('music')
                if not download_url:
                    logger.error("No audio URL found in API response")
                    return None
                file_ext = 'mp3'
            else:
                if quality == 'sd':
                    download_url = video_data.get('play')
                    logger.info("Using SD quality (user requested)")
                elif quality == 'hd' or quality is None:
                    download_url = video_data.get('hdplay') or video_data.get('play')
                    logger.info(f"Using HD quality (available: {bool(video_data.get('hdplay'))})")
                else:
                    download_url = video_data.get('hdplay') or video_data.get('play')
                
                if not download_url:
                    logger.error("No video URL found in API response")
                    return None
                file_ext = 'mp4'
            
            os.makedirs('downloads', exist_ok=True)
            
            video_id = re.search(r'/video/(\d+)', url)
            if video_id:
                filename = f"downloads/{video_id.group(1)}.{file_ext}"
            else:
                import hashlib
                filename = f"downloads/{hashlib.md5(url.encode()).hexdigest()}.{file_ext}"
            
            logger.info(f"Downloading from: {download_url[:100]}...")
            
            video_response = await client.get(download_url)
            
            if video_response.status_code != 200:
                logger.error(f"Failed to download file: {video_response.status_code}")
                return None
            
            with open(filename, 'wb') as f:
                f.write(video_response.content)
            
            file_size = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"Successfully downloaded: {filename} ({file_size:.2f} MB)")
            
            return filename
            
    except Exception as e:
        logger.error(f"Error downloading TikTok via API: {str(e)}", exc_info=True)
        return None

async def download_video(url: str, quality: Optional[str] = None, audio_only: bool = False) -> Optional[str]:
    try:
        platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
        
        logger.info(f"Starting download from {platform}: {url}, quality={quality}, audio_only={audio_only}")
        
        if platform == 'tiktok':
            return await download_tiktok_via_api(url, quality, audio_only)
        
        base_opts = {
            'quiet': False,
            'no_warnings': False,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }
        
        if audio_only:
            ydl_opts = {
                **base_opts,
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            if quality:
                height = quality.replace('p', '')
                ydl_opts = {
                    **base_opts,
                    'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                    'outtmpl': 'downloads/%(id)s.%(ext)s',
                    'merge_output_format': 'mp4',
                }
            else:
                ydl_opts = {
                    **base_opts,
                    'format': 'best',
                    'outtmpl': 'downloads/%(id)s.%(ext)s',
                }
        
        os.makedirs('downloads', exist_ok=True)
        
        def download_sync():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if audio_only:
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                
                return filename
        
        loop = asyncio.get_event_loop()
        filename = await loop.run_in_executor(None, download_sync)
        
        if filename and os.path.exists(filename):
            file_size = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"Successfully downloaded: {filename} ({file_size:.2f} MB)")
            return filename
        else:
            logger.error(f"Download failed: file not found")
            return None
            
    except Exception as e:
        logger.error(f"Error downloading video from {url}: {str(e)}", exc_info=True)
        return None

def format_duration(seconds) -> str:
    if seconds is None:
        return "Неизвестно"
    
    seconds = int(seconds)
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def delete_message_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 20):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_user(user.id, user.username)
    
    if await is_user_blocked(user.id):
        return
    
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
    
    await update.message.reply_text(
        "⚡ *Привет! Я — MaxSaver* ⚡\n\n"
        "Скачиваю видео и изображения из *TikTok* и *Pinterest* без водяных знаков:\n"
        "✅ Быстро и качественно\n"
        "✅ Поддержка до 4K\n"
        "✅ Скачивание аудио в MP3\n\n"
        "📲 *Просто отправь ссылку* — и получишь готовый файл!",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if await is_user_blocked(user.id):
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
        has_mass = await has_feature(user.id, 'mass_download')
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
    subs = await get_user_subscriptions(user.id)
    
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
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if await is_user_blocked(user.id):
        return
    
    if user.id in ADMIN_IDS and 'admin_action' in context.user_data:
        action = context.user_data.pop('admin_action')
        parts = text.strip().split()
        
        try:
            if action == 'user_info' and len(parts) >= 1:
                target_id = int(parts[0])
                user_info = await get_user_info(target_id)
                if user_info:
                    subs = await get_user_subscriptions(target_id)
                    blocked_status = "🚫 Заблокирован" if user_info['is_blocked'] else "✅ Активен"
                    username = f"@{user_info['username']}" if user_info['username'] else "Не указан"
                    
                    info_text = f"👤 *Информация о пользователе:*\n\n"
                    info_text += f"ID: `{target_id}`\n"
                    info_text += f"Ник: {escape_markdown(username)}\n"
                    info_text += f"Статус: {blocked_status}\n"
                    info_text += f"Первое посещение: {user_info['first_seen']}\n\n"
                    
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
                await block_user(target_id)
                await update.message.reply_text(f"🚫 Пользователь {target_id} заблокирован")
                return
            
            elif action == 'unblock' and len(parts) >= 1:
                target_id = int(parts[0])
                await unblock_user(target_id)
                await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован")
                return
            
            elif action == 'give_package' and len(parts) >= 2:
                target_id = int(parts[0])
                package_key = parts[1]
                package = PACKAGES.get(package_key)
                
                if package:
                    await add_subscription(target_id, package['features'], package['duration_days'])
                    await update.message.reply_text(f"✅ Пакет {package['name']} выдан пользователю {target_id}")
                else:
                    await update.message.reply_text("❌ Неизвестный пакет")
                return
            
            elif action == 'remove_feature' and len(parts) >= 2:
                target_id = int(parts[0])
                feature = parts[1]
                await remove_user_feature(target_id, feature)
                await update.message.reply_text(f"✅ Функция {feature} удалена у пользователя {target_id}")
                return
            
            elif action == 'removeall' and len(parts) >= 1:
                target_id = int(parts[0])
                await remove_all_user_features(target_id)
                await update.message.reply_text(f"✅ Все функции удалены у пользователя {target_id}")
                return
            
            elif action == 'extend' and len(parts) >= 3:
                target_id = int(parts[0])
                feature = parts[1]
                days = int(parts[2])
                await update_subscription_expiry(target_id, feature, days)
                await update.message.reply_text(f"✅ Функция {feature} продлена на {days} дней для пользователя {target_id}")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат данных. Попробуй снова.")
            return
    
    urls = extract_urls(text)
    
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
    
    has_mass = await has_feature(user.id, 'mass_download')
    
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
        status_msg = await update.message.reply_text(
            f"📦 *Массовая загрузка*\n\n"
            f"Найдено видео: *{len(urls)}*\n"
            f"Обработано: 0/{len(urls)}\n\n"
            f"⏳ Начинаем загрузку...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        for idx, url in enumerate(urls, 1):
            await status_msg.edit_text(
                f"📦 *Массовая загрузка*\n\n"
                f"Найдено видео: *{len(urls)}*\n"
                f"Обработано: {idx}/{len(urls)}\n\n"
                f"⏳ Загружаю видео {idx}...",
                parse_mode=ParseMode.MARKDOWN
            )
            await process_video_url(update, context, url)
        
        await status_msg.edit_text(
            f"✅ *Массовая загрузка завершена!*\n\n"
            f"Всего загружено: *{len(urls)} видео*\n\n"
            f"Все файлы отправлены выше 👆",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(delete_message_later(context, update.effective_chat.id, status_msg.message_id, 30))
    else:
        for url in urls:
            await process_video_url(update, context, url)

async def process_video_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user = update.effective_user
    
    if not is_valid_url(url):
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
    
    info = await extract_video_info_async(url)
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
    
    has_unlimited = await has_feature(user.id, 'unlimited')
    if not has_unlimited:
        download_count = await get_download_count_24h(user.id)
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
    await store_pending_download(download_id, url, user.id)
    
    keyboard = []
    has_4k = await has_feature(user.id, '4k')
    
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
                if has_4k:
                    keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality} 💎", callback_data=f"dl_{quality}_{download_id}")])
                else:
                    keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality} 🔒", callback_data=f"need_4k")])
            else:
                keyboard.append([InlineKeyboardButton(f"🎥 Видео {quality}", callback_data=f"dl_{quality}_{download_id}")])
        
        keyboard.append([InlineKeyboardButton("🎧 Аудио (MP3)", callback_data=f"dl_audio_{download_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    duration_str = format_duration(info['duration']) if info['duration'] else "Неизвестно"
    
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
    
    if await is_user_blocked(user.id):
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
            
            payment_info = create_payment(
                package['price'],
                f"{package['name']} - {user.id}",
                user.id
            )
            
            if payment_info:
                await create_payment_record(user.id, package_key, package['price'], payment_info['id'])
                
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
    
    elif data.startswith('check_'):
        payment_id = data.replace('check_', '')
        payment_info = check_payment_status(payment_id)
        status = payment_info['status']
        paid = payment_info['paid']
        
        await query.answer()
        
        if status == 'succeeded' and paid:
            payment_data = await get_payment(payment_id)
            if payment_data and payment_data['status'] != 'succeeded':
                package_key = payment_data['package_key']
                package = PACKAGES.get(package_key)
                
                if package:
                    await add_subscription(user.id, package['features'], package['duration_days'])
                    await update_payment_status(payment_id, 'succeeded')
                    
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
        await query.answer("⚠️ 4K доступно только для платных пользователей.\nПодключи пакет 💎4K или Full.", show_alert=True)
    
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
        pending = await get_pending_download(download_id)
        
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
        
        await delete_pending_download(download_id)
        
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
                filename = await download_video(url, quality, audio_only)
                
                if filename and os.path.exists(filename):
                    file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                    logger.info(f"Downloaded file size: {file_size_mb:.2f} MB")
                    
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
                    await add_download(user.id, platform)
                    
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
                            logger.info(f"Отправка большого видео как документ ({file_size_mb:.1f} MB)...")
                            
                            if file_size_mb > 500:
                                await loading_msg.edit_text(
                                    f"📤 *Отправка файла ({file_size_mb:.1f} MB)*\n\n"
                                    f"⏳ Это может занять несколько минут\n"
                                    f"Пожалуйста, не закрывайте чат...",
                                    parse_mode=ParseMode.MARKDOWN
                                )
                            
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
        if data == 'admin_stats':
            stats = await get_statistics()
            users_count = await get_all_users_count()
            active_subs = await get_active_subscriptions_count()
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
    
    await show_admin_panel(update, context)

app = Flask(__name__)
application_bot = None
loop = None
init_complete = False

def run_async_loop(loop_param):
    asyncio.set_event_loop(loop_param)
    loop_param.run_forever()

async def initialize_bot():
    global application_bot, init_complete
    await init_db()
    application_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    await application_bot.initialize()
    
    application_bot.add_handler(CommandHandler("start", start))
    application_bot.add_handler(CommandHandler("admin", admin_command))
    application_bot.add_handler(MessageHandler(filters.Regex(
        '^(📌 Pinterest|🎵 TikTok|📦 Массовая загрузка|💎 Plus\+|👤 My Account|🔧 Admin Panel)$'
    ), button_handler))
    application_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application_bot.add_handler(CallbackQueryHandler(callback_handler))
    
    await application_bot.start()
    
    init_complete = True
    print("Bot initialized and started successfully!")

def init_flask_app():
    global loop, application_bot
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=run_async_loop, args=(loop,), daemon=True)
    thread.start()
    asyncio.run_coroutine_threadsafe(initialize_bot(), loop).result(timeout=30)

init_flask_app()

@app.route('/')
def index():
    status = "initialized" if init_complete else "initializing"
    return f'MaxSaver Bot is running on Scalingo! Status: {status}'

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if not init_complete or not application_bot or not loop:
        return jsonify({'status': 'bot not ready'}), 503
    
    json_str = request.get_data().decode('UTF-8')
    json_data = json.loads(json_str)
    update = Update.de_json(json_data, application_bot.bot)
    asyncio.run_coroutine_threadsafe(application_bot.process_update(update), loop)
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
