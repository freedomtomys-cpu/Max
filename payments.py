# payments.py
import uuid
import logging
from typing import Optional, Dict
from yookassa import Configuration, Payment
from yookassa.exceptions import ApiException
from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, BOT_USERNAME

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключаем боевые ключи (у тебя они уже в Environment on Render)
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# Базовый return_url на твой сервер (должен быть HTTPS)
BASE_RETURN_URL = "https://max-7ftv.onrender.com"  # <-- при необходимости замени

def create_payment(amount: float, description: str, user_id: int) -> Optional[Dict]:
    """
    Создает платеж в YooKassa и возвращает dict с id, status, confirmation_url, amount
    Возвращает None при ошибке.
    """
    try:
        idempotence_key = str(uuid.uuid4())
        amount_formatted = f"{amount:.2f}"

        return_url = f"{BASE_RETURN_URL}/payment_return?user_id={user_id}&payment_amount={amount_formatted}"

        payload = {
            "amount": {
                "value": amount_formatted,
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description,
            # Receipt/Items: если в бизнес-аккаунте требуется фискализация, заполняй корректно.
            "receipt": {
                "customer": {
                    # Валидный email — не используем странные домены
                    "email": f"user{user_id}@example.com"
                },
                "items": [
                    {
                        "description": description[:127],  # ограничение длины
                        "quantity": "1.00",
                        "amount": {
                            "value": amount_formatted,
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

        logger.info("Создаём платёж: amount=%s user_id=%s", amount_formatted, user_id)
        payment = Payment.create(payload, idempotence_key)

        # В SDK объект Payment должен содержать confirmation и confirmation_url
        confirmation = getattr(payment, "confirmation", None)
        confirmation_url = getattr(confirmation, "confirmation_url", None) if confirmation else None

        if not confirmation_url:
            logger.error("Платёж создан, но confirmation_url отсутствует: %s", payment)
            return None

        logger.info("Платёж создан: id=%s status=%s", payment.id, payment.status)
        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": confirmation_url,
            "amount": float(amount_formatted)
        }

    except ApiException as ae:
        # yookassa SDK может бросать ApiException — логируем тело ответа
        logger.exception("ApiException при создании платежа: %s", getattr(ae, "message", ae))
        try:
            # Может быть полезно посмотреть тело ответа, если есть
            logger.error("ApiException details: %s", ae.__dict__)
        except Exception:
            pass
        return None
    except Exception as e:
        logger.exception("Ошибка при создании платежа: %s", e)
        return None


def check_payment_status(payment_id: str) -> Dict:
    """
    Проверяет статус платежа в YooKassa.
    Возвращает словарь {'status': ..., 'paid': bool}
    """
    try:
        logger.info("Запрос статуса платежа: %s", payment_id)
        payment = Payment.find_one(payment_id)
        status = getattr(payment, "status", "error")
        paid = getattr(payment, "paid", False)
        logger.info("Статус платежа: id=%s status=%s paid=%s", payment_id, status, paid)
        return {"status": status, "paid": paid}
    except ApiException as ae:
        logger.exception("ApiException при проверке платежа %s: %s", payment_id, getattr(ae, "message", ae))
        return {"status": "error", "paid": False}
    except Exception as e:
        logger.exception("Ошибка при проверке платежа %s: %s", payment_id, e)
        return {"status": "error", "paid": False"}
