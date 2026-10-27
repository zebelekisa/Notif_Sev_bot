# parsers/governor_parser.py
import logging
import vk_api
import os
from dotenv import load_dotenv
from datetime import datetime  # <--- ДОБАВИЛИ ИМПОРТ ДЛЯ ДАТЫ

load_dotenv()
logger = logging.getLogger(__name__)

class GovernorParser:
    def __init__(self):
        # Берем сервисный ключ из .env
        self.token = os.getenv("VK_SERVICE_TOKEN")
        if not self.token:
            logger.error("VK_SERVICE_TOKEN не задан в .env! Парсер губернатора не будет работать.")
            self.vk = None
        else:
            # Авторизуемся с сервисным ключом
            self.vk_session = vk_api.VkApi(token=self.token)
            self.vk = self.vk_session.get_api()
            
        self.domain = "razvozhaev_m"

    def fetch_posts(self, count: int = 30) -> list:
        """Возвращает список постов со стены через официальный API."""
        if not self.vk:
            return []

        try:
            # Запрашиваем посты со стены
            response = self.vk.wall.get(
                domain=self.domain,
                count=count,
                filter="all",
                v="5.199" # Актуальная версия API
            )
            return response.get("items", [])
        except Exception as e:
            logger.error(f"Ошибка wall.get для {self.domain}: {e}")
            return []

    def fetch_all_recent(self, limit: int = 30) -> list:
        """Возвращает посты в формате, который ожидает бот."""
        raw_posts = self.fetch_posts(count=limit)
        
        posts = []
        for p in raw_posts:
            # Конвертируем Unix timestamp в строку "ДД.ММ.ГГГГ ЧЧ:ММ"
            timestamp = p.get("date", 0)
            dt = datetime.fromtimestamp(timestamp).strftime('%d.%m.%Y %H:%M')

            # ДОБАВЛЯЕМ ПОИСК КАРТИНОК
            photo_ids = []
            for attachment in p.get("attachments", []):
                if attachment.get("type") == "photo":
                    photo = attachment.get("photo", {})
                    owner_id = photo.get("owner_id")
                    photo_id = photo.get("id")
                    if owner_id and photo_id:
                        photo_ids.append(f"{owner_id}_{photo_id}")
            posts.append({
                "id": p.get("id"),
                "text": p.get("text", ""),
                "date": p.get("date"),
                "date": dt,  # <--- Теперь тут красивая строка
                "photos": photo_ids, # <--- Передаем ID картинок в бота
            })
        return posts
