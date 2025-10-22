import os
import sys

def get_env_var(name, default='', required=False):
    value = os.getenv(name, default)
    
    if required and not value:
        error_msg = f"❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения {name} не установлена!"
        print(error_msg, file=sys.stderr)
        print(f"Проверьте настройки в Render.com -> Environment Variables", file=sys.stderr)
        raise ValueError(error_msg)
    
    if value:
        print(f"✅ {name} успешно загружена (длина: {len(value)} символов)")
    else:
        print(f"⚠️ {name} не установлена, используется значение по умолчанию")
    
    return value

print("=" * 50)
print("ЗАГРУЗКА КОНФИГУРАЦИИ...")
print("=" * 50)

TELEGRAM_TOKEN = get_env_var('TELEGRAM_TOKEN', required=True)
YOOKASSA_SECRET_KEY = get_env_var('YOOKASSA_SECRET_KEY', required=True)
YOOKASSA_SHOP_ID = get_env_var('YOOKASSA_SHOP_ID', required=True)
BOT_USERNAME = get_env_var('BOT_USERNAME', default='MaxSaverBot')

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

print("=" * 50)
print("✅ КОНФИГУРАЦИЯ УСПЕШНО ЗАГРУЖЕНА")
print("=" * 50)
