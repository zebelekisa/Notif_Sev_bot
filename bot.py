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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
        # VK
        self.vk_session = vk_api.VkApi(token=VK_TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, GROUP_ID)

        # Хранилище
        self.storage = Storage()

        # Парсеры
        self.sevsu_site = SevSUParser(
            "https://www.sevsu.ru/novosti/rss.php?section=0",
            storage=self.storage,
        )
        self.governor_parser = GovernorParser()

    # ---------- Отправка ----------
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

    def broadcast(self, text: str, only_alerts: bool = False, only_news: bool = False) -> bool:
        if BROADCAST_PEER_ID:
            return self.send_message(BROADCAST_PEER_ID, text)
        return False

    # ---------- Обработка новостей ----------
    def process_news(self):
        news = self.sevsu_site.fetch_news(skip_sent=True)
        logger.info(f"[process_news] Новых новостей: {len(news)}")

        if not news:
            logger.info("[process_news] Нечего рассылать")
            return

        for item in news[:3]:
            title = item.get("title", "")
            link = item.get("link", "")
            description = item.get("description", "")
            date = item.get("date", "")
            category = item.get("category", "")

            header = "📰 Новости СевГУ"
            if category:
                header += f" · {category}"

            text = f"{header}\n\n**{title}**"
            if description:
                text += f"\n\n{description[:300]}"
                if len(description) > 300:
                    text += "..."
            if date:
                text += f"\n\n🗓 {date}"
            if link:
                text += f"\n🔗 {link}"

            if self.broadcast(text, only_news=True):
                self.storage.mark_news_sent(link)
                logger.info(f"Отправлена новость: {title[:60]}")

    # ---------- Обработка команд ----------
    def handle_message(self, event):
        user_id = event.message.from_id
        peer_id = event.message.peer_id
        text = event.message.text.strip()

        # === /start ===
        if text.lower() in ("/start", "начать", "start", ""):
            self.storage.add_subscriber(user_id, peer_id)
            self.send_message(
                peer_id,
                "👋 Привет! Я бот уведомлений СевГУ.\n\n"
                "Выберите действие на клавиатуре ниже.",
                keyboard=get_main_keyboard(),
            )
            return

        # === ТЕСТОВЫЙ РЕЖИМ ТРЕВОГ ===
        if text.lower() == "/test_alerts" or text == "🧪 Тест тревог (Губернатор)":
            self.send_message(peer_id, "⏳ Загружаю последние посты губернатора и ищу тревоги...")
            posts = self.governor_parser.fetch_all_recent(limit=30)
            
            if not posts:
                self.send_message(peer_id, "⚠️ Не удалось загрузить посты.")
                return
                
            alerts_found = 0
            report = ["🧪 РЕЗУЛЬТАТЫ ТЕСТА ТРЕВОГ (последние 30 постов):\n"] 
            
            for p in posts:
                post_text = p.get("text", "")
                post_id = p.get("id")
                post_date = p.get("date")
                post_photos = p.get("photos", [])
                
                # 1. Ищем по ключевым словам в тексте
                matched_keywords = [kw for kw in ALERT_KEYWORDS if kw.lower() in post_text.lower()]
                
                # 2. Ищем по ID картинок
                has_alert_photo = PHOTO_ALERT_ID in post_photos
                has_clear_photo = PHOTO_CLEAR_ID in post_photos
                
                # Если нашли текст ИЛИ нужную картинку
                if matched_keywords or has_alert_photo or has_clear_photo:
                    alerts_found += 1
                    
                    triggers = []
                    if matched_keywords:
                        triggers.append(f"текст ({', '.join(matched_keywords)})")
                    if has_alert_photo:
                        triggers.append("картинка (Тревога)")
                    if has_clear_photo:
                        triggers.append("картинка (Отбой)")
                        
                    short_text = post_text[:80].replace("\n", " ")
                    if not short_text:
                        short_text = "[Пост без текста, только картинка]"
                    else:
                        short_text += "..."
                        
                    report.append(
                        f"🚨 [{post_date}] (ID: {post_id})\n"
                        f"🔍 Триггер: {', '.join(triggers)}\n"
                        f"📝 {short_text}\n"
                    )
            
            if alerts_found == 0:
                report.append("✅ В последних 30 постах тревог не найдено.")
            else:
                report.append(f"Всего найдено постов с триггерами: {alerts_found}")
                
            final_msg = "\n".join(report)
            if len(final_msg) > 4000:
                final_msg = final_msg[:4000] + "\n... (сообщение обрезано)"
                
            self.send_message(peer_id, final_msg, keyboard=get_main_keyboard())
            return

        # === Статус тревоги ===
        if text == "🚨 Статус тревоги":
            self.send_message(peer_id, "✅ Воздушная тревога не объявлена.\n\n"
                "ℹ️ Функция в разработке: подключение к оперативному источнику тревог.",
                keyboard=get_main_keyboard(),
            )
            return

        # === Новости ===
        if text == "📰 Новости":
            # Запрашиваем ТОЛЬКО те новости, которых нет в БД
            news = self.sevsu_site.fetch_news(skip_sent=True)
            
            if not news:
                msg = "Пока новых новостей нет. Все актуальные новости уже показаны."
                self.send_message(peer_id, msg, keyboard=get_main_keyboard())
            else:
                for n in news[:3]:
                    title = n.get('title', '')[:120]
                    link = n.get('link', '')
                    msg = f"📰 Новость СевГУ:\n\n{title}\n{link}"
                    
                    if self.send_message(peer_id, msg, keyboard=get_main_keyboard()):
                        self.storage.mark_news_sent(link)
            return

        # === Памятка ===
        if text == "📋 Памятка":
            memo = (
                "📋 **Памятка при воздушной тревоге**\n\n"
                "1. Не паникуйте. Сохраняйте спокойствие.\n"
                "2. Проследуйте в ближайшее укрытие (подвал, цокольный этаж, "
                "подземный переход).\n"
                "3. Если укрытия нет — перейдите в помещение без окон, "
                "сядьте на пол у несущей стены.\n"
                "4. Отойдите от окон и стеклянных поверхностей.\n"
                "5. Не пользуйтесь лифтом.\n"
                "6. Возьмите с собой документы, телефон, воду.\n"
                "7. Дождитесь отбоя тревоги. Не выходите до сигнала «Отбой»."
            )
            self.send_message(peer_id, memo, keyboard=get_main_keyboard())
            return

        # === Настройки ===
        if text == "⚙️ Настройки":
            self.send_message(
                peer_id,
                "⚙️ Настройки уведомлений:",
                keyboard=get_settings_keyboard(),
            )
            return

        # === Тумблер тревог ===
        if text == "🔔 Тревоги: вкл/выкл":
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_alerts FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute(
                "UPDATE subscribers SET notify_alerts = ? WHERE user_id = ?",
                (new_val, user_id),
            )
            self.storage.conn.commit()
            state = "включены ✅" if new_val else "выключены 🔕"
            self.send_message(peer_id, f"Уведомления о тревогах {state}.", keyboard=get_settings_keyboard())
            return

        # === Тумблер новостей ===
        if text == "📨 Новости: вкл/выкл":
            cur = self.storage.conn.cursor()
            cur.execute("SELECT notify_news FROM subscribers WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            new_val = 0 if (row and row[0]) else 1
            self.storage.conn.execute(
                "UPDATE subscribers SET notify_news = ? WHERE user_id = ?",
                (new_val, user_id),
            )
            self.storage.conn.commit()
            state = "включены ✅" if new_val else "выключены 🔕"
            self.send_message(peer_id, f"Уведомления о новостях {state}.", keyboard=get_settings_keyboard())
            return

        # === Очистка новостей ===
        if text == "🗑 Очистить новости":
            count = self.storage.clear_sent_news()
            self.send_message(
                peer_id,
                f"🗑 История отправленных новостей очищена (удалено записей: {count}).\n"
                "При следующем нажатии на «📰 Новости» они будут показаны снова.",
                keyboard=get_settings_keyboard(),
            )
            return

        # === Назад ===
        if text == "⬅️ Назад":
            self.send_message(peer_id, "Главное меню:", keyboard=get_main_keyboard())
            return

    # ---------- Основной цикл ----------
    def run(self):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self.process_news, "interval", minutes=30)
        scheduler.start()
        logger.info("Планировщик запущен. Проверка каждые %s мин.", CHECK_INTERVAL_MINUTES)

        logger.info("Бот запущен. Ожидание событий...")
        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    self.handle_message(event)
                except Exception as e:
                    logger.exception(f"Ошибка обработки сообщения: {e}")


if __name__ == "__main__":
    bot = NotificationBot()
    bot.run()
