# parsers/sevsu_parser.py
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class SevSUParser:
    """Парсер новостей с сайта СевГУ."""

    def __init__(self, news_url: str):
        self.news_url = news_url
        self._last_news_titles = set()

    def fetch_news(self) -> List[Dict]:
        try:
            resp = requests.get(self.news_url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Ошибка загрузки новостей СевГУ: {e}")
            return []

        # ▼▼▼ ВСТАВИТЬ ЗДЕСЬ — первая строка диагностики ▼▼▼
        print(f"[SevSUParser] HTTP {resp.status_code}, длина HTML: {len(resp.text)}")
        # ▲▲▲ конец первой вставки ▲▲▲

        soup = BeautifulSoup(resp.text, "lxml")
        news_items = []

        # ▼▼▼ ВСТАВИТЬ ЗДЕСЬ — вторая строка диагностики ▼▼▼
        print(f"[SevSUParser] Найдено элементов: {len(soup.select('.news-item, .news-list-item, article'))}")
        # ▲▲▲ конец второй вставки ▲▲▲

        # Селекторы зависят от текущей вёрстки сайта sevsu.ru.
        # Ниже — типовой вариант; при необходимости скорректируйте.
        for item in soup.select(".news-item, .news-list-item, article"):
            title_el = item.select_one("a, .title, h3, h4")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.sevsu.ru" + link

            if title in self._last_news_titles:
                continue

            news_items.append({
                "title": title,
                "link": link,
                "source": "СевГУ",
            })

        # Обновляем кэш заголовков
        for n in news_items:
            self._last_news_titles.add(n["title"])

        return news_items
