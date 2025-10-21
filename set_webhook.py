import requests
import sys
import os
from config import TELEGRAM_TOKEN

def set_webhook(webhook_url):
    """
    Устанавливает webhook для Telegram бота
    
    Args:
        webhook_url: URL вашего сервиса на Render (например: https://your-app.onrender.com)
    """
    # Формируем полный URL для webhook
    full_webhook_url = f"{webhook_url}/{TELEGRAM_TOKEN}"
    
    # Устанавливаем webhook через Telegram API
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    
    print(f"Устанавливаем webhook: {full_webhook_url}")
    
    response = requests.post(api_url, json={
        'url': full_webhook_url,
        'allowed_updates': ['message', 'callback_query']
    })
    
    result = response.json()
    
    if result.get('ok'):
        print("✅ Webhook успешно установлен!")
        print(f"URL: {full_webhook_url}")
        
        # Проверяем информацию о webhook
        info_response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo")
        info = info_response.json()
        
        if info.get('ok'):
            webhook_info = info.get('result', {})
            print("\nИнформация о webhook:")
            print(f"URL: {webhook_info.get('url')}")
            print(f"Pending updates: {webhook_info.get('pending_update_count', 0)}")
            if webhook_info.get('last_error_message'):
                print(f"⚠️ Последняя ошибка: {webhook_info.get('last_error_message')}")
    else:
        print("❌ Ошибка при установке webhook:")
        print(result)
        sys.exit(1)

def delete_webhook():
    """Удаляет webhook (переводит бота в режим polling)"""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
    response = requests.get(api_url)
    result = response.json()
    
    if result.get('ok'):
        print("✅ Webhook удален! Бот переведен в режим polling.")
    else:
        print("❌ Ошибка при удалении webhook:")
        print(result)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование:")
        print("  Установить webhook: python set_webhook.py https://your-app.onrender.com")
        print("  Удалить webhook:    python set_webhook.py delete")
        sys.exit(1)
    
    if sys.argv[1] == 'delete':
        delete_webhook()
    else:
        webhook_url = sys.argv[1].rstrip('/')
        set_webhook(webhook_url)
