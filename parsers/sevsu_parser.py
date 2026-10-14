# parsers/sevsu_parser.py
import re
import html as html_lib
import feedparser
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

    def __init__(self, rss_url: str = "https://www.sevsu.ru/novosti/rss.php?section=0"):
        self.rss_url = rss_url
        self._last_news_links = set()

    def fetch_news(self) -> List[Dict]:
        try:
            feed = feedparser.parse(self.rss_url)
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS СевГУ: {e}")
            return []

        if not feed.entries:
            logger.warning(f"[SevSUParser] RSS пуст или недоступен: {self.rss_url}")
            return []

        logger.info(f"[SevSUParser] Найдено новостей в RSS: {len(feed.entries)}")

        news_items = []
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link or link in self._last_news_links:
                continue

            title = entry.get("title", "").strip()
            description = strip_html(entry.get("description", ""))
            date = entry.get("published", "")
            category = entry.get("category", "")

            # Категория в RSS СевГУ длинная: "Институт/Кафедра".
            # Для бота оставляем только институт.
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

        # Запоминаем, чтобы не дублировать
        for n in news_items:
            self._last_news_links.add(n["link"])

        return news_items
