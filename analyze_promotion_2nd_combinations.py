import sqlite3
import numpy as np
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def is_fastest_last_3f(conn, race_id, horse_id):
    """指定のrace_idで、指定のhorse_idがlast_3f最速かどうかを判定"""
    cursor = conn.execute(f'''
        SELECT horse_id, last_3f FROM horse_data_dtl
        WHERE race_id = {race_id} AND last_3f IS NOT NULL
        ORDER BY last_3f ASC
    ''')
    horses = cursor.fetchall()
    if not horses:
        return False
    # 最速の馬が該当馬かどうか
    return horses[0][0] == horse_id

def get_horse_race_history(horse_id):
    """特定の馬のレース履歴を取得"""
    conn = get_connection()
    escaped_id = horse_id.replace("'", "''")
    query = f'''
        SELECT * FROM horse_data_dtl
        WHERE horse_id = '{escaped_id}'
        ORDER BY race_date DESC
    '''
    try:
        cur = conn.execute(query)
        columns = [description[0] for description in cur.description]
        rows = cur.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error: {e}")
        data = []
    finally:
        conn.close()
    return data

def identify_promotion_2nd(race_history):
    """昇級二戦目のレースを特定（シンプル版：1着→次の2走）"""
    promotion_2nd_races = []

    for i in range(len(race_history) - 2):
        # 前々走（i+2）が1着かどうか
        prev2_finish = race_history[i+2].get('finish_position')
        if prev2_finish != 1:
            continue

        # 前走（i+1）を昇級一戦目
        # 今回（i）を昇級二戦目
        # 前々走（i+2）を昇級した1着のレース

        promotion_2nd_data = {
            'current': race_history[i],  # 昇級二戦目
            'prev': race_history[i+1],  # 昇級一戦目
            'prev2': race_history[i+2]  # 昇級した1着のレース
        }
        promotion_2nd_races.append(promotion_2nd_data)

    return promotion_2nd_races

