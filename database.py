import os
import asyncpg
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_blocked INTEGER DEFAULT 0
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            platform TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            feature TEXT,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            package_key TEXT,
            amount REAL,
            payment_id TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS statistics (
            id SERIAL PRIMARY KEY,
            total_downloads INTEGER DEFAULT 0,
            total_revenue REAL DEFAULT 0
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS pending_downloads (
            download_id TEXT PRIMARY KEY,
            url TEXT,
            user_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS admin_sessions (
            admin_id BIGINT PRIMARY KEY,
            session_active INTEGER DEFAULT 0,
            auth_step INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS push_messages (
            id TEXT PRIMARY KEY,
            text TEXT,
            lifetime INTEGER,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS sponsors (
            id SERIAL PRIMARY KEY,
            link TEXT,
            position INTEGER,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS sponsor_checks (
            user_id BIGINT PRIMARY KEY,
            checked_sponsors_ids TEXT,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS push_recipients (
            id SERIAL PRIMARY KEY,
            push_id TEXT,
            user_id BIGINT,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (push_id) REFERENCES push_messages (id)
        )
    ''')
    await conn.execute('INSERT INTO statistics (id) VALUES (1) ON CONFLICT (id) DO NOTHING')
    await conn.close()

# универсальная функция подключения
def db():
    return asyncpg.connect(DATABASE_URL)

async def add_user(user_id: int, username: Optional[str] = None):
    conn = await db()
    await conn.execute('''INSERT INTO users (user_id, username) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username''', user_id, username)
    await conn.close()

async def is_user_blocked(user_id: int) -> bool:
    conn = await db()
    row = await conn.fetchrow('SELECT is_blocked FROM users WHERE user_id=$1', user_id)
    await conn.close()
    return row and row['is_blocked'] == 1

async def get_download_count_24h(user_id: int) -> int:
    conn = await db()
    time_24h_ago = datetime.now() - timedelta(hours=24)
    row = await conn.fetchrow('SELECT COUNT(*) AS c FROM downloads WHERE user_id=$1 AND download_time > $2', user_id, time_24h_ago)
    await conn.close()
    return row['c'] if row else 0

async def add_download(user_id: int, platform: str):
    conn = await db()
    await conn.execute('INSERT INTO downloads (user_id, platform) VALUES ($1,$2)', user_id, platform)
    await conn.execute('UPDATE statistics SET total_downloads=total_downloads+1 WHERE id=1')
    await conn.close()

async def get_active_features(user_id: int) -> List[str]:
    conn = await db()
    rows = await conn.fetch('SELECT DISTINCT feature FROM subscriptions WHERE user_id=$1 AND expires_at>NOW()', user_id)
    await conn.close()
    return [r['feature'] for r in rows]

async def has_feature(user_id: int, feature: str) -> bool:
    return feature in await get_active_features(user_id)

async def get_user_subscriptions(user_id: int) -> List[Dict]:
    conn = await db()
    rows = await conn.fetch('SELECT feature, expires_at FROM subscriptions WHERE user_id=$1 AND expires_at>NOW() ORDER BY expires_at DESC', user_id)
    await conn.close()
    return [{'feature':r['feature'],'expires_at':r['expires_at']} for r in rows]

async def add_subscription(user_id: int, features: List[str], duration_days: int):
    conn = await db()
    expires_at = datetime.now() + timedelta(days=duration_days)
    for f in features:
        await conn.execute('INSERT INTO subscriptions (user_id, feature, expires_at) VALUES ($1,$2,$3)', user_id, f, expires_at)
    await conn.close()

async def create_payment(user_id: int, package_key: str, amount: float, payment_id: str):
    conn = await db()
    await conn.execute('INSERT INTO payments (user_id, package_key, amount, payment_id, status) VALUES ($1,$2,$3,$4,$5)', user_id, package_key, amount, payment_id, 'pending')
    await conn.close()

async def update_payment_status(payment_id: str, status: str):
    conn = await db()
    await conn.execute('UPDATE payments SET status=$1 WHERE payment_id=$2', status, payment_id)
    if status=='succeeded':
        await conn.execute('UPDATE statistics SET total_revenue=total_revenue+(SELECT amount FROM payments WHERE payment_id=$1) WHERE id=1', payment_id)
    await conn.close()

async def get_payment(payment_id: str) -> Optional[Dict]:
    conn = await db()
    row = await conn.fetchrow('SELECT user_id,package_key,amount,status FROM payments WHERE payment_id=$1', payment_id)
    await conn.close()
    if not row: return None
    return dict(row)

async def get_statistics() -> Dict:
    conn = await db()
    row = await conn.fetchrow('SELECT total_downloads,total_revenue FROM statistics WHERE id=1')
    await conn.close()
    return {'total_downloads': row['total_downloads'] if row else 0, 'total_revenue': row['total_revenue'] if row else 0}

async def block_user(user_id:int):
    conn = await db()
    await conn.execute('UPDATE users SET is_blocked=1 WHERE user_id=$1', user_id)
    await conn.close()

async def unblock_user(user_id:int):
    conn = await db()
    await conn.execute('UPDATE users SET is_blocked=0 WHERE user_id=$1', user_id)
    await conn.close()

async def store_pending_download(download_id:str,url:str,user_id:int):
    conn = await db()
    await conn.execute('INSERT INTO pending_downloads(download_id,url,user_id) VALUES($1,$2,$3) ON CONFLICT(download_id) DO UPDATE SET url=EXCLUDED.url,user_id=EXCLUDED.user_id',download_id,url,user_id)
    await conn.close()

async def get_pending_download(download_id:str)->Optional[Dict]:
    conn = await db()
    row = await conn.fetchrow('SELECT url,user_id FROM pending_downloads WHERE download_id=$1',download_id)
    await conn.close()
    return dict(row) if row else None

async def delete_pending_download(download_id:str):
    conn = await db()
    await conn.execute('DELETE FROM pending_downloads WHERE download_id=$1',download_id)
    await conn.close()

async def remove_user_feature(user_id:int,feature:str):
    conn = await db()
    await conn.execute('DELETE FROM subscriptions WHERE user_id=$1 AND feature=$2',user_id,feature)
    await conn.close()

async def remove_all_user_features(user_id:int):
    conn = await db()
    await conn.execute('DELETE FROM subscriptions WHERE user_id=$1',user_id)
    await conn.close()

async def update_subscription_expiry(user_id:int,feature:str,new_days:int):
    conn = await db()
    new_expiry=datetime.now()+timedelta(days=new_days)
    await conn.execute('UPDATE subscriptions SET expires_at=$1 WHERE user_id=$2 AND feature=$3',new_expiry,user_id,feature)
    await conn.close()

async def get_user_info(user_id:int)->Optional[Dict]:
    conn = await db()
    row=await conn.fetchrow('SELECT username,first_seen,is_blocked FROM users WHERE user_id=$1',user_id)
    await conn.close()
    return {'username':row['username'],'first_seen':row['first_seen'],'is_blocked':row['is_blocked']==1} if row else None

async def get_all_users_count()->int:
    conn=await db()
    row=await conn.fetchrow('SELECT COUNT(*) AS c FROM users')
    await conn.close()
    return row['c'] if row else 0

async def get_active_subscriptions_count()->int:
    conn=await db()
    row=await conn.fetchrow('SELECT COUNT(DISTINCT user_id) AS c FROM subscriptions WHERE expires_at>NOW()')
    await conn.close()
    return row['c'] if row else 0

async def get_all_user_ids()->List[int]:
    conn=await db()
    rows=await conn.fetch('SELECT user_id FROM users')
    await conn.close()
    return [r['user_id'] for r in rows]

async def create_push_message(message_id:str,text:str,lifetime:int)->bool:
    try:
        conn=await db()
        await conn.execute('INSERT INTO push_messages(id,text,lifetime) VALUES($1,$2,$3)',message_id,text,lifetime)
        await conn.close()
        return True
    except:
        return False

async def save_push_recipient(push_id:str,user_id:int,message_id:int):
    conn=await db()
    await conn.execute('INSERT INTO push_recipients(push_id,user_id,message_id) VALUES($1,$2,$3)',push_id,user_id,message_id)
    await conn.close()

async def get_push_recipients(push_id:str)->List[Dict]:
    conn=await db()
    rows=await conn.fetch('SELECT user_id,message_id FROM push_recipients WHERE push_id=$1',push_id)
    await conn.close()
    return [{'user_id':r['user_id'],'message_id':r['message_id']} for r in rows]

async def delete_push_message(message_id:str)->bool:
    conn=await db()
    await conn.execute('UPDATE push_messages SET active=0 WHERE id=$1',message_id)
    await conn.execute('DELETE FROM push_recipients WHERE push_id=$1',message_id)
    await conn.close()
    return True

async def get_push_message(message_id:str)->Optional[Dict]:
    conn=await db()
    row=await conn.fetchrow('SELECT id,text,lifetime,created_at FROM push_messages WHERE id=$1 AND active=1',message_id)
    await conn.close()
    return dict(row) if row else None

async def get_active_push_messages()->List[Dict]:
    conn=await db()
    rows=await conn.fetch('SELECT id,text,lifetime,created_at FROM push_messages WHERE active=1')
    await conn.close()
    return [dict(r) for r in rows]

async def add_sponsor(link:str)->int:
    conn=await db()
    row=await conn.fetchrow('SELECT MAX(position) AS m FROM sponsors WHERE active=1')
    next_pos=(row['m']+1) if row and row['m'] else 1
    new_row=await conn.fetchrow('INSERT INTO sponsors(link,position) VALUES($1,$2) RETURNING id',link,next_pos)
    await conn.close()
    return new_row['id']

async def get_active_sponsors()->List[Dict]:
    conn=await db()
    rows=await conn.fetch('SELECT id,link,position FROM sponsors WHERE active=1 ORDER BY position')
    await conn.close()
    return [dict(r) for r in rows]

async def delete_sponsor(sponsor_id:int)->bool:
    conn=await db()
    await conn.execute('UPDATE sponsors SET active=0 WHERE id=$1',sponsor_id)
    sponsors=await conn.fetch('SELECT id FROM sponsors WHERE active=1 ORDER BY position')
    for idx,s in enumerate(sponsors,1):
        await conn.execute('UPDATE sponsors SET position=$1 WHERE id=$2',idx,s['id'])
    await conn.close()
    return True

async def delete_all_sponsors()->bool:
    conn=await db()
    await conn.execute('UPDATE sponsors SET active=0')
    await conn.close()
    return True

async def store_user_subscription_check(user_id:int,checked_sponsors:str):
    conn=await db()
    await conn.execute('INSERT INTO sponsor_checks(user_id,checked_sponsors_ids,checked_at) VALUES($1,$2,NOW()) ON CONFLICT(user_id) DO UPDATE SET checked_sponsors_ids=EXCLUDED.checked_sponsors_ids,checked_at=NOW()',user_id,checked_sponsors)
    await conn.close()

async def check_user_subscribed_sponsors(user_id:int)->Optional[str]:
    conn=await db()
    row=await conn.fetchrow('SELECT checked_sponsors_ids FROM sponsor_checks WHERE user_id=$1',user_id)
    await conn.close()
    return row['checked_sponsors_ids'] if row else None
