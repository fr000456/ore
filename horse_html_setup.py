import sqlite3
import os

DB_PATH = 'horse_html.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_db():
    if not os.path.exists(DB_PATH):
        with get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS horse_html (
                    horse_id INTEGER PRIMARY KEY,
                    html TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    race_count INTEGER DEFAULT 0
                )
            ''')
            print("✅ DB 初期化完了")

if __name__ == '__main__':
    init_db()
