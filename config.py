import os

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
