from yookassa import Configuration, Payment
import uuid
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, BOT_USERNAME
    
    if not YOOKASSA_SECRET_KEY or not YOOKASSA_SHOP_ID:
        logger.error("❌ YOOKASSA_SECRET_KEY или YOOKASSA_SHOP_ID не установлены!")
        logger.error("Проверьте переменные окружения в Render!")
    else:
        Configuration.account_id = YOOKASSA_SHOP_ID
        Configuration.secret_key = YOOKASSA_SECRET_KEY
        logger.info(f"✅ ЮКасса настроена: Shop ID = {YOOKASSA_SHOP_ID[:10]}...")
        
except Exception as e:
    logger.error(f"❌ Ошибка при загрузке конфигурации ЮКассы: {e}")
    raise

def create_payment(amount: float, description: str, user_id: int) -> dict:
    try:
        idempotence_key = str(uuid.uuid4())
        
        logger.info(f"Создание платежа: {amount} RUB для пользователя {user_id}")
        logger.info(f"Idempotence key: {idempotence_key}")
        
        payment_data = {
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
        }
        
        logger.info(f"Отправка запроса в ЮКассу...")
        payment = Payment.create(payment_data, idempotence_key)
        
        logger.info(f"✅ Платеж создан успешно: ID = {payment.id}, Status = {payment.status}")
        
        result = {
            'id': payment.id,
            'status': payment.status,
            'confirmation_url': payment.confirmation.confirmation_url,
            'amount': amount
        }
        
        logger.info(f"URL для оплаты: {result['confirmation_url']}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания платежа: {e}", exc_info=True)
        logger.error(f"Тип ошибки: {type(e).__name__}")
        logger.error(f"Детали: {str(e)}")
        return None

def check_payment_status(payment_id: str) -> dict:
    try:
        logger.info(f"Проверка статуса платежа: {payment_id}")
        
        payment = Payment.find_one(payment_id)
        
        result = {
            'status': payment.status,
            'paid': payment.paid
        }
        
        logger.info(f"Статус платежа {payment_id}: {result['status']}, Оплачен: {result['paid']}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки платежа {payment_id}: {e}", exc_info=True)
        logger.error(f"Тип ошибки: {type(e).__name__}")
        return {'status': 'error', 'paid': False}
