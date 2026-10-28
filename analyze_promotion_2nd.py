import sqlite3
import numpy as np
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

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

def analyze_promotion_2nd():
    """昇級二戦目の成績を分析"""
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

    for i, horse_id in enumerate(horse_ids):
        if i % 1000 == 0:
            print(f"進捗: {i}/{len(horse_ids)} 馬を処理中")

        race_history = get_horse_race_history(horse_id)
        if len(race_history) >= 3:
            promotion_2nd_races = identify_promotion_2nd(race_history)
            all_promotion_2nd.extend(promotion_2nd_races)

    print(f"\n昇級二戦目のレース数: {len(all_promotion_2nd)}")

    # 全体の3着以内率
    top3_count = sum(1 for r in all_promotion_2nd if r['current'].get('finish_position') and r['current'].get('finish_position') <= 3)
    overall_top3_rate = top3_count / len(all_promotion_2nd) if all_promotion_2nd else 0

    print(f"\n=== 全体統計 ===")
    print(f"昇級二戦目の3着以内率: {overall_top3_rate:.4f} ({top3_count}/{len(all_promotion_2nd)})")

    # 前走（昇級一戦目）の条件別集計
    print(f"\n=== 前走（昇級一戦目）の条件別集計 ===")

    # 前走着順 vs 今回着順
    prev_finish_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev_finish = r['prev'].get('finish_position')
        current_finish = r['current'].get('finish_position')
        if prev_finish and current_finish:
            if current_finish <= 3:
                prev_finish_vs_current[prev_finish]['top3'] += 1
            prev_finish_vs_current[prev_finish]['total'] += 1

    print("\n前走着順別の今回3着以内率:")
    for finish in sorted(prev_finish_vs_current.keys()):
        total = prev_finish_vs_current[finish]['total']
        top3 = prev_finish_vs_current[finish]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  前走着順{finish}: {rate:.4f} ({top3}/{total})")

    # 前走コース vs 今回コース
    prev_course_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev_course = r['prev'].get('course')
        current_course = r['current'].get('course')
        current_finish = r['current'].get('finish_position')
        if prev_course and current_course and current_finish:
            key = f"{prev_course}→{current_course}"
            if current_finish <= 3:
                prev_course_vs_current[key]['top3'] += 1
            prev_course_vs_current[key]['total'] += 1

    print("\n前走コース→今回コース別の3着以内率:")
    for key in sorted(prev_course_vs_current.keys()):
        total = prev_course_vs_current[key]['total']
        top3 = prev_course_vs_current[key]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 前走距離 vs 今回距離
    prev_distance_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev_distance = r['prev'].get('distance')
        current_distance = r['current'].get('distance')
        current_finish = r['current'].get('finish_position')
        if prev_distance and current_distance and current_finish:
            key = f"{prev_distance}m→{current_distance}m"
            if current_finish <= 3:
                prev_distance_vs_current[key]['top3'] += 1
            prev_distance_vs_current[key]['total'] += 1

    print("\n前走距離→今回距離別の3着以内率:")
    for key in sorted(prev_distance_vs_current.keys()):
        total = prev_distance_vs_current[key]['total']
        top3 = prev_distance_vs_current[key]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 前々走（昇級した1着のレース）の条件別集計
    print(f"\n=== 前々走（昇級した1着のレース）の条件別集計 ===")

    # 前々走着順（常に1着）vs 今回着順
    prev2_finish_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_finish = r['prev2'].get('finish_position')
        current_finish = r['current'].get('finish_position')
        if prev2_finish and current_finish:
            if current_finish <= 3:
                prev2_finish_vs_current[prev2_finish]['top3'] += 1
            prev2_finish_vs_current[prev2_finish]['total'] += 1

    print("\n前々走着順別の今回3着以内率:")
    for finish in sorted(prev2_finish_vs_current.keys()):
        total = prev2_finish_vs_current[finish]['total']
        top3 = prev2_finish_vs_current[finish]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  前々走着順{finish}: {rate:.4f} ({top3}/{total})")

    # 前々走コース vs 今回コース
    prev2_course_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_course = r['prev2'].get('course')
        current_course = r['current'].get('course')
        current_finish = r['current'].get('finish_position')
        if prev2_course and current_course and current_finish:
            key = f"{prev2_course}→{current_course}"
            if current_finish <= 3:
                prev2_course_vs_current[key]['top3'] += 1
            prev2_course_vs_current[key]['total'] += 1

    print("\n前々走コース→今回コース別の3着以内率:")
    for key in sorted(prev2_course_vs_current.keys()):
        total = prev2_course_vs_current[key]['total']
        top3 = prev2_course_vs_current[key]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 前々走距離 vs 今回距離
    prev2_distance_vs_current = defaultdict(lambda: {'top3': 0, 'total': 0})
    for r in all_promotion_2nd:
        prev2_distance = r['prev2'].get('distance')
        current_distance = r['current'].get('distance')
        current_finish = r['current'].get('finish_position')
        if prev2_distance and current_distance and current_finish:
            key = f"{prev2_distance}m→{current_distance}m"
            if current_finish <= 3:
                prev2_distance_vs_current[key]['top3'] += 1
            prev2_distance_vs_current[key]['total'] += 1

    print("\n前々走距離→今回距離別の3着以内率:")
    for key in sorted(prev2_distance_vs_current.keys()):
        total = prev2_distance_vs_current[key]['total']
        top3 = prev2_distance_vs_current[key]['top3']
        rate = top3 / total if total > 0 else 0
        print(f"  {key}: {rate:.4f} ({top3}/{total})")

    # 相関係数の計算（簡易版）
    print(f"\n=== 相関係数（簡易版）===")

    # 前走着順と今回着順の相関
    prev_finishes = []
    current_finishes = []
    for r in all_promotion_2nd:
        pf = r['prev'].get('finish_position')
        cf = r['current'].get('finish_position')
        if pf is not None and cf is not None:
            prev_finishes.append(pf)
            current_finishes.append(cf)

    if len(prev_finishes) > 1 and len(prev_finishes) == len(current_finishes):
        correlation = np.corrcoef(prev_finishes, current_finishes)[0, 1]
        print(f"前走着順と今回着順の相関係数: {correlation:.4f}")

    # 前走距離と今回着順の相関
    prev_distances = []
    current_finishes2 = []
    for r in all_promotion_2nd:
        pd = r['prev'].get('distance')
        cf = r['current'].get('finish_position')
        if pd is not None and cf is not None:
            prev_distances.append(pd)
            current_finishes2.append(cf)

    if len(prev_distances) > 1 and len(prev_distances) == len(current_finishes2):
        correlation = np.corrcoef(prev_distances, current_finishes2)[0, 1]
        print(f"前走距離と今回着順の相関係数: {correlation:.4f}")

    # 結果をファイルに保存
    with open('promotion_2nd_analysis.txt', 'w', encoding='utf-8') as f:
        f.write("=== 昇級二戦目の成績分析 ===\n\n")
        f.write(f"全体統計:\n")
        f.write(f"  昇級二戦目のレース数: {len(all_promotion_2nd)}\n")
        f.write(f"  3着以内率: {overall_top3_rate:.4f} ({top3_count}/{len(all_promotion_2nd)})\n\n")

        f.write("前走着順別の今回3着以内率:\n")
        for finish in sorted(prev_finish_vs_current.keys()):
            total = prev_finish_vs_current[finish]['total']
            top3 = prev_finish_vs_current[finish]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  前走着順{finish}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n前走コース→今回コース別の3着以内率:\n")
        for key in sorted(prev_course_vs_current.keys()):
            total = prev_course_vs_current[key]['total']
            top3 = prev_course_vs_current[key]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n前走距離→今回距離別の3着以内率:\n")
        for key in sorted(prev_distance_vs_current.keys()):
            total = prev_distance_vs_current[key]['total']
            top3 = prev_distance_vs_current[key]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n前々走着順別の今回3着以内率:\n")
        for finish in sorted(prev2_finish_vs_current.keys()):
            total = prev2_finish_vs_current[finish]['total']
            top3 = prev2_finish_vs_current[finish]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  前々走着順{finish}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n前々走コース→今回コース別の3着以内率:\n")
        for key in sorted(prev2_course_vs_current.keys()):
            total = prev2_course_vs_current[key]['total']
            top3 = prev2_course_vs_current[key]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        f.write("\n前々走距離→今回距離別の3着以内率:\n")
        for key in sorted(prev2_distance_vs_current.keys()):
            total = prev2_distance_vs_current[key]['total']
            top3 = prev2_distance_vs_current[key]['top3']
            rate = top3 / total if total > 0 else 0
            f.write(f"  {key}: {rate:.4f} ({top3}/{total})\n")

        if len(prev_finishes) > 1 and len(prev_finishes) == len(current_finishes):
            correlation = np.corrcoef(prev_finishes, current_finishes)[0, 1]
            f.write(f"\n前走着順と今回着順の相関係数: {correlation:.4f}\n")

        if len(prev_distances) > 1 and len(prev_distances) == len(current_finishes2):
            correlation = np.corrcoef(prev_distances, current_finishes2)[0, 1]
            f.write(f"前走距離と今回着順の相関係数: {correlation:.4f}\n")

    print("\n分析結果を保存しました: promotion_2nd_analysis.txt")

if __name__ == '__main__':
    analyze_promotion_2nd()
