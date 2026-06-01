import os
import json
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS_STR = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(uid.strip()) for uid in ALLOWED_USERS_STR.split(",") if uid.strip()]

INSIDE_EMAIL = os.getenv("INSIDE_EMAIL")
INSIDE_PASSWORD = os.getenv("INSIDE_PASSWORD")
FORMA_LOGIN = os.getenv("FORMA_LOGIN")
FORMA_PASSWORD = os.getenv("FORMA_PASSWORD")
FOURCARS_LOGIN = os.getenv("FOURCARS_LOGIN")
FOURCARS_PASSWORD = os.getenv("FOURCARS_PASSWORD")
AUTONOVA_LOGIN = os.getenv("AUTONOVAD_LOGIN")
AUTONOVA_PASSWORD = os.getenv("AUTONOVAD_PASSWORD")

def load_sessions():
    logger.debug("Спроба завантажити sessions.json...")
    if os.path.exists("sessions.json"):
        try:
            with open("sessions.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.debug("✅ sessions.json успішно завантажено.")
                return data
        except Exception as e:
            logger.error(f"❌ Помилка читання sessions.json: {e}")
    else:
        logger.debug("ℹ️ sessions.json не знайдено, буде створено новий після авторизації.")
    return {}

def save_sessions(data):
    logger.debug("Збереження оновлених сесій у sessions.json...")
    try:
        with open("sessions.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.debug("✅ Сесії успішно збережені.")
    except Exception as e:
        logger.error(f"❌ Помилка збереження сесій: {e}", exc_info=True)