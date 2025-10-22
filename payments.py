import uuid
import logging
import httpx

# Ссылка на Cloudflare Worker
YOOKASSA_PROXY_URL = "https://tg-bot.kamizaevruslan.workers.dev/proxy/payments"

async def create_payment(amount: float, description: str):
    """
    Создаёт платёж через Cloudflare Worker
    amount: сумма
    description: описание (например, пакет или юзер ID)
    """
    try:
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/WitchTAROhouse_bot"
            },
            "capture": True,
            "description": description
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(YOOKASSA_PROXY_URL, json=data, headers=headers)
            r.raise_for_status()
            payment = r.json()
            # Возвращаем ссылку на подтверждение оплаты
            return payment["confirmation"]["confirmation_url"]

    except httpx.HTTPStatusError as e:
        logging.error(f"[Yookassa Proxy Error] HTTP {e.response.status_code}: {e.response.text}")
        return None
    except Exception as e:
        logging.error(f"[Yookassa Proxy Error] {e}")
        return None
