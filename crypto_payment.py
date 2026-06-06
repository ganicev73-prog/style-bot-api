import os, logging, requests

logger = logging.getLogger(__name__)

API_URL = "https://api.cryptocloud.plus/v2"

try:
    from config import (
        CRYPTO_CLOUD_API_KEY as CFG_KEY,
        CRYPTO_CLOUD_SHOP_ID as CFG_SHOP,
        CRYPTO_PACKAGES as CFG_PACK,
    )
    API_KEY = CFG_KEY
    SHOP_ID = CFG_SHOP
    CRYPTO_PACKAGES = CFG_PACK
except ImportError:
    API_KEY = os.getenv("CRYPTO_CLOUD_API_KEY", "")
    SHOP_ID = os.getenv("CRYPTO_CLOUD_SHOP_ID", "")
    CRYPTO_PACKAGES = {5: 1.0, 15: 2.0, 30: 3.0, 50: 5.0, 100: 9.0}


def create_invoice(amount_usd: float, user_id: int, stylizations: int) -> dict | None:
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "amount": amount_usd,
        "shop_id": SHOP_ID,
        "currency": "USD",
        "order_id": f"user{user_id}_{stylizations}",
    }
    try:
        r = requests.post(
            f"{API_URL}/invoice/create",
            headers=headers,
            json=data,
            timeout=15,
        )
        if r.status_code == 200:
            result = r.json()
            if result.get("status") == "success":
                return result["result"]
        logger.error(f"CryptoCloud create error: {r.status_code} {r.text}")
    except Exception as e:
        logger.exception(f"CryptoCloud request failed: {e}")
    return None


def check_invoice(uuid: str) -> str | None:
    headers = {"Authorization": f"Token {API_KEY}"}
    data = {"uuids": [uuid]}
    try:
        r = requests.post(
            f"{API_URL}/invoice/merchant/info",
            headers=headers,
            json=data,
            timeout=15,
        )
        if r.status_code == 200:
            result = r.json()
            if result.get("status") == "success":
                invoices = result.get("result", [])
                if invoices:
                    return invoices[0].get("status")
        logger.error(f"CryptoCloud check error: {r.status_code} {r.text}")
    except Exception as e:
        logger.exception(f"CryptoCloud check failed: {e}")
    return None
