# parsers/sevsu_parser.py
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class SevSUParser:
    """Парсер новостей с сайта СевГУ (страница /novosti/)."""

    BASE_URL = "https://www.sevsu.ru"

    def __init__(self, news_url: str = "https://www.sevsu.ru/novosti/"):
        self.news_url = news_url
        self._last_news_titles = set()

    def fetch_news(self) -> List[Dict]:
        try:
            resp = requests.get(
                self.news_url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SevSU-Bot/1.0)"},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Ошибка загрузки новостей СевГУ: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # ... внутри fetch_news после soup = BeautifulSoup(...)        
        # 1. Сколько блоков нашлось каждым селектором отдельно
        print(f"[DEBUG] div.page-news: {len(soup.select('div.page-news'))}")
        print(f"[DEBUG] a.page-news__title: {len(soup.select('a.page-news__title'))}")
        print(f"[DEBUG] .page-news__content: {len(soup.select('.page-news__content'))}")
        # 2. Что вообще в HTML
        print(f"[DEBUG] Длина HTML: {len(resp.text)}")
        print(f"[DEBUG] Первые 300 символов: {resp.text[:300]}")
        print(f"[DEBUG] Содержит 'page-news': {'page-news' in resp.text}")

        # Основная лента новостей — блоки div.page-news (слайдер игнорируем)
        news_blocks = soup.select("div.page-news")
        logger.info(f"[SevSUParser] Найдено блоков новостей: {len(news_blocks)}")

        news_items = []
        for block in news_blocks:
            # Заголовок и ссылка
            title_el = block.select_one("a.page-news__title")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            if link and not link.startswith("http"):
                link = self.BASE_URL + link

            # Категория (Жизнь СевГУ, Новости СевГУ, Анонсы и т.д.)
            type_el = block.select_one(".page-news__type")
            category = type_el.get_text(strip=True) if type_el else ""

            # Краткое описание
            desc_el = block.select_one(".page-news__content p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Дата
            date_el = block.select_one(".page-news__info time")
            date_text = date_el.get_text(" ", strip=True) if date_el else ""

            if title in self._last_news_titles:
                continue

            news_items.append({
                "title": title,
                "link": link,
                "description": description,
                "category": category,
                "date": date_text,
                "source": "СевГУ",
            })

        # Обновляем кэш, чтобы не дублировать
        for n in news_items:
            self._last_news_titles.add(n["title"])

        return news_items
