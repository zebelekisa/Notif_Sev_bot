# config.py
import os
from dotenv import load_dotenv

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", 0))
BROADCAST_PEER_ID = int(os.getenv("BROADCAST_PEER_ID", 0))
CHECK_INTERVAL_MINUTES = 2
NEWS_CHECK_INTERVAL_MINUTES = 5
# Максимальный возраст новости в часах (24 = 1 сутки)
NEWS_MAX_AGE_HOURS = 60

if not VK_TOKEN or not GROUP_ID:
    raise RuntimeError("VK_TOKEN или GROUP_ID не заданы.")

SEVSU_NEWS_URL = "https://www.sevsu.ru/novosti/"

# Ключевые слова для текста (если он есть)
ALERT_KEYWORDS = ["воздушная тревога", "ракетная опасность", "опасность атаки бпла", "внимание всем"]
DRILL_KEYWORDS = ["проводит учения", "профилактические мероприятия"]
CLEAR_KEYWORDS = ["отбой"]
