# parsers/sevsu_parser.py
import re
import html as html_lib
import feedparser
import datetime
from datetime import timezone, timedelta
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

        # Часовой пояс Севастополя (UTC+3)
        msk_tz = timezone(timedelta(hours=3))
        now_utc = datetime.datetime.now(timezone.utc)
        news_items = []
        
        for entry in feed.entries:
            link = entry.get("link", "")
            
            if not link or (skip_sent and link in sent_links):
                continue

            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_time_utc = datetime.datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                age = now_utc - pub_time_utc
                
                if age > datetime.timedelta(hours=NEWS_MAX_AGE_HOURS):
                    continue

                # ПЕРЕВОДИМ ВРЕМЯ В МЕСТНОЕ (UTC+3)
                pub_time_msk = pub_time_utc.astimezone(msk_tz)
                date = pub_time_msk.strftime('%d.%m.%Y %H:%M')
            else:
                date = ""

            title = entry.get("title", "").strip()
            description = strip_html(entry.get("description", ""))

            news_items.append({
                "title": title,
                "link": link,
                "description": description,
                "date": date,
            })

        return news_items
