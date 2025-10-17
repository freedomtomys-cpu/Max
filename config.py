import os

def load_keys():
    keys = {}
    keys_file = os.path.join(os.path.dirname(__file__), 'keys')
    try:
        with open(keys_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ' - ' in line:
                    key, value = line.split(' - ', 1)
                    keys[key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"⚠️ Файл {keys_file} не найден! Используются переменные окружения.")
        return {
            'TOKEN': os.getenv('TELEGRAM_TOKEN'),
            'Kassa': os.getenv('YOOKASSA_SECRET_KEY'),
            'IdKassa': os.getenv('YOOKASSA_SHOP_ID')
        }
    return keys

_keys = load_keys()

TELEGRAM_TOKEN = _keys.get('TOKEN')
YOOKASSA_SECRET_KEY = _keys.get('Kassa')
YOOKASSA_SHOP_ID = _keys.get('IdKassa')
BOT_USERNAME = _keys.get('BOT_USERNAME', 'MaxSaverBot')

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
