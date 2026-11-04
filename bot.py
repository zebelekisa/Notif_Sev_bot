# bot.py
import logging
import time

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from apscheduler.schedulers.background import BackgroundScheduler
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import VK_TOKEN, GROUP_ID, BROADCAST_PEER_ID, ALERT_KEYWORDS, PHOTO_ALERT_ID, PHOTO_CLEAR_ID, CHECK_INTERVAL_MINUTES, NEWS_CHECK_INTERVAL_MINUTES
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
    keyboard.add_button("🧪 Тест тревог (Губернатор)", color=VkKeyboardColor.SECONDARY)
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
        self.storage = Storage()
        self.sevsu_site = SevSUParser("https://www.sevsu.ru/novosti/rss.php?section=0", storage=self.storage)
        self.governor_parser = GovernorParser()

    def send_message(self, peer_id: int, text: str, keyboard: dict = None) -> int:
        try:
            res = self.vk.messages.send(
                peer_id=peer_id, message=text,
                keyboard=keyboard if keyboard is not None else get_empty_keyboard(),
                random_id=int(time.time() * 1000),
            )
            
            # Безопасное получение ID сообщения
            if isinstance(res, dict):
                return res.get('message_id')
            elif isinstance(res, list):
                return res[0]
            return res
            
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            return None  # Если ошибка, возвращаем None

    def edit_message(self, peer_id: int, msg_id: int, text: str, keyboard: dict = None):
        if not msg_id:
            return
        try:
            self.vk.messages.edit(
                peer_id=peer_id, message_id=msg_id, message=text,
                keyboard=keyboard if keyboard is not None else get_empty_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка редактирования: {e}")

    def send_to_all(self, text: str, only_alerts: bool = False, only_news: bool = False):
        """Рассылка всем подписчикам из базы."""
        subscribers = self.storage.get_subscribers(only_alerts=only_alerts, only_news=only_news)
        for user_id, peer_id in subscribers:
            self.send_message(peer_id, text)
            time.sleep(0.1) # Защита от бана ВК

    def delete_message(self, peer_id: int, message_id: int):
        try:
            self.vk.messages.delete(peer_id=peer_id, message_ids=message_id, delete_for_all=1)
        except Exception:
            pass

    def update_settings_menu(self, peer_id: int, user_id: int, user_msg_id: int = None):
        if user_msg_id:
            self.delete_message(peer_id, user_msg_id)
        old_menu_id = self.storage.get_menu_message(peer_id)
        new_keyboard = get_settings_keyboard(self.storage, user_id)
        
        if old_menu_id:
            try:
                self.vk.messages.edit(peer_id=peer_id, message_id=old_menu_id, message="\u2063", keyboard=new_keyboard)
                return
            except Exception:
                pass
        
        try:
            res = self.vk.messages.send(peer_id=peer_id, message="\u2063", keyboard=new_keyboard, random_id=int(time.time() * 1000))
            new_msg_id = res.get('message_id') if isinstance(res, dict) else (res[0] if isinstance(res, list) else res)
            self.storage.set_menu_message(peer_id, new_msg_id)
        except Exception as e:
            logger.error(f"Ошибка отправки меню: {e}")

    # ---------- Фоновые задачи ----------
    def process_news(self):
        news = self.sevsu_site.fetch_news(skip_sent=True)
        if not news: return

        latest_8 = news[:8]
        latest_8.reverse()

        for item in latest_8:
            text = f"📰 Новость СевГУ\n\n🗓 {item['date']}\n\n{item['title']}"
            if item.get('description'):
                text += f"\n\n{item['description'][:300]}..."
            text += f"\n\n🔗 {item['link']}"

            self.send_to_all(text, only_news=True)
            self.storage.mark_news_sent(item['link'])
            time.sleep(1)

    def process_alerts(self):
        logger.info("Проверка тревог...")
        posts = self.governor_parser.fetch_all_recent(limit=5)
        posts.reverse() 
        
        for p in posts:
            post_id = str(p.get("id"))
            if self.storage.is_alert_sent(post_id):
                continue

            text = p.get("text", "").lower().strip()
            photos = p.get("photos", [])
            
            # 1. Отбой: есть слово "отбой" ИЛИ только картинка без текста
            is_clear = "отбой" in text or (len(photos) > 0 and len(text) == 0)
            
            # 2. Учения: есть слова "учения" или "тренировка"
            is_drill = "учени" in text or "тренировк" in text
            
            # 3. Тревога: есть ключевые слова (из config.py) и это не отбой/учения
            is_alert = any(kw in text for kw in ALERT_KEYWORDS) and not is_clear and not is_drill

            if is_clear:
                msg = f"✅ ОТБОЙ ВОЗДУШНОЙ ТРЕВОГИ\n\n🕒 {p.get('date')}"
                self.send_to_all(msg, only_alerts=True)
                self.storage.mark_alert_sent(post_id)
            elif is_drill:
                msg = f"⚠️ УЧЕНИЯ (НЕ ТРЕВОГА)\n\n🕒 {p.get('date')}\n\nСохраняйте спокойствие."
                self.send_to_all(msg, only_alerts=True)
                self.storage.mark_alert_sent(post_id)
            elif is_alert:
                msg = f"🚨 ВНИМАНИЕ! ВОЗДУШНАЯ ТРЕВОГА!\n\n🕒 {p.get('date')}\n\nПроследуйте в укрытие!\n\n🔗 https://vk.com/wall-{p.get('owner_id', '')}_{post_id}"
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

        # === КНОПКА СТАТУСА ТРЕВОГИ ===
        if text == "🚨 Статус тревоги":
            msg_id = self.send_message(peer_id, "⏳ Проверяю оперативную обстановку...")
            posts = self.governor_parser.fetch_all_recent(limit=5)
            status = "✅ Воздушная тревога не объявлена."
            
            if posts:
                for p in posts: # от новых к старым
                    p_text = p.get("text", "").lower().strip()
                    p_photos = p.get("photos", [])
                    
                    is_clear = "отбой" in p_text or (len(p_photos) > 0 and len(p_text) == 0)
                    is_drill = "учени" in p_text or "тренировк" in p_text
                    is_alert = any(kw in p_text for kw in ALERT_KEYWORDS) and not is_clear and not is_drill
                    
                    if is_clear:
                        status = f"✅ ОТБОЙ ТРЕВОГИ.\n\nДата: {p.get('date')}"
                        break
                    elif is_drill:
                        status = f"⚠️ ИДУТ УЧЕНИЯ.\n\nДата: {p.get('date')}"
                        break
                    elif is_alert:
                        status = f"🚨 ВОЗДУШНАЯ ТРЕВОГА!\n\nОбъявлена: {p.get('date')}\n\nСпуститесь в укрытие!"
                        break
            
            self.edit_message(peer_id, msg_id, status, get_main_keyboard())
            return

        # === ТЕСТОВЫЙ РЕЖИМ ТРЕВОГ ===
        if text.lower() == "/test_alerts" or text == "🧪 Тест тревог (Губернатор)":
            msg_id = self.send_message(peer_id, "⏳ Загружаю посты губернатора...")
            posts = self.governor_parser.fetch_all_recent(limit=30)
            if not posts:
                self.send_message(peer_id, "⚠️ Не удалось загрузить посты.")
                return
                
            alerts_found = 0
            report = ["🧪 РЕЗУЛЬТАТЫ ТЕСТА:\n"] 
            
            for p in posts:
                p_text = p.get("text", "").lower().strip()
                p_photos = p.get("photos", [])
                
                is_clear = "отбой" in p_text or (len(p_photos) > 0 and len(p_text) == 0)
                is_drill = "учени" in p_text or "тренировк" in p_text
                is_alert = any(kw in p_text for kw in ALERT_KEYWORDS) and not is_clear and not is_drill

                if is_alert or is_clear or is_drill:
                    alerts_found += 1
                    status = "🚨 ТРЕВОГА" if is_alert else ("✅ ОТБОЙ" if is_clear else "⚠️ УЧЕНИЯ")
                    short_text = p_text[:50].replace("\n", " ") or "[Только картинка = отбой]"
                    
                    report.append(f"{status} [{p.get('date')}]\n📝 {short_text}...\n")
            
            if alerts_found == 0: report.append("✅ Ничего не найдено.")
            self.edit_message(peer_id, msg_id, "\n".join(report)[:4000], get_main_keyboard())
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
            self.update_settings_menu(peer_id, user_id, event.message.id)
            return

        if "Тревоги: вкл" in text or "Тревоги: выкл" in text:
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_alerts FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute("UPDATE subscribers SET notify_alerts = ? WHERE user_id = ?", (new_val, user_id))
            self.storage.conn.commit()
            self.update_settings_menu(peer_id, user_id, event.message.id)
            return

        if "Новости: вкл" in text or "Новости: выкл" in text:
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_news FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute("UPDATE subscribers SET notify_news = ? WHERE user_id = ?", (new_val, user_id))
            self.storage.conn.commit()
            self.update_settings_menu(peer_id, user_id, event.message.id)
            return

        if text == "🗑 Очистить новости":
            self.storage.clear_sent_news()
            self.update_settings_menu(peer_id, user_id, event.message.id)
            return

        if text == "⬅️ Назад":
            self.delete_message(peer_id, event.message.id)
            old_menu_id = self.storage.get_menu_message(peer_id)
            if old_menu_id: self.delete_message(peer_id, old_menu_id)
            self.send_message(peer_id, "Главное меню:", keyboard=get_main_keyboard())
            return

    # ---------- Запуск ----------
    def run(self):
        scheduler = BackgroundScheduler()
        # Проверка тревог каждые 2 минуты (из конфига)
        scheduler.add_job(self.process_alerts, "interval", minutes=CHECK_INTERVAL_MINUTES)
        # Проверка новостей каждые 5 минут (из конфига)
        scheduler.add_job(self.process_news, "interval", minutes=NEWS_CHECK_INTERVAL_MINUTES) # <--- ИЗМЕНИЛИ ЗДЕСЬ
        scheduler.start()

        logger.info(f"Бот запущен. Тревоги: каждые {CHECK_INTERVAL_MINUTES} мин, Новости: каждые {NEWS_CHECK_INTERVAL_MINUTES} мин.")
        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    self.handle_message(event)
                except Exception as e:
                    logger.exception(f"Ошибка обработки: {e}")

if __name__ == "__main__":
    bot = NotificationBot()
    bot.run()
