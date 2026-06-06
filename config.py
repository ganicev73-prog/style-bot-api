import os


def _load_dotenv(path: str = ".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "NeuralStyleTransferBot")

STARS_PACKAGES = {
    5: 5,
    15: 15,
    30: 30,
    50: 50,
    100: 100,
}

CRYPTO_PACKAGES = {
    5: 1.0,
    15: 2.0,
    30: 3.0,
    50: 5.0,
    100: 9.0,
}

CRYPTO_CLOUD_API_KEY = os.getenv("CRYPTO_CLOUD_API_KEY", "")
CRYPTO_CLOUD_SHOP_ID = os.getenv("CRYPTO_CLOUD_SHOP_ID", "")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEB_APP_URL = os.getenv("WEB_APP_URL", "")
WEB_API_HOST = os.getenv("WEB_API_HOST", "127.0.0.1")
WEB_API_PORT = int(os.getenv("WEB_API_PORT", "8787"))
WEB_API_PUBLIC_URL = os.getenv("WEB_API_PUBLIC_URL", "")
