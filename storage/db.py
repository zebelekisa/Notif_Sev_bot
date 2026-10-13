# storage/db.py
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict


class Storage:
    def __init__(self, db_path: str = "bot.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT UNIQUE,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                peer_id INTEGER,
                notify_alerts INTEGER DEFAULT 1,
                notify_news INTEGER DEFAULT 1,
                is_starosta INTEGER DEFAULT 0,
                faculty TEXT,
                group_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS student_status (
                user_id INTEGER PRIMARY KEY,
                peer_id INTEGER,
                status TEXT,              -- 'safe', 'need_help', 'unknown'
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    # --- тревоги ---
    def is_alert_sent(self, guid: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM sent_alerts WHERE guid = ?", (guid,))
        return cur.fetchone() is not None

    def mark_alert_sent(self, guid: str):
        cur = self.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO sent_alerts (guid) VALUES (?)", (guid,))
        self.conn.commit()

    # --- подписчики ---
    def add_subscriber(self, user_id: int, peer_id: int, is_starosta: bool = False,
                       faculty: str = "", group_name: str = ""):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO subscribers
            (user_id, peer_id, is_starosta, faculty, group_name)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, peer_id, int(is_starosta), faculty, group_name))
        self.conn.commit()

    def get_subscribers(self, only_alerts: bool = False, only_news: bool = False):
        cur = self.conn.cursor()
        query = "SELECT user_id, peer_id FROM subscribers WHERE 1=1"
        if only_alerts:
            query += " AND notify_alerts = 1"
        if only_news:
            query += " AND notify_news = 1"
        cur.execute(query)
        return cur.fetchall()

    # --- статус студентов (для подсчёта во время тревоги) ---
    def set_status(self, user_id: int, peer_id: int, status: str):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO student_status (user_id, peer_id, status, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, peer_id, status))
        self.conn.commit()

    def count_by_status(self) -> Dict[str, int]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT status, COUNT(*) FROM student_status GROUP BY status
        """)
        return dict(cur.fetchall())
