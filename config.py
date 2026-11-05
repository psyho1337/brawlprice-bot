import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BS_API_KEY = os.getenv("BS_API_KEY", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
MARKUP = float(os.getenv("MARKUP", "1.10"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
# Менеджер, к которому ведут кнопки "Продать" и "Уточнить редкое"
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "psyhode3ic").lstrip("@")
# Необязательно: ID чата/пользователя, куда бот будет присылать заявки на продажу
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0") or 0)
# Менеджеры: видят заявки и меняют их статус, но НЕ имеют доступа к админ-панели
MANAGER_IDS = {int(x) for x in os.getenv("MANAGER_IDS", "").split(",") if x.strip()}

# Обязательная подписка на канал: @username или числовой ID (бот должен быть админом канала)
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip() or (
    f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}" if REQUIRED_CHANNEL.startswith("@") else "")
# Кэш ответов Brawl Stars API (секунды) и автобэкап базы (часы, 0 = выключить)
API_CACHE_SECONDS = int(os.getenv("API_CACHE_SECONDS", "120") or 120)
BACKUP_HOURS = float(os.getenv("BACKUP_HOURS", "24") or 24)
BACKUP_SEND = os.getenv("BACKUP_SEND", "1") != "0"   # присылать копию базы первому админу
