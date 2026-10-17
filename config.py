# config.py
import os
from dotenv import load_dotenv

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", 0))
BROADCAST_PEER_ID = int(os.getenv("BROADCAST_PEER_ID", 0))
CHECK_INTERVAL_MINUTES = 2

if not VK_TOKEN:
    raise RuntimeError("VK_TOKEN не задан. Проверьте переменные окружения.")
if not GROUP_ID:
    raise RuntimeError("GROUP_ID не задан. Проверьте переменные окружения.")

print(f"[config] GROUP_ID={GROUP_ID}, token starts with {VK_TOKEN[:10]}...")

SEVSU_NEWS_URL = "https://www.sevsu.ru/novosti/"

# ЖЕСТКИЙ ФИЛЬТР: только конкретные фразы
ALERT_KEYWORDS = [
    "воздушная тревога",
    "ракетная опасность",
    "опасность атаки бпла",
    "угроза атаки бпла",
    "внимание всем",
    "отбой воздушной тревоги",
    "отбой ракетной опасности",
    "отбой угрозы атаки",
]
# ID картинок-шаблонов (формат: "owner_id_photo_id")
PHOTO_ALERT_ID = "513235930_457288731" # Красная картинка (Тревога)
PHOTO_CLEAR_ID = "513235930_457289666" # Зеленая картинка (Отбой)
