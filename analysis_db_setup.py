import sqlite3
import os

DB_PATH = 'horse_analysis.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_analysis_db():
    if not os.path.exists(DB_PATH):
        with get_connection() as conn:
            # horse_data_hd テーブル作成（馬の基本情報）
            conn.execute('''
                CREATE TABLE horse_data_hd (
                    horse_id INTEGER PRIMARY KEY,
                    horse_name TEXT NOT NULL,
                    sire TEXT,
                    dam TEXT
                )
            ''')
            print("✅ horse_data_hd テーブル作成完了")

            # horse_data_dtl テーブル作成（馬ごとの過去レース情報）
            conn.execute('''
                CREATE TABLE horse_data_dtl (
                    horse_id INTEGER NOT NULL,
                    race_number INTEGER NOT NULL,
                    race_date TEXT NOT NULL,
                    course TEXT,
                    race_id INTEGER NOT NULL,
                    field_size INTEGER,
                    gate INTEGER,
                    horse_number INTEGER,
                    popularity INTEGER,
                    finish_position INTEGER,
                    jockey TEXT,
                    carried_weight REAL,
                    surface TEXT,
                    distance INTEGER,
                    track_condition TEXT,
                    finish_time TEXT,
                    margin INTEGER,
                    passing_order TEXT,
                    pace TEXT,
                    last_3f REAL,
                    horse_weight INTEGER,
                    PRIMARY KEY (horse_id, race_id),
                    FOREIGN KEY (horse_id) REFERENCES horse_data_hd(horse_id)
                )
            ''')
            print("✅ horse_data_dtl テーブル作成完了")
            print("✅ 解析用DB初期化完了")

if __name__ == '__main__':
    init_analysis_db()
