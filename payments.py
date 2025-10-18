from yookassa import Configuration, Payment
import uuid
from config import YOOKASSA_SECRET_KEY, YOOKASSA_SHOP_ID, BOT_USERNAME

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

def create_payment(amount: float, description: str, user_id: int) -> dict:
    try:
        idempotence_key = str(uuid.uuid4())
        
        payment = Payment.create({
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
        }, idempotence_key)
        
        return {
            'id': payment.id,
            'status': payment.status,
            'confirmation_url': payment.confirmation.confirmation_url,
            'amount': amount
        }
    except Exception as e:
        print(f"Error creating payment: {e}")
        return None

def check_payment_status(payment_id: str) -> dict:
    try:
        payment = Payment.find_one(payment_id)
        return {
            'status': payment.status,
            'paid': payment.paid
        }
    except Exception as e:
        print(f"Error checking payment: {e}")
        return {'status': 'error', 'paid': False}
