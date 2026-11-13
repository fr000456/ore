import sqlite3
import os

DB_PATH = 'horse_analysis.db'

def add_banushi_column():
    """horse_data_hdテーブルにbanushiカラムを追加"""
    conn = sqlite3.connect(DB_PATH)
    try:
        # カラムが既に存在するか確認
        cur = conn.execute("PRAGMA table_info(horse_data_hd)")
        columns = [row[1] for row in cur.fetchall()]

        if 'banushi' not in columns:
            conn.execute('ALTER TABLE horse_data_hd ADD COLUMN banushi TEXT')
            conn.commit()
            print("banushiカラムを追加しました")
        else:
            print("banushiカラムは既に存在します")
    except Exception as e:
        print(f"エラー: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    add_banushi_column()
