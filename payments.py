from yookassa import Configuration, Payment
import uuid
from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки YooKassa
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

def create_payment(amount: float, description: str, user_id: int) -> Optional[dict]:
    """
    Создает платеж через YooKassa и возвращает confirmation_url
    """
    try:
        idempotence_key = str(uuid.uuid4())
        amount_formatted = f"{amount:.2f}"

        # URL возврата после оплаты (должен быть HTTPS)
        return_url = f"https://max-7ftv.onrender.com/payment_return?user_id={user_id}"

        payment = Payment.create({
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
            "receipt": {
                "customer": {
                    "email": f"user{user_id}@example.com"  # для теста можно использовать любой валидный email
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

        if not payment.confirmation or not hasattr(payment.confirmation, 'confirmation_url'):
            logger.error(f"Payment created but no confirmation_url: {payment}")
            return None

        confirmation_url = payment.confirmation.confirmation_url
        logger.info(f"Payment created successfully: id={payment.id}, status={payment.status}")

        return {
            'id': payment.id,
            'status': payment.status,
            'confirmation_url': confirmation_url,
            'amount': amount
        }

    except Exception as e:
        logger.error(f"Error creating payment: {e}", exc_info=True)
        return None


def check_payment_status(payment_id: str) -> dict:
    """
    Проверяет статус платежа через YooKassa
    """
    try:
        logger.info(f"Checking payment status: {payment_id}")
        payment = Payment.find_one(payment_id)
        status = getattr(payment, 'status', 'error')
        paid = getattr(payment, 'paid', False)
        logger.info(f"Payment status: id={payment_id}, status={status}, paid={paid}")
        return {
            'status': status,
            'paid': paid
        }
    except Exception as e:
        logger.error(f"Error checking payment {payment_id}: {e}", exc_info=True)
        return {'status': 'error', 'paid': False}
