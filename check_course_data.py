import sqlite3

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def check_course_data():
    """courseカラムのデータを確認"""
    conn = get_connection()

    query = '''
        SELECT DISTINCT course
        FROM horse_data_dtl
        WHERE course IS NOT NULL
        ORDER BY course
    '''

    try:
        cur = conn.execute(query)
        rows = cur.fetchall()

        print("=== courseカラムの値の一覧 ===\n")

        major_courses = ['東京', '中山', '京都', '阪神', '新潟', '中京', '札幌', '函館', '福島', '小倉']

        for row in rows:
            course = row[0]
            # 主要な競馬場名が含まれているかチェック
            is_major = any(major in course for major in major_courses)
            marker = "★" if is_major else "  "
            print(f"{marker} {course}")

        print(f"\n総計: {len(rows)}種類")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    check_course_data()
