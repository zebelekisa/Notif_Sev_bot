# parsers/governor_parser.py
import logging
import vk_api
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class GovernorParser:
    def __init__(self):
        self.token = os.getenv("VK_SERVICE_TOKEN")
        self.vk = vk_api.VkApi(token=self.token).get_api() if self.token else None
        self.domain = "razvozhaev_m"

    def fetch_all_recent(self, limit: int = 10) -> list:
        if not self.vk: return []
        try:
            res = self.vk.wall.get(domain=self.domain, count=limit, filter="all", v="5.199")
            raw_posts = res.get("items", [])
        except Exception as e:
            logger.error(f"Ошибка wall.get: {e}")
            return []

        posts = []
        for p in raw_posts:
            dt = datetime.fromtimestamp(p.get("date", 0)).strftime('%d.%m.%Y %H:%M')
            
            # Ищем лучшую картинку для OCR (берем размер 'x' или 'z', они оптимальны по размеру)
            image_url = None
            for attachment in p.get("attachments", []):
                if attachment.get("type") == "photo":
                    sizes = attachment.get("photo", {}).get("sizes", [])
                    # Сортируем по ширине и берем среднюю (около 600-800px), чтобы OCR работал быстро
                    sizes = sorted([s for s in sizes if s.get('width', 0) > 0], key=lambda x: x['width'])
                    if sizes:
                        # Берем предпоследний размер (обычно 600-800px)
                        best_size = sizes[-2] if len(sizes) > 1 else sizes[0]
                        image_url = best_size.get("url")
                        break # Берем только первую картинку

            posts.append({
                "id": p.get("id"),
                "text": p.get("text", "").strip(),
                "date": dt,
                "image_url": image_url,
            })
        return posts
