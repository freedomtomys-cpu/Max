import requests
import sys

# Вставь сюда токен от BotFather
TELEGRAM_TOKEN = "8385014294:AAFhEOK0OLuvuhIk1tWR3kctxwnI1EYFm7Q"

def set_webhook(webhook_url):
    full_webhook_url = f"{webhook_url}/{TELEGRAM_TOKEN}"
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
            print(f"Pending updates: {webhook_info.get('pending_update_count', 0)}")
            if webhook_info.get('last_error_message'):
                print(f"⚠️ Последняя ошибка: {webhook_info.get('last_error_message')}")
    else:
        print("❌ Ошибка при установке webhook:")
        print(result)
        sys.exit(1)

def delete_webhook():
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
    response = requests.get(api_url)
    result = response.json()
    if result.get('ok'):
        print("✅ Webhook удален!")
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
