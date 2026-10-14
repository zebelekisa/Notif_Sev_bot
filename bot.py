# bot.py
import logging
import time

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from apscheduler.schedulers.background import BackgroundScheduler
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import VK_TOKEN, GROUP_ID, BROADCAST_PEER_ID, CHECK_INTERVAL_MINUTES
from parsers.mchs_parser import MCHSParser
from parsers.sevsu_parser import SevSUParser
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
        self.mchs = MCHSParser(
            rss_url="https://92.mchs.gov.ru/rss",
            keywords=[
                "воздушная тревога", "ракетная опасность", "отбой",
                "опасность", "тревога", "БПЛА",
            ],
        )
        self.sevsu_site = SevSUParser("https://www.sevsu.ru/novosti/rss.php?section=0")

        # Состояние тревоги
        self.current_alert_state = None  # None | "alert" | "all_clear"

    # ---------- Отправка ----------
    def send_message(self, peer_id: int, text: str, keyboard: dict = None):
        """Отправляет сообщение. keyboard — либо словарь, либо None (без клавы)."""
        try:
            self.vk.messages.send(
                peer_id=peer_id,
                message=text,
                keyboard=keyboard if keyboard is not None else get_empty_keyboard(),
                random_id=int(time.time() * 1000),
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в {peer_id}: {e}")

    def broadcast(self, text: str, only_alerts: bool = False, only_news: bool = False):
        """Рассылка в беседу."""
        if BROADCAST_PEER_ID:
            self.send_message(BROADCAST_PEER_ID, text)

    # ---------- Обработка тревог ----------
    def process_alerts(self):
        alerts = self.mchs.fetch_alerts()
        for alert in alerts:
            guid = alert["guid"]
            if self.storage.is_alert_sent(guid):
                continue

            text = (
                f"🚨 **{alert['title']}**\n\n"
                f"{alert['summary'][:500]}\n\n"
                f"🔗 {alert['link']}"
            )

            full = (alert["title"] + " " + alert["summary"]).lower()
            if "отбой" in full and self.current_alert_state == "alert":
                self.current_alert_state = "all_clear"
                text = "✅ **ОТБОЙ ВОЗДУШНОЙ ТРЕВОГИ**\n\n" + text
            elif any(kw in full for kw in ["воздушная тревога", "ракетная опасность"]):
                self.current_alert_state = "alert"
                text = "🚨 **ВОЗДУШНАЯ ТРЕВОГА!**\n\n" + text

            self.broadcast(text, only_alerts=True)
            self.storage.mark_alert_sent(guid)
            logger.info(f"Отправлено оповещение: {alert['title']}")

    # ---------- Обработка новостей ----------
    def process_news(self):
        news = self.sevsu_site.fetch_news()
        logger.info(f"[process_news] RSS вернул {len(news)} новостей")

        if not news:
            logger.warning("[process_news] Новостей нет")
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
                # Обрезаем до 300 символов
                text += f"\n\n{description[:300]}"
                if len(description) > 300:
                    text += "..."
            if date:
                text += f"\n\n🗓 {date}"
            if link:
                text += f"\n🔗 {link}"

            self.broadcast(text, only_news=True)
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

        # === Статус тревоги ===
        if text == "🚨 Статус тревоги":
            if self.current_alert_state == "alert":
                msg = "🚨 Сейчас в Севастополе действует воздушная тревога!"
            else:
                msg = "✅ Воздушная тревога не объявлена."
            self.send_message(peer_id, msg, keyboard=get_main_keyboard())
            return

        # === Новости ===
        if text == "📰 Новости":
            news = self.sevsu_site.fetch_news()
            if not news:
                msg = "Пока новостей нет."
            else:
                parts = ["📰 Последние новости СевГУ:\n"]
                for n in news[:3]:
                    parts.append(f"• {n.get('title', '')[:120]}\n{n.get('link', '')}")
                msg = "\n\n".join(parts)
            self.send_message(peer_id, msg, keyboard=get_main_keyboard())
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
            self.send_message(
                peer_id,
                f"Уведомления о тревогах {state}.",
                keyboard=get_settings_keyboard(),
            )
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
            self.send_message(
                peer_id,
                f"Уведомления о новостях {state}.",
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
        scheduler.add_job(self.process_alerts, "interval", minutes=CHECK_INTERVAL_MINUTES)
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
