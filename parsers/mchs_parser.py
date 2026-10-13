# parsers/mchs_parser.py
import requests
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MCHSParser:
    """Парсер RSS-ленты МЧС Севастополя для отслеживания воздушных тревог."""

    def __init__(self, rss_url: str, keywords: List[str]):
        self.rss_url = rss_url
        self.keywords = [kw.lower() for kw in keywords]
        self._last_seen_guid: Optional[str] = None

    def fetch_alerts(self) -> List[Dict]:
        """
        Возвращает список новых записей, содержащих ключевые слова.
        Каждая запись — dict с полями: title, link, published, summary, guid.
        """
        try:
            feed = feedparser.parse(self.rss_url)
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS МЧС: {e}")
            return []

        alerts = []
        for entry in feed.entries:
            # Пропускаем уже обработанные записи
            if self._last_seen_guid and entry.get("id") == self._last_seen_guid:
                break

            text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
            if any(kw in text for kw in self.keywords):
                alerts.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                    "guid": entry.get("id", entry.get("link", "")),
                    "source": "МЧС Севастополь",
                })

        # Запоминаем последнюю запись, чтобы не дублировать
        if feed.entries:
            self._last_seen_guid = feed.entries[0].get("id")

        return alerts

    def check_alert_status(self) -> Optional[str]:
        """
        Быстрая проверка: есть ли в последних записях признаки тревоги.
        Возвращает 'alert', 'all_clear' или None.
        """
        alerts = self.fetch_alerts()
        for alert in alerts:
            text = alert["title"].lower() + " " + alert["summary"].lower()
            if "отбой" in text:
                return "all_clear"
            if any(kw in text for kw in ["воздушная тревога", "ракетная опасность"]):
                return "alert"
        return None
