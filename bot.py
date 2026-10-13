# bot.py
import logging
import time
from datetime import datetime

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from apscheduler.schedulers.background import BackgroundScheduler
import json
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import VK_TOKEN, GROUP_ID, BROADCAST_PEER_ID, CHECK_INTERVAL_MINUTES
from parsers.mchs_parser import MCHSParser
from parsers.sevsu_parser import SevSUParser
from parsers.vk_news_parser import VKNewsParser
from storage.db import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

# ===== ВОТ СЮДА — функция клавиатуры =====
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
    """Убирает клавиатуру у пользователя."""
    return VkKeyboard(one_time=False).get_empty_keyboard()

# Основной класс бота
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
        self.sevsu_site = SevSUParser("https://www.sevsu.ru/news/")
        self.sevsu_vk = VKNewsParser(VK_TOKEN, "sevsu")

        # Состояние тревоги (чтобы не дублировать отбой)
        self.current_alert_state = None  # None | "alert" | "all_clear"

    # ---------- Отправка ----------
    def send_message(self, peer_id: int, text: str, keyboard: dict = None):
        try:
            self.vk.messages.send(
            peer_id=peer_id,
            message="👋 Привет! Выберите действие:",
            keyboard=get_main_keyboard(),
            random_id=int(time.time() * 1000),
        )
        except Exception as e:
            logger.error(f"Ошибка отправки в {peer_id}: {e}")

    def broadcast(self, text: str, only_alerts: bool = False, only_news: bool = False):
        """Рассылка всем подписчикам или только в беседу."""
        # Вариант 1: в беседу (если задан BROADCAST_PEER_ID)
        if BROADCAST_PEER_ID:
            self.send_message(BROADCAST_PEER_ID, text)

        # Вариант 2: персонально подписчикам (пока отключено, чтобы не спамить)
        # for user_id, peer_id in self.storage.get_subscribers(only_alerts, only_news):
        #     self.send_message(peer_id or user_id, text)

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

            # Определяем тип: тревога или отбой
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
        # Новости из VK (приоритетный источник)
        news = self.sevsu_vk.fetch_news(count=3)
        if not news:
            # Fallback: парсинг сайта
            news = self.sevsu_site.fetch_news()

        for item in news:
            text = (
                f"📰 **Новости СевГУ**\n\n"
                f"{item.get('title', item.get('text', ''))[:400]}\n\n"
                f"🔗 {item.get('link', '')}"
            )
            self.broadcast(text, only_news=True)
            logger.info(f"Отправлена новость: {item.get('title', '')[:60]}")

    # ---------- Обработка команд от пользователей ----------
    def handle_message(self, event):
        user_id = event.message.from_id
        peer_id = event.message.peer_id
        text = event.message.text.strip()

        # === Кнопка "Начать" и /start ===
        if text.lower() in ("/start", "начать", "start", ""):
            self.storage.add_subscriber(user_id, peer_id)
            self.vk.messages.send(
                peer_id=peer_id,
                message=(
                    "👋 Привет! Я бот уведомлений СевГУ.\n\n"
                    "Выберите действие на клавиатуре ниже."
                ),
                keyboard=get_main_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        # === Кнопка "Статус тревоги" ===
        if text == "🚨 Статус тревоги":
            if self.current_alert_state == "alert":
                msg = "🚨 Сейчас в Севастополе действует воздушная тревога!"
            else:
                msg = "✅ Воздушная тревога не объявлена."
            self.vk.messages.send(
                peer_id=peer_id,
                message=msg,
                keyboard=get_main_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        # === Кнопка "Новости" ===
        if text == "📰 Новости":
            news = self.sevsu_vk.fetch_news(count=3)
            if not news:
                news = self.sevsu_site.fetch_news()
            if not news:
                msg = "Пока новостей нет."
            else:
                parts = ["📰 Последние новости СевГУ:\n"]
                for n in news[:3]:
                    parts.append(f"• {n.get('title','')[:100]}\n{n.get('link','')}")
                msg = "\n\n".join(parts)
            self.vk.messages.send(
                peer_id=peer_id,
                message=msg,
                keyboard=get_main_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        # === Кнопка "Памятка" ===
        if text == "📋 Памятка":
            memo = (
                "📋 Памятка при воздушной тревоге\n\n"
                "1. Не паникуйте.\n"
                "2. Проследуйте в укрытие (подвал, подземный переход).\n"
                "3. Если укрытия нет — помещение без окон, у несущей стены.\n"
                "4. Отойдите от окон.\n"
                "5. Не пользуйтесь лифтом.\n"
                "6. Возьмите документы, телефон, воду.\n"
                "7. Дождитесь отбоя."
            )
            self.vk.messages.send(
                peer_id=peer_id,
                message=memo,
                keyboard=get_main_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        # === Кнопка "Настройки" ===
        if text == "⚙️ Настройки":
            self.vk.messages.send(
                peer_id=peer_id,
                message="⚙️ Настройки уведомлений:",
                keyboard=get_settings_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        # === Кнопки внутри настроек ===
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
            self.vk.messages.send(
                peer_id=peer_id,
                message=f"Уведомления о тревогах {state}.",
                keyboard=get_settings_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

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
            self.vk.messages.send(
                peer_id=peer_id,
                message=f"Уведомления о новостях {state}.",
                keyboard=get_settings_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

        if text == "⬅️ Назад":
            self.vk.messages.send(
                peer_id=peer_id,
                message="Главное меню:",
                keyboard=get_main_keyboard(),
                random_id=int(time.time() * 1000),
            )
            return

    # ---------- Основной цикл ----------
    def run(self):
        # Планировщик: периодическая проверка источников
        scheduler = BackgroundScheduler()
        scheduler.add_job(self.process_alerts, "interval", minutes=CHECK_INTERVAL_MINUTES)
        scheduler.add_job(self.process_news, "interval", minutes=30)
        scheduler.start()
        logger.info("Планировщик запущен. Проверка каждые %s мин.", CHECK_INTERVAL_MINUTES)

        # LongPoll: обработка сообщений
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
