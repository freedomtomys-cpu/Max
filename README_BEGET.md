# MaxSaver Telegram Bot - Инструкция для Beget

## 📋 Что это?
Telegram-бот для скачивания видео из TikTok и Pinterest с интеграцией платежей YooKassa.

## 🚀 Установка на Beget

### 1. Загрузка файлов
Загрузите все файлы из папки `bot/` на ваш хостинг Beget в нужную директорию.

### 2. Настройка виртуального окружения
Подключитесь к серверу через SSH и выполните:

```bash
cd /home/USERNAME/YOURDOMAIN/bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Создание файла с ключами
Создайте файл `keys` в корне папки `bot/` со следующим содержимым:

```
TOKEN - ВАШ_TELEGRAM_BOT_TOKEN
Kassa - ВАШ_YOOKASSA_SECRET_KEY
IdKassa - ВАШ_YOOKASSA_SHOP_ID
BOT_USERNAME - ВАШ_БОТ_USERNAME
```

### 4. Настройка .htaccess
Откройте файл `.htaccess` и замените:
- `USERNAME` - на ваш логин на Beget
- `YOURDOMAIN` - на название вашего домена

Чтобы узнать путь к Python, выполните в SSH:
```bash
which python3
```

### 5. Настройка webhook
После загрузки файлов, откройте в браузере:
```
https://YOURDOMAIN/set_webhook?url=https://YOURDOMAIN
```

Замените `YOURDOMAIN` на ваш реальный домен.

### 6. Перезапуск приложения
В терминале Beget выполните:
```bash
cd /home/USERNAME/YOURDOMAIN/bot
touch tmp/restart.txt
```

## 📁 Структура проекта

```
bot/
├── app/                    # Основное приложение
│   ├── __init__.py        # Flask приложение с webhook
│   ├── bot.py             # Обработчики Telegram
│   ├── config.py          # Конфигурация
│   ├── database.py        # Работа с БД
│   ├── downloader.py      # Загрузка видео
│   └── payments.py        # YooKassa платежи
├── downloads/             # Временные файлы
├── passenger_wsgi.py      # WSGI точка входа для Passenger
├── .htaccess             # Конфигурация веб-сервера
├── requirements.txt       # Зависимости Python
├── keys                   # Секретные ключи (создать вручную!)
└── README_BEGET.md       # Эта инструкция
```

## ⚙️ Требования

- Python 3.7 или выше
- Домен с SSL-сертификатом (для webhook)
- Telegram Bot Token
- YooKassa API ключи (для платежей)

## 🔧 Устранение проблем

### Бот не отвечает
1. Проверьте, что webhook установлен правильно
2. Проверьте логи в панели Beget
3. Убедитесь, что в файле `keys` правильные данные

### Ошибка "Module not found"
Переустановите зависимости:
```bash
source venv/bin/activate
pip install --force-reinstall -r requirements.txt
```

### Webhook не работает
1. Убедитесь, что у домена есть SSL-сертификат
2. Проверьте, что в .htaccess правильные пути
3. Перезапустите приложение через `touch tmp/restart.txt`

## 📞 Поддержка
При возникновении проблем обратитесь к документации Beget:
https://beget.com/ru/kb/how-to/web-apps/python
