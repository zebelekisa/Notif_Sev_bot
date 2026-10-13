# config.py
import os
from dotenv import load_dotenv

load_dotenv()  # читает .env и кладёт значения в os.environ

VK_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", 0))
BROADCAST_PEER_ID = int(os.getenv("BROADCAST_PEER_ID", 0))
CHECK_INTERVAL_MINUTES = 2

# Источники
MCHS_RSS_URL = "https://92.mchs.gov.ru/rss"  # RSS МЧС по Севастополю
SEVSU_NEWS_URL = "https://www.sevsu.ru/news/"
SEVSU_VK_GROUP = "sevsu"  # короткое имя сообщества

# Ключевые слова для фильтрации тревог
ALERT_KEYWORDS = [
    "воздушная тревога",
    "воздушную тревогу",
    "ракетная опасность",
    "опасность",
    "тревога",
    "отбой",
    "угроза",
    "БПЛА",
    "беспилотник",
]
