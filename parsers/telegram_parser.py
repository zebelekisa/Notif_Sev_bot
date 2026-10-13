# parsers/telegram_parser.py
import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)


class TelegramChannelParser:
    """Парсит публичную веб-версию Telegram-канала (t.me/s/...)."""

    def __init__(self, channel: str):
        self.channel = channel
        self.url = f"https://t.me/s/{channel}"
        self._last_post_id = None

    def fetch_latest(self) -> list:
        try:
            resp = requests.get(self.url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Ошибка загрузки {self.url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        posts = []
        for msg in soup.select(".tgme_widget_message_wrap"):
            post_id = msg.get("data-post", "")
            text_el = msg.select_one(".tgme_widget_message_text")
            if not text_el:
                continue
            text = text_el.get_text(strip=True)
            # Простейшая фильтрация по ключевым словам
            if any(kw in text.lower() for kw in ["тревога", "отбой", "опасность"]):
                posts.append({
                    "id": post_id,
                    "text": text,
                    "source": f"Telegram @{self.channel}",
                })
        return posts
