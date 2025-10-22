import uuid
import logging
from typing import Optional
from yookassa import Configuration, Payment
from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, BOT_USERNAME

# 🔧 Настройка логирования (всё будет видно в Render Logs)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ⚙️ Настройка ключей YooKassa
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY


def create_payment(amount: float, description: str, user_id: int) -> Optional[dict]:
    """
    Создает платеж через YooKassa
    Возвращает dict с полями id, status, confirmation_url, amount
    """
    try:
        idempotence_key = str(uuid.uuid4())
        amount_formatted = f"{amount:.2f}"

        logger.info(f"[START PAYMENT] User {user_id} | Amount: {amount_formatted} | Desc: {description}")

        payment = Payment.create({
            "amount": {
                "value": amount_formatted,
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
        }, idempotence_key)

        # Проверка обязательных полей
        if not payment.confirmation or not hasattr(payment.confirmation, "confirmation_url"):
            logger.error(f"[ERROR] No confirmation URL in payment object: {payment}")
            return None

        confirmation_url = payment.confirmation.confirmation_url

        logger.info(f"[PAYMENT CREATED] ✅ ID: {payment.id} | Status: {payment.status} | URL: {confirmation_url}")

        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": confirmation_url,
            "amount": amount
        }

    except Exception as e:
        logger.error(f"[Yookassa Error] ❌ {e}", exc_info=True)
        return None


def check_payment_status(payment_id: str) -> dict:
    """
    Проверяет статус платежа через YooKassa
    Возвращает dict: {'status': str, 'paid': bool}
    """
    try:
        logger.info(f"[CHECK PAYMENT] Checking status for ID: {payment_id}")
        payment = Payment.find_one(payment_id)

        status = getattr(payment, "status", "error")
        paid = getattr(payment, "paid", False)

        logger.info(f"[PAYMENT STATUS] ID: {payment_id} | Status: {status} | Paid: {paid}")

        return {"status": status, "paid": paid}

    except Exception as e:
        logger.error(f"[Error Checking Payment] ❌ {e}", exc_info=True)
        return {"status": "error", "paid": False}
