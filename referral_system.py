import aiosqlite
from datetime import datetime
from typing import Optional, Dict, List
import random
import string

DATABASE_FILE = 'bot_database.db'

async def init_referral_tables():
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                user_id INTEGER PRIMARY KEY,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                coins_balance INTEGER DEFAULT 0,
                total_earned_coins INTEGER DEFAULT 0,
                total_referrals INTEGER DEFAULT 0,
                total_spent_coins INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referred_by) REFERENCES referrals (user_id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS coin_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                transaction_type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES referrals (user_id)
            )
        ''')
        
        await db.commit()

def generate_referral_code() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

async def create_referral_account(user_id: int, referred_by: Optional[int] = None):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT user_id FROM referrals WHERE user_id = ?', (user_id,)) as cursor:
            existing = await cursor.fetchone()
            if existing:
                return
        
        referral_code = generate_referral_code()
        
        while True:
            async with db.execute('SELECT user_id FROM referrals WHERE referral_code = ?', (referral_code,)) as cursor:
                exists = await cursor.fetchone()
                if not exists:
                    break
            referral_code = generate_referral_code()
        
        initial_coins = 10 if referred_by else 0
        
        await db.execute('''
            INSERT INTO referrals (user_id, referral_code, referred_by, coins_balance, total_earned_coins)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, referral_code, referred_by, initial_coins, initial_coins))
        
        if initial_coins > 0:
            await db.execute('''
                INSERT INTO coin_transactions (user_id, amount, transaction_type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, initial_coins, 'bonus', 'Бонус за регистрацию по реферальной ссылке'))
        
        if referred_by:
            await db.execute('''
                UPDATE referrals 
                SET total_referrals = total_referrals + 1,
                    coins_balance = coins_balance + 20,
                    total_earned_coins = total_earned_coins + 20
                WHERE user_id = ?
            ''', (referred_by,))
            
            await db.execute('''
                INSERT INTO coin_transactions (user_id, amount, transaction_type, description)
                VALUES (?, ?, ?, ?)
            ''', (referred_by, 20, 'referral', f'Приглашение пользователя {user_id}'))
        
        await db.commit()

async def get_referral_info(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT referral_code, coins_balance, total_earned_coins, total_referrals, total_spent_coins, referred_by
            FROM referrals WHERE user_id = ?
        ''', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                async with db.execute('''
                    SELECT SUM(amount) FROM coin_transactions 
                    WHERE user_id = ? AND transaction_type = 'referral_download'
                ''', (user_id,)) as cursor2:
                    row2 = await cursor2.fetchone()
                    earned_from_referrals = row2[0] if row2 and row2[0] else 0
                
                return {
                    'referral_code': row[0],
                    'coins_balance': row[1],
                    'total_earned_coins': row[2],
                    'total_referrals': row[3],
                    'total_spent_coins': row[4],
                    'referred_by': row[5],
                    'earned_from_referrals': earned_from_referrals
                }
            return None

async def add_coins(user_id: int, amount: float, transaction_type: str, description: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
            UPDATE referrals 
            SET coins_balance = coins_balance + ?,
                total_earned_coins = total_earned_coins + ?
            WHERE user_id = ?
        ''', (amount, amount, user_id))
        
        await db.execute('''
            INSERT INTO coin_transactions (user_id, amount, transaction_type, description)
            VALUES (?, ?, ?, ?)
        ''', (user_id, amount, transaction_type, description))
        
        await db.commit()

async def spend_coins(user_id: int, amount: int, description: str) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT coins_balance FROM referrals WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                return False
        
        await db.execute('''
            UPDATE referrals 
            SET coins_balance = coins_balance - ?,
                total_spent_coins = total_spent_coins + ?
            WHERE user_id = ?
        ''', (amount, amount, user_id))
        
        await db.execute('''
            INSERT INTO coin_transactions (user_id, amount, transaction_type, description)
            VALUES (?, ?, ?, ?)
        ''', (user_id, -amount, 'purchase', description))
        
        await db.commit()
        return True

async def get_referrer_id(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT referred_by FROM referrals WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else None

async def get_user_by_referral_code(referral_code: str) -> Optional[int]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT user_id FROM referrals WHERE referral_code = ?', (referral_code,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def process_download_coins(user_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await add_coins(user_id, 1, 'download', 'Вознаграждение за скачивание видео')
        
        referrer_id = await get_referrer_id(user_id)
        if referrer_id:
            await add_coins(referrer_id, 0.5, 'referral_download', f'Скачивание видео рефералом {user_id}')

async def get_transaction_history(user_id: int, limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT amount, transaction_type, description, created_at
            FROM coin_transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [{
                'amount': row[0],
                'type': row[1],
                'description': row[2],
                'created_at': row[3]
            } for row in rows]
