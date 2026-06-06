import os

try:
    from config import (
        STARS_PACKAGES as CFG_S_PACK,
        CRYPTO_PACKAGES as CFG_C_PACK,
        BOT_USERNAME as CFG_USERNAME,
    )
    STARS_PACKAGES = CFG_S_PACK
    CRYPTO_PACKAGES = CFG_C_PACK
    BOT_USERNAME = CFG_USERNAME
except ImportError:
    STARS_PACKAGES = {5: 5, 15: 15, 30: 30, 50: 50, 100: 100}
    CRYPTO_PACKAGES = {5: 1.0, 15: 2.0, 30: 3.0, 50: 5.0, 100: 9.0}
    BOT_USERNAME = os.getenv("BOT_USERNAME", "NeuralStyleTransferBot")
