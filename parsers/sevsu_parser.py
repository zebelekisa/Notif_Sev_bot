# parsers/sevsu_parser.py
import re
import html as html_lib
import feedparser
import time
import datetime
from datetime import timezone
from typing import List, Dict
import logging

from config import NEWS_MAX_AGE_HOURS

logger = logging.getLogger(__name__)

def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html_lib.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()

class SevSUParser:
    def __init__(self, rss_url: str, storage=None):
        self.rss_url = rss_url
        self.storage = storage

    def fetch_news(self, skip_sent: bool = False) -> List[Dict]:
        try:
            feed = feedparser.parse(self.rss_url)
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS СевГУ: {e}")
            return []

        if not feed.entries:
            return []

        sent_links = set()
        if skip_sent and self.storage is not None:
            try:
                sent_links = self.storage.get_sent_news_links()
            except Exception as e:
                logger.error(f"Ошибка чтения БД: {e}")

        now_utc = datetime.datetime.now(timezone.utc)
        news_items = []
        
        for entry in feed.entries:
            link = entry.get("link", "")
            
            # Пропускаем, если нет ссылки или она уже отправлена
            if not link or (skip_sent and link in sent_links):
                continue

            # --- ФИЛЬТР ПО ДАТЕ ---
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_time_utc = datetime.datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                age = now_utc - pub_time_utc
                
                # Если новость старше разрешенного возраста — пропускаем
                if age > datetime.timedelta(hours=NEWS_MAX_AGE_HOURS):
                    continue
            # -----------------------

            title = entry.get("title", "").strip()
            description = strip_html(entry.get("description", ""))
            
            date = time.strftime('%d.%m.%Y %H:%M', entry.published_parsed) if hasattr(entry, 'published_parsed') else ""

            category = entry.get("category", "")
            if category and "/" in category:
                category = category.split("/")[0].strip()

            news_items.append({
                "title": title,
                "link": link,
                "description": description,
                "date": date,
                "category": category,
            })

        return news_items
