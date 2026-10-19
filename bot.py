# bot.py
import logging
import time

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from apscheduler.schedulers.background import BackgroundScheduler
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import VK_TOKEN, GROUP_ID, BROADCAST_PEER_ID, CHECK_INTERVAL_MINUTES, ALERT_KEYWORDS, PHOTO_ALERT_ID, PHOTO_CLEAR_ID
from parsers.sevsu_parser import SevSUParser
from parsers.governor_parser import GovernorParser
from storage.db import Storage

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

def get_settings_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("🔔 Тревоги: вкл/выкл", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("📨 Новости: вкл/выкл", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("🧪 Тест тревог (Губернатор)", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("🗑 Очистить новости", color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button("⬅️ Назад", color=VkKeyboardColor.NEGATIVE)
    return keyboard.get_keyboard()

def get_empty_keyboard():
    return VkKeyboard(one_time=False).get_empty_keyboard()

# ===== Основной класс =====
class NotificationBot:
    def __init__(self):
        self.vk_session = vk_api.VkApi(token=VK_TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, GROUP_ID)
        self.storage = Storage()
        self.sevsu_site = SevSUParser("https://www.sevsu.ru/novosti/rss.php?section=0", storage=self.storage)
        self.governor_parser = GovernorParser()

    def send_message(self, peer_id: int, text: str, keyboard: dict = None) -> bool:
        try:
            self.vk.messages.send(
                peer_id=peer_id,
                message=text,
                keyboard=keyboard if keyboard is not None else get_empty_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки в {peer_id}: {e}")
            return False

    def broadcast(self, text: str, only_news: bool = False) -> bool:
        if BROADCAST_PEER_ID:
            return self.send_message(BROADCAST_PEER_ID, text)
        return False

    # ---------- Обработка новостей ----------
    def process_news(self):
        # Парсер уже отфильтровал старье и уже отправленные
        news = self.sevsu_site.fetch_news(skip_sent=True)
        
        if not news:
            return

        # Берем и переворачиваем (от старых к новым)
        news.reverse()

        for item in news:
            title = item.get("title", "")
            link = item.get("link", "")
            description = item.get("description", "")
            date = item.get("date", "")
            category = item.get("category", "")

            header = "📰 Новости СевГУ"
            if category:
                header += f" · {category}"

            text = f"{header}\n\n🗓 {date}\n\n{title}"
            if description:
                text += f"\n\n{description[:300]}"
                if len(description) > 300:
                    text += "..."
            if link:
                text += f"\n\n🔗 {link}"

            if self.broadcast(text, only_news=True):
                self.storage.mark_news_sent(link)
                logger.info(f"Отправлена новость: {title[:60]}")
                time.sleep(1)

    # ---------- Обработка команд ----------
    def handle_message(self, event):
        user_id = event.message.from_id
        peer_id = event.message.peer_id
        text = event.message.text.strip()

        if text.lower() in ("/start", "начать", "start", ""):
            self.storage.add_subscriber(user_id, peer_id)
            self.send_message(peer_id, "👋 Привет! Я бот уведомлений СевГУ.\n\nВыберите действие:", keyboard=get_main_keyboard())
            return

        if text.lower() == "/test_alerts" or text == "🧪 Тест тревог (Губернатор)":
            self.send_message(peer_id, "⏳ Загружаю посты губернатора...")
            posts = self.governor_parser.fetch_all_recent(limit=30)
            
            if not posts:
                self.send_message(peer_id, "⚠️ Не удалось загрузить посты.")
                return
                
            alerts_found = 0
            report = ["🧪 РЕЗУЛЬТАТЫ ТЕСТА ТРЕВОГ:\n"] 
            
            for p in posts:
                post_text = p.get("text", "")
                post_id = p.get("id")
                post_date = p.get("date")
                post_photos = p.get("photos", [])
                
                matched_keywords = [kw for kw in ALERT_KEYWORDS if kw.lower() in post_text.lower()]
                has_alert_photo = PHOTO_ALERT_ID in post_photos
                has_clear_photo = PHOTO_CLEAR_ID in post_photos
                
                if matched_keywords or has_alert_photo or has_clear_photo:
                    alerts_found += 1
                    triggers = []
                    if matched_keywords: triggers.append(f"текст ({', '.join(matched_keywords)})")
                    if has_alert_photo: triggers.append("картинка (Тревога)")
                    if has_clear_photo: triggers.append("картинка (Отбой)")
                        
                    short_text = post_text[:80].replace("\n", " ")
                    if not short_text: short_text = "[Только картинка]"
                    else: short_text += "..."
                        
                    report.append(f"🚨 [{post_date}] (ID: {post_id})\n🔍 Триггер: {', '.join(triggers)}\n📝 {short_text}\n")
            
            if alerts_found == 0:
                report.append("✅ Тревог не найдено.")
            else:
                report.append(f"Всего найдено: {alerts_found}")
                
            final_msg = "\n".join(report)
            if len(final_msg) > 4000: final_msg = final_msg[:4000] + "\n... (обрезано)"
            self.send_message(peer_id, final_msg, keyboard=get_main_keyboard())
            return

        if text == "🚨 Статус тревоги":
            self.send_message(peer_id, "✅ Воздушная тревога не объявлена.", keyboard=get_main_keyboard())
            return

        if text == "📰 Новости":
            # Парсер сам отсеет старьё и уже показанное
            news = self.sevsu_site.fetch_news(skip_sent=True)
            
            if not news:
                self.send_message(peer_id, "Пока новых (свежих) новостей нет.", keyboard=get_main_keyboard())
            else:
                news.reverse()
                
                for n in news:
                    title = n.get('title', '')
                    link = n.get('link', '')
                    date = n.get('date', '')
                    description = n.get('description', '')
                    
                    msg = f"📰 Новость СевГУ\n\n🗓 {date}\n\n{title}"
                    if description:
                        msg += f"\n\n{description[:300]}..."
                    msg += f"\n\n🔗 {link}"
                    
                    if self.send_message(peer_id, msg, keyboard=get_main_keyboard()):
                        self.storage.mark_news_sent(link)
                        time.sleep(1)
            return

        if text == "📋 Памятка":
            memo = ("📋 Памятка при воздушной тревоге\n\n1. Не паникуйте.\n2. Проследуйте в укрытие.\n"
                    "3. Если укрытия нет — помещение без окон.\n4. Отойдите от окон.\n5. Не пользуйтесь лифтом.\n"
                    "6. Возьмите документы, телефон, воду.\n7. Дождитесь отбоя.")
            self.send_message(peer_id, memo, keyboard=get_main_keyboard())
            return

        if text == "⚙️ Настройки":
            self.send_message(peer_id, "⚙️ Настройки уведомлений:", keyboard=get_settings_keyboard())
            return

        if text in ("🔔 Тревоги: вкл/выкл", "📨 Новости: вкл/выкл"):
            col = "notify_alerts" if "Тревоги" in text else "notify_news"
            cur = self.storage.conn.cursor()
            cur.execute(f"SELECT {col} FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute(f"UPDATE subscribers SET {col} = ? WHERE user_id = ?", (new_val, user_id))
            self.storage.conn.commit()
            state = "включены ✅" if new_val else "выключены 🔕"
            name = "о тревогах" if "Тревоги" in text else "о новостях"
            self.send_message(peer_id, f"Уведомления {name} {state}.", keyboard=get_settings_keyboard())
            return

        if text == "🗑 Очистить новости":
            count = self.storage.clear_sent_news()
            self.send_message(peer_id, f"🗑 Очищено записей: {count}. Свежие новости можно показать снова.", keyboard=get_settings_keyboard())
            return

        if text == "⬅️ Назад":
            self.send_message(peer_id, "Главное меню:", keyboard=get_main_keyboard())
            return

    # ---------- Основной цикл ----------
    def run(self):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self.process_news, "interval", minutes=30)
        scheduler.start()

        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    self.handle_message(event)
                except Exception as e:
                    logger.exception(f"Ошибка обработки: {e}")

if __name__ == "__main__":
    bot = NotificationBot()
    bot.run()
