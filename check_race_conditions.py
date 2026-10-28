import sqlite3
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def get_race_conditions():
    """データベースからレース条件の組み合わせを取得（障害除外）"""
    conn = get_connection()

    query = '''
        SELECT DISTINCT course, distance, surface
        FROM horse_data_dtl
        WHERE course IS NOT NULL AND distance IS NOT NULL AND surface IS NOT NULL
        AND course NOT LIKE '%障%'
        ORDER BY course, distance, surface
    '''

    try:
        cur = conn.execute(query)
        rows = cur.fetchall()

        # 競馬場ごとの距離・馬場の組み合わせを集計
        conditions = defaultdict(lambda: {'芝': set(), 'ダート': set()})

        for row in rows:
            course, distance, surface = row
            if course and distance and surface:
                conditions[course][surface].add(distance)

        # 結果を表示
        print("=== レース条件の組み合わせ（障害除外）===\n")

        total_combinations = 0
        for course in sorted(conditions.keys()):
            print(f"【{course}】")
            for surface in ['芝', 'ダート']:
                distances = sorted(conditions[course].get(surface, []))
                if distances:
                    print(f"  {surface}: {distances}")
                    total_combinations += len(distances)
            print()

        print(f"総組み合わせ数: {total_combinations}")

        # 組み合わせリストを保存
        combinations = []
        for course in conditions:
            for surface in ['芝', 'ダート']:
                for distance in conditions[course].get(surface, []):
                    combinations.append({
                        'course': course,
                        'surface': surface,
                        'distance': distance
                    })

        print(f"\n組み合わせリスト（{len(combinations)}件）:")
        for combo in combinations:
            print(f"  {combo['course']} {combo['surface']} {combo['distance']}m")

        return combinations

    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        conn.close()

if __name__ == '__main__':
    get_race_conditions()