def analyze_combinations():
    """条件の組み合わせを分析"""
    conn = get_connection()

    # 全馬IDを取得
    query = '''
        SELECT DISTINCT horse_id FROM horse_data_dtl
    '''
    cur = conn.execute(query)
    horse_ids = [row[0] for row in cur.fetchall()]

    print(f"全馬数: {len(horse_ids)}")

    # 昇級二戦目のレースを収集
    all_promotion_2nd = []
    conn = get_connection()

    for i, horse_id in enumerate(horse_ids):
        if i % 1000 == 0:
            print(f"進捗: {i}/{len(horse_ids)} 馬を処理中")

        race_history = get_horse_race_history(horse_id)
        if len(race_history) >= 3:
            promotion_2nd_races = identify_promotion_2nd(race_history)

            # 上がり3ハロン最速フラグを追加
            for r in promotion_2nd_races:
                prev_race_id = r['prev'].get('race_id')
                prev_horse_id = r['prev'].get('horse_id')
                if prev_race_id and prev_horse_id:
                    r['prev_is_fastest_last_3f'] = is_fastest_last_3f(conn, prev_race_id, prev_horse_id)
                else:
                    r['prev_is_fastest_last_3f'] = False

            all_promotion_2nd.extend(promotion_2nd_races)

    conn.close()

    print(f"\n昇級二戦目のレース数: {len(all_promotion_2nd)}")

    # 条件の組み合わせを分析
    print(f"\n=== 条件の組み合わせ分析 ===")

    # JRA主要コースリスト
    jra_courses = ['東京', '中山', '京都', '阪神', '新潟', '中京', '札幌', '函館', '福島', '小倉']

    # 組み合わせ1: 前々走距離 → 前走距離 → 昇級二戦目距離（JRAのみ）
    combo1 = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_distance = r['prev2'].get('distance')
        prev_distance = r['prev'].get('distance')
        current_distance = r['current'].get('distance')
        current_finish = r['current'].get('finish_position')

        # JRAコースのみを対象
        prev2_course = r['prev2'].get('course')
        prev_course = r['prev'].get('course')
        current_course = r['current'].get('course')

        prev2_jra = any(course in prev2_course for course in jra_courses) if prev2_course else False
        prev_jra = any(course in prev_course for course in jra_courses) if prev_course else False
        current_jra = any(course in current_course for course in jra_courses) if current_course else False

        if prev2_distance and prev_distance and current_distance and current_finish and prev2_jra and prev_jra and current_jra:
            key = f"{prev2_distance}m → {prev_distance}m → {current_distance}m"
            if current_finish <= 3:
                combo1[key]['top3'] += 1
            combo1[key]['total'] += 1

    print("\n=== 前々走距離 → 前走距離 → 昇級二戦目距離（JRAのみ）===")
    sorted_combo1 = sorted(combo1.items(), key=lambda x: x[1]['total'], reverse=True)
    sorted_combo1 = [x for x in sorted_combo1 if x[1]['total'] >= 10]  # 10件以上のみ
    sorted_combo1 = sorted(sorted_combo1, key=lambda x: x[1]['top3'] / x[1]['total'], reverse=True)

    for key, data in sorted_combo1[:20]:
        total = data['total']
        top3 = data['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 組み合わせ2: 前々走コース → 前走コース → 昇級二戦目コース（JRAのみ）
    combo2 = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_course = r['prev2'].get('course')
        prev_course = r['prev'].get('course')
        current_course = r['current'].get('course')
        current_finish = r['current'].get('finish_position')

        if prev2_course and prev_course and current_course and current_finish:
            # JRAコースのみを対象
            prev2_jra = any(course in prev2_course for course in jra_courses)
            prev_jra = any(course in prev_course for course in jra_courses)
            current_jra = any(course in current_course for course in jra_courses)

            if prev2_jra and prev_jra and current_jra:
                # コース名を簡略化（数字などを削除）
                import re
                prev2_course_simple = re.sub(r'[0-9]', '', prev2_course)
                prev_course_simple = re.sub(r'[0-9]', '', prev_course)
                current_course_simple = re.sub(r'[0-9]', '', current_course)

                key = f"{prev2_course_simple} → {prev_course_simple} → {current_course_simple}"
                if current_finish <= 3:
                    combo2[key]['top3'] += 1
                combo2[key]['total'] += 1

    print("\n=== 前々走コース → 前走コース → 昇級二戦目コース（JRAのみ）===")
    sorted_combo2 = sorted(combo2.items(), key=lambda x: x[1]['total'], reverse=True)
    sorted_combo2 = [x for x in sorted_combo2 if x[1]['total'] >= 10]  # 10件以上のみ
    sorted_combo2 = sorted(sorted_combo2, key=lambda x: x[1]['top3'] / x[1]['total'], reverse=True)

    for key, data in sorted_combo2[:20]:
        total = data['total']
        top3 = data['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 組み合わせ3: 距離 + コース + 芝ダートの複合パターン（JRAのみ）
    combo3 = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_distance = r['prev2'].get('distance')
        prev_distance = r['prev'].get('distance')
        current_distance = r['current'].get('distance')
        prev2_course = r['prev2'].get('course')
        prev_course = r['prev'].get('course')
        current_course = r['current'].get('course')
        prev2_surface = r['prev2'].get('surface')
        prev_surface = r['prev'].get('surface')
        current_surface = r['current'].get('surface')
        current_finish = r['current'].get('finish_position')

        if prev2_distance and prev_distance and current_distance and prev2_course and prev_course and current_course and current_finish:
            # JRAコースのみを対象
            prev2_jra = any(course in prev2_course for course in jra_courses)
            prev_jra = any(course in prev_course for course in jra_courses)
            current_jra = any(course in current_course for course in jra_courses)

            if prev2_jra and prev_jra and current_jra:
                import re
                prev2_course_simple = re.sub(r'[0-9]', '', prev2_course)
                prev_course_simple = re.sub(r'[0-9]', '', prev_course)
                current_course_simple = re.sub(r'[0-9]', '', current_course)

                # 芝ダートを追加
                prev2_surface_str = prev2_surface if prev2_surface else ''
                prev_surface_str = prev_surface if prev_surface else ''
                current_surface_str = current_surface if current_surface else ''

                key = f"{prev2_distance}m({prev2_course_simple}{prev2_surface_str}) → {prev_distance}m({prev_course_simple}{prev_surface_str}) → {current_distance}m({current_course_simple}{current_surface_str})"
                if current_finish <= 3:
                    combo3[key]['top3'] += 1
                combo3[key]['total'] += 1

    print("\n=== 距離 + コース + 芝ダートの複合パターン（JRAのみ）===")
    sorted_combo3 = sorted(combo3.items(), key=lambda x: x[1]['total'], reverse=True)
    sorted_combo3 = [x for x in sorted_combo3 if x[1]['total'] >= 10]  # 10件以上のみ
    sorted_combo3 = sorted(sorted_combo3, key=lambda x: x[1]['top3'] / x[1]['total'], reverse=True)

    for key, data in sorted_combo3[:20]:
        total = data['total']
        top3 = data['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 結果をファイルに保存
    with open('promotion_2nd_combinations.txt', 'w', encoding='utf-8') as f:
        f.write("=== 昇級二戦目の条件組み合わせ分析（JRAのみ）===\n\n")

        f.write("=== 前々走距離 → 前走距離 → 昇級二戦目距離（JRAのみ）===\n")
        for key, data in sorted_combo1[:20]:
            total = data['total']
            top3 = data['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n=== 前々走コース → 前走コース → 昇級二戦目コース（JRAのみ）===\n")
        for key, data in sorted_combo2[:20]:
            total = data['total']
            top3 = data['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n=== 距離 + コース + 芝ダートの複合パターン（JRAのみ）===\n")
        for key, data in sorted_combo3[:20]:
            total = data['total']
            top3 = data['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

    print("\n分析結果を保存しました: promotion_2nd_combinations.txt")

if __name__ == '__main__':
    analyze_combinations()
