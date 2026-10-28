import sqlite3
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def get_race_data_count():
    """レース条件ごとのデータ数を確認"""
    conn = get_connection()

    query = '''
        SELECT course, distance, surface, COUNT(*) as count
        FROM horse_data_dtl
        WHERE course IS NOT NULL AND distance IS NOT NULL AND surface IS NOT NULL
        AND course NOT LIKE '%障%'
        GROUP BY course, distance, surface
        ORDER BY count DESC
    '''

    try:
        cur = conn.execute(query)
        rows = cur.fetchall()

        print("=== レース条件ごとのデータ数 ===\n")

        total_count = 0
        min_threshold = 100  # 最小データ数

        valid_combinations = []

        for row in rows:
            course, distance, surface, count = row
            total_count += count

            if count >= min_threshold:
                valid_combinations.append({
                    'course': course,
                    'distance': distance,
                    'surface': surface,
                    'count': count
                })
                print(f"{course} {surface} {distance}m: {count}件")

        print(f"\n総データ数: {total_count}")
        print(f"データ数{min_threshold}件以上の組み合わせ: {len(valid_combinations)}件")
        print(f"除外された組み合わせ: {len(rows) - len(valid_combinations)}件")

        return valid_combinations

    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        conn.close()

if __name__ == '__main__':
    get_race_data_count()
