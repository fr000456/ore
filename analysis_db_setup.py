import sqlite3
import os

DB_PATH = 'horse_analysis.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_analysis_db():
    with get_connection() as conn:
        # 既存のデータ確認
        try:
            cur = conn.execute('SELECT COUNT(*) FROM horse_data_hd')
            horse_count = cur.fetchone()[0]
            cur = conn.execute('SELECT COUNT(*) FROM horse_data_dtl')
            race_count = cur.fetchone()[0]

            if horse_count > 0 or race_count > 0:
                print(f"⚠️ 既存データが存在します:")
                print(f"   horse_data_hd: {horse_count}件")
                print(f"   horse_data_dtl: {race_count}件")
                confirm = input("⚠️ 既存テーブルを削除して再作成しますか？ (yes/no): ")
                if confirm.lower() != 'yes':
                    print("❌ 処理をキャンセルしました")
                    return
        except sqlite3.OperationalError:
            # テーブルが存在しない場合はそのまま続行
            pass

        # 既存のテーブルを削除
        conn.execute('DROP TABLE IF EXISTS horse_data_dtl')
        conn.execute('DROP TABLE IF EXISTS horse_data_hd')
        print("🗑️ 既存テーブル削除完了")

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
                margin REAL,
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
