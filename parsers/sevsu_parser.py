# parsers/sevsu_parser.py
import re
import html as html_lib
import feedparser
import time
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    """Убирает HTML-теги и раскодирует сущности (&nbsp;, &amp; и т.п.)."""
    if not text:
        return ""
    # Раскодируем HTML-сущности
    text = html_lib.unescape(text)
    # Убираем теги
    text = re.sub(r"<[^>]+>", "", text)
    # Сжимаем пробелы
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SevSUParser:
    """Парсер новостей СевГУ через RSS-ленту Битрикса."""

    def __init__(self, rss_url: str = "https://www.sevsu.ru/novosti/rss.php?section=0",
                 storage=None):
        self.rss_url = rss_url
        self.storage = storage  # storage.db.Storage | None

    def fetch_news(self, skip_sent: bool = False) -> List[Dict]:
        try:
            feed = feedparser.parse(self.rss_url)
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS СевГУ: {e}")
            return []

        if not feed.entries:
            logger.warning(f"[SevSUParser] RSS пуст или недоступен: {self.rss_url}")
            return []

        logger.info(f"[SevSUParser] Найдено новостей в RSS: {len(feed.entries)}")

        # Если нужно отбросить уже разосланные — читаем один раз
        sent_links = set()
        if skip_sent and self.storage is not None:
            try:
                sent_links = self.storage.get_sent_news_links()
            except Exception as e:
                logger.error(f"[SevSUParser] Не удалось прочитать sent_news: {e}")

        news_items = []
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link:
                continue
            if skip_sent and link in sent_links:
                continue

            title = entry.get("title", "").strip()
            description = strip_html(entry.get("description", ""))
            # КРАСИВАЯ ДАТА
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                date = time.strftime('%d.%m.%Y %H:%M', entry.published_parsed)
            else:
                date = entry.get("published", "")

            category = entry.get("category", "")

            if category and "/" in category:
                category = category.split("/")[0].strip()

            news_items.append({
                "title": title,
                "link": link,
                "description": description,
                "date": date,
                "category": category,
                "source": "СевГУ",
            })

        return news_items
