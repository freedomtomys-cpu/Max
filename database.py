import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json

DATABASE_FILE = 'bot_database.db'

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
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                admin_id INTEGER PRIMARY KEY,
                session_active INTEGER DEFAULT 0,
                auth_step INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS push_messages (
                id TEXT PRIMARY KEY,
                text TEXT,
                lifetime INTEGER,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS sponsors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT,
                position INTEGER,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS push_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                push_id TEXT,
                user_id INTEGER,
                message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (push_id) REFERENCES push_messages (id)
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

async def create_payment(user_id: int, package_key: str, amount: float, payment_id: str):
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

async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT user_id FROM users') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def create_push_message(message_id: str, text: str, lifetime: int) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        try:
            await db.execute(
                'INSERT INTO push_messages (id, text, lifetime) VALUES (?, ?, ?)',
                (message_id, text, lifetime)
            )
            await db.commit()
            return True
        except:
            return False

async def save_push_recipient(push_id: str, user_id: int, message_id: int):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT INTO push_recipients (push_id, user_id, message_id) VALUES (?, ?, ?)',
            (push_id, user_id, message_id)
        )
        await db.commit()

async def get_push_recipients(push_id: str) -> List[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT user_id, message_id FROM push_recipients WHERE push_id = ?',
            (push_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{'user_id': row[0], 'message_id': row[1]} for row in rows]

async def delete_push_message(message_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'UPDATE push_messages SET active = 0 WHERE id = ?',
            (message_id,)
        )
        await db.execute(
            'DELETE FROM push_recipients WHERE push_id = ?',
            (message_id,)
        )
        await db.commit()
        return True

async def get_push_message(message_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT id, text, lifetime, created_at FROM push_messages WHERE id = ? AND active = 1',
            (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'text': row[1],
                    'lifetime': row[2],
                    'created_at': row[3]
                }
            return None

async def get_active_push_messages() -> List[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT id, text, lifetime, created_at FROM push_messages WHERE active = 1'
        ) as cursor:
            rows = await cursor.fetchall()
            return [{
                'id': row[0],
                'text': row[1],
                'lifetime': row[2],
                'created_at': row[3]
            } for row in rows]

async def add_sponsor(link: str) -> int:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT MAX(position) FROM sponsors WHERE active = 1') as cursor:
            row = await cursor.fetchone()
            next_position = (row[0] + 1) if row and row[0] else 1
        
        cursor = await db.execute(
            'INSERT INTO sponsors (link, position) VALUES (?, ?)',
            (link, next_position)
        )
        await db.commit()
        return cursor.lastrowid

async def get_active_sponsors() -> List[Dict]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute(
            'SELECT id, link, position FROM sponsors WHERE active = 1 ORDER BY position'
        ) as cursor:
            rows = await cursor.fetchall()
            return [{
                'id': row[0],
                'link': row[1],
                'position': row[2]
            } for row in rows]

async def delete_sponsor(sponsor_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'UPDATE sponsors SET active = 0 WHERE id = ?',
            (sponsor_id,)
        )
        
        sponsors = await get_active_sponsors()
        for idx, sponsor in enumerate(sponsors, 1):
            await db.execute(
                'UPDATE sponsors SET position = ? WHERE id = ?',
                (idx, sponsor['id'])
            )
        
        await db.commit()
        return True

async def delete_all_sponsors() -> bool:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('UPDATE sponsors SET active = 0')
        await db.commit()
        return True

async def store_user_subscription_check(user_id: int, checked_sponsors: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT OR REPLACE INTO users (user_id, username) VALUES (?, (SELECT username FROM users WHERE user_id = ?))',
            (user_id, user_id)
        )
        await db.commit()

async def check_user_subscribed_sponsors(user_id: int) -> bool:
    return True

