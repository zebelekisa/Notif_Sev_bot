# bot.py
import logging
import time
import requests
import pytesseract
# Указываем точный путь к программе
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from PIL import Image
from io import BytesIO

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.upload import VkUpload
from apscheduler.schedulers.background import BackgroundScheduler
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    VK_TOKEN, GROUP_ID, BROADCAST_PEER_ID, ALERT_KEYWORDS, DRILL_KEYWORDS, CLEAR_KEYWORDS,
    CHECK_INTERVAL_MINUTES, NEWS_CHECK_INTERVAL_MINUTES
)
from parsers.sevsu_parser import SevSUParser
from parsers.governor_parser import GovernorParser
from storage.db import Storage
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bot")

# ===== Клавиатуры =====
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("🚨 Статус тревоги", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("📰 Новости", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("📋 Памятка", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("⚙️ Настройки", color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()

def get_settings_keyboard(storage, user_id):
    cur = storage.conn.cursor()
    cur.execute("SELECT notify_alerts, notify_news FROM subscribers WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    alerts_on = row[0] if row else 1
    news_on = row[1] if row else 1

    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("🔔 Тревоги: вкл ✅" if alerts_on else "🔕 Тревоги: выкл ❌", 
                        color=VkKeyboardColor.POSITIVE if alerts_on else VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button("📨 Новости: вкл ✅" if news_on else "🔕 Новости: выкл ❌", 
                        color=VkKeyboardColor.POSITIVE if news_on else VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button("🧪 Тест тревог (Губернатор)", color=VkKeyboardColor.SECONDARY) # <--- ВЕРНУЛИ КНОПКУ
    keyboard.add_line()
    keyboard.add_button("🗑 Очистить новости", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("⬅️ Назад", color=VkKeyboardColor.PRIMARY)
    return keyboard.get_keyboard()

def get_empty_keyboard():
    return VkKeyboard(one_time=False).get_empty_keyboard()

# ===== Основной класс =====
class NotificationBot:
    def __init__(self):
        self.vk_session = vk_api.VkApi(token=VK_TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, GROUP_ID)
        
        # Загрузка фото
        user_token = os.getenv("VK_USER_TOKEN")
        if user_token:
            self.upload = VkUpload(vk_api.VkApi(token=user_token))
        else:
            self.upload = None

        self.storage = Storage()
        self.sevsu_site = SevSUParser("https://www.sevsu.ru/novosti/rss.php?section=0", storage=self.storage)
        self.governor_parser = GovernorParser()

    def send_message(self, peer_id: int, text: str, keyboard: dict = None, attachment: str = None) -> bool:
        try:
            self.vk.messages.send(
                peer_id=peer_id, message=text, attachment=attachment,
                keyboard=keyboard if keyboard is not None else get_empty_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки в {peer_id}: {e}")
            return False

    def send_to_all(self, text: str, only_alerts: bool = False, only_news: bool = False):
        subscribers = self.storage.get_subscribers(only_alerts=only_alerts, only_news=only_news)
        for user_id, peer_id in subscribers:
            self.send_message(peer_id, text)
            time.sleep(0.1)

    # ---------- ЯДРО: Анализ поста и OCR ----------
    def get_image_text(self, url: str) -> str:
        """Скачивает картинку и распознает текст (OCR)."""
        if not url: return ""
        try:
            # Скачиваем картинку
            img_data = requests.get(url, timeout=5).content
            img = Image.open(BytesIO(img_data))
            
            # Оптимизация: уменьшаем картинку, если она огромная, для скорости OCR
            img.thumbnail((1000, 1000))
            
            # Конвертируем в ч/б для лучшего распознавания контрастного текста
            img = img.convert('L')
            
            # Распознаем русский текст
            text = pytesseract.image_to_string(img, lang='rus')
            return text.lower().replace(" ", "").replace("\n", "")
        except Exception as e:
            logger.error(f"Ошибка OCR: {e}")
            return ""

    def analyze_post(self, post: dict) -> str:
        """Определяет тип поста: ALERT, CLEAR, DRILL или UNKNOWN."""
        # Убираем лишние пробелы по краям
        text = post.get("text", "").lower().strip()
        
        # 1. ЕСЛИ ТЕКСТ ЕСТЬ - проверяем только его, OCR не запускаем
        if text:
            clean_text = text.replace(" ", "")
            if any(kw in clean_text for kw in CLEAR_KEYWORDS): return "CLEAR"
            if any(kw in clean_text for kw in DRILL_KEYWORDS): return "DRILL"
            if any(kw in clean_text for kw in ALERT_KEYWORDS): return "ALERT"
            
            # Если текст есть, но он не про тревогу (например, "ремонт дорог") - пропускаем
            return "UNKNOWN"

        # 2. ЕСЛИ ТЕКСТА НЕТ ВООБЩЕ - включаем OCR (только для картинок)
        if not text and post.get("image_url"):
            img_text = self.get_image_text(post["image_url"])
            
            if any(kw.replace(" ", "") in img_text for kw in CLEAR_KEYWORDS): return "CLEAR"
            if any(kw.replace(" ", "") in img_text for kw in DRILL_KEYWORDS): return "DRILL"
            if any(kw.replace(" ", "") in img_text for kw in ALERT_KEYWORDS): return "ALERT"
            
            # Если OCR распознал только "учения" без других слов
            if "учения" in img_text: return "DRILL"

        return "UNKNOWN"

    # ---------- Фоновая проверка тревог ----------
    def process_alerts(self):
        logger.info("Проверка тревог...")
        posts = self.governor_parser.fetch_all_recent(limit=5)
        
        for p in reversed(posts):
            post_id = str(p.get("id"))
            if self.storage.is_alert_sent(post_id):
                continue

            p_type = self.analyze_post(p)
            
            if p_type == "CLEAR":
                msg = f"✅ ОТБОЙ ВОЗДУШНОЙ ТРЕВОГИ\n\n🕒 {p.get('date')}"
            elif p_type == "DRILL":
                msg = f"⚠️ ИДУТ УЧЕНИЯ\n\n🕒 {p.get('date')}\n\nСохраняйте спокойствие."
            elif p_type == "ALERT":
                msg = f"🚨 ВНИМАНИЕ! ВОЗДУШНАЯ ТРЕВОГА!\n\n🕒 {p.get('date')}\n\nСпуститесь в укрытие!\n\n🔗 https://vk.com/wall-{p.get('owner_id', '')}_{post_id}"
            else:
                continue

            logger.warning(f"ОТПРАВЛЕНА РАССЫЛКА: {p_type}")
            self.send_to_all(msg, only_alerts=True)
            self.storage.mark_alert_sent(post_id)

    # ---------- Обработка команд ----------
    def handle_message(self, event):
        user_id = event.message.from_id
        peer_id = event.message.peer_id
        text = event.message.text.strip()

        if text.lower() in ("/start", "начать", "start", ""):
            self.storage.add_subscriber(user_id, peer_id)
            self.send_message(peer_id, "👋 Привет! Я бот уведомлений СевГУ.\n\nВыберите действие:", keyboard=get_main_keyboard())
            return

        # === ТЕСТОВЫЙ РЕЖИМ ТРЕВОГ (ГЛУБОКАЯ ПРОВЕРКА) ===
        if text.lower() == "/test_alerts" or text == "🧪 Тест тревог (Губернатор)":
            self.send_message(peer_id, "⏳ Загружаю до 30 постов и распознаю картинки (это может занять 10-15 секунд)...")
            
            # УВЕЛИЧИВАЕМ ЛИМИТ ДО 30
            posts = self.governor_parser.fetch_all_recent(limit=30) 
            if not posts:
                self.send_message(peer_id, "⚠️ Не удалось загрузить посты.", keyboard=get_main_keyboard())
                return
                
            report = ["🧪 РЕЗУЛЬТАТЫ ТЕСТА (последние 30 постов):\n"] 
            alerts_found = 0
            
            for p in posts:
                p_type = self.analyze_post(p)
                
                if p_type != "UNKNOWN":
                    alerts_found += 1
                    status = "🚨 ТРЕВОГА" if p_type == "ALERT" else ("✅ ОТБОЙ" if p_type == "CLEAR" else "⚠️ УЧЕНИЯ")
                    source = "текст" if p.get("text", "").strip() else "OCR (картинка)"
                    report.append(f"{status} [{p.get('date')}]\n👁 {source}\n")
            
            if alerts_found == 0:
                report.append("✅ За последние 30 постов событий не найдено.")
                
            self.send_message(peer_id, "\n".join(report), keyboard=get_main_keyboard())
            return

        # === КНОПКА СТАТУСА ТРЕВОГИ ===
        if text == "🚨 Статус тревоги":
            posts = self.governor_parser.fetch_all_recent(limit=5)
            status = "✅ Воздушная тревога не объявлена."
            
            for p in posts:
                p_type = self.analyze_post(p)
                if p_type == "ALERT":
                    status = f"🚨 ВОЗДУШНАЯ ТРЕВОГА!\n\nОбъявлена: {p.get('date')}\n\nСпуститесь в укрытие!"
                    break
                elif p_type == "DRILL":
                    status = f"⚠️ ИДУТ УЧЕНИЯ.\n\nДата: {p.get('date')}"
                    break
                elif p_type == "CLEAR":
                    break
            
            self.send_message(peer_id, status, keyboard=get_main_keyboard())
            return

        # === НОВОСТИ ===
        if text == "📰 Новости":
            news = self.sevsu_site.fetch_news(skip_sent=True)
            if not news:
                self.send_message(peer_id, "Пока новых (свежих) новостей нет.", keyboard=get_main_keyboard())
            else:
                latest_8 = news[:8]
                latest_8.reverse()
                for n in latest_8:
                    msg = f"📰 Новость СевГУ\n\n🗓 {n.get('date', '')}\n\n{n.get('title', '')}"
                    if n.get('description'): msg += f"\n\n{n.get('description')[:300]}..."
                    msg += f"\n\n🔗 {n.get('link', '')}"
                    if self.send_message(peer_id, msg, keyboard=get_main_keyboard()):
                        self.storage.mark_news_sent(n.get('link'))
                        time.sleep(1)
            return

        # === ПАМЯТКА ===
        if text == "📋 Памятка":
            memo = ("📋 Памятка при воздушной тревоге\n\n1. Не паникуйте.\n2. Проследуйте в укрытие.\n"
                    "3. Если укрытия нет — помещение без окон.\n4. Отойдите от окон.\n5. Не пользуйтесь лифтом.\n"
                    "6. Возьмите документы, телефон, воду.\n7. Дождитесь отбоя.")
            self.send_message(peer_id, memo, keyboard=get_main_keyboard())
            return

        # === НАСТРОЙКИ ===
        if text == "⚙️ Настройки":
            self.send_message(peer_id, "\u2063", keyboard=get_settings_keyboard(self.storage, user_id))
            return

        if "Тревоги:" in text:
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_alerts FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute("UPDATE subscribers SET notify_alerts = ? WHERE user_id = ?", (new_val, user_id))
            self.storage.conn.commit()
            self.send_message(peer_id, "\u2063", keyboard=get_settings_keyboard(self.storage, user_id))
            return

        if "Новости:" in text:
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_news FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute("UPDATE subscribers SET notify_news = ? WHERE user_id = ?", (new_val, user_id))
            self.storage.conn.commit()
            self.send_message(peer_id, "\u2063", keyboard=get_settings_keyboard(self.storage, user_id))
            return

        if text == "🗑 Очистить новости":
            self.storage.clear_sent_news()
            self.send_message(peer_id, "🗑 История новостей очищена.", keyboard=get_settings_keyboard(self.storage, user_id))
            return

        if text == "⬅️ Назад":
            self.send_message(peer_id, "Главное меню:", keyboard=get_main_keyboard())
            return

    # ---------- Запуск ----------
    def run(self):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self.process_alerts, "interval", minutes=CHECK_INTERVAL_MINUTES)
        scheduler.start()

        logger.info("Бот запущен. Умный OCR-парсинг активен.")
        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    self.handle_message(event)
                except Exception as e:
                    logger.exception(f"Ошибка: {e}")

if __name__ == "__main__":
    bot = NotificationBot()
    bot.run()
