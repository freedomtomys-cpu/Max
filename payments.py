from yookassa import Configuration, Payment
import uuid
from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, BOT_USERNAME
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

def create_payment(amount: float, description: str, user_id: int) -> Optional[dict]:
    """
    Создает платеж через YooKassa
    
    Returns:
        dict с полями id, status, confirmation_url, amount при успехе
        None при ошибке
    """
    try:
        idempotence_key = str(uuid.uuid4())
        
        # ВАЖНО: amount должен быть строкой с 2 десятичными знаками
        amount_formatted = f"{amount:.2f}"
        
        logger.info(f"Creating payment: amount={amount_formatted}, user_id={user_id}")
        
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
        
        # Проверка наличия confirmation объекта
        if not payment.confirmation:
            logger.error(f"Payment created but no confirmation object: {payment}")
            return None
            
        # Проверка наличия confirmation_url
        if not hasattr(payment.confirmation, 'confirmation_url'):
            logger.error(f"Payment confirmation has no confirmation_url: {payment.confirmation}")
            return None
        
        confirmation_url = payment.confirmation.confirmation_url
        
        if not confirmation_url:
            logger.error(f"Payment confirmation_url is empty: {payment}")
            return None
        
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
    
    Returns:
        dict с полями status, paid
        При ошибке возвращает {'status': 'error', 'paid': False}
    """
    try:
        logger.info(f"Checking payment status: {payment_id}")
        payment = Payment.find_one(payment_id)
        
        status = payment.status if hasattr(payment, 'status') else 'error'
        paid = payment.paid if hasattr(payment, 'paid') else False
        
        logger.info(f"Payment status: id={payment_id}, status={status}, paid={paid}")
        
        return {
            'status': status,
            'paid': paid
        }
    except Exception as e:
        logger.error(f"Error checking payment {payment_id}: {e}", exc_info=True)
        return {'status': 'error', 'paid': False}
