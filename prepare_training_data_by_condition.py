import sqlite3
import numpy as np
import pickle
import re
from datetime import datetime, timedelta
from feature_engineering import calculate_horse_features, get_horse_race_history, parse_date, days_between

DB_PATH = 'horse_analysis.db'
MIN_DATA_COUNT = 100

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def get_race_conditions():
    """データ数100件以上のレース条件を取得（JRAコースのみ）"""
    conn = get_connection()

    # JRA主要コースリスト
    jra_courses = ['東京', '中京', '新潟', '中山', '福島', '函館', '札幌', '阪神', '京都', '小倉']

    query = '''
        SELECT course, distance, surface, COUNT(*) as count
        FROM horse_data_dtl
        WHERE course IS NOT NULL AND distance IS NOT NULL AND surface IS NOT NULL
        AND course NOT LIKE '%障%'
        AND course IN ('東京', '中京', '新潟', '中山', '福島', '函館', '札幌', '阪神', '京都', '小倉')
        GROUP BY course, distance, surface
        HAVING count >= ?
        ORDER BY count DESC
    '''

    try:
        cur = conn.execute(query, (MIN_DATA_COUNT,))
        rows = cur.fetchall()

        combinations = []
        for row in rows:
            course, distance, surface, count = row
            # コース名から数字を削除して統一
            course_simple = re.sub(r'[0-9]', '', course)
            combinations.append({
                'course': course_simple,
                'distance': distance,
                'surface': surface,
                'count': count
            })

        print(f"データ数{MIN_DATA_COUNT}件以上の組み合わせ: {len(combinations)}件")
        return combinations

    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        conn.close()

def get_race_group(race_id):
    """特定のrace_idの出走馬を取得"""
    conn = get_connection()
    query = '''
        SELECT horse_id, race_date, finish_position, race_class
        FROM horse_data_dtl
        WHERE race_id = ?
    '''
    try:
        cur = conn.execute(query, (race_id,))
        columns = [description[0] for description in cur.description]
        rows = cur.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error reading race group for race_id={race_id}: {e}")
        data = []
    finally:
        conn.close()
    return data

def get_all_race_ids_by_condition(course, distance, surface, min_horses=3):
    """特定のレース条件のrace_idを取得（コース名は数字削除済みのためLIKE検索）"""
    conn = get_connection()
    query = f'''
        SELECT race_id, COUNT(*) as horse_count
        FROM horse_data_dtl
        WHERE course LIKE ? AND distance = ? AND surface = ?
        GROUP BY race_id
        HAVING horse_count >= {min_horses}
        ORDER BY race_id
    '''
    try:
        # コース名の後にワイルドカードを追加（例：京都 → 京都%）
        cur = conn.execute(query, (f"{course}%", distance, surface))
        rows = cur.fetchall()
        race_ids = [row[0] for row in rows]
    except Exception as e:
        print(f"Error: {e}")
        race_ids = []
    finally:
        conn.close()
    return race_ids

def prepare_training_data_by_condition(course, distance, surface, years_limit=10):
    """特定のレース条件の学習データを準備"""
    race_ids = get_all_race_ids_by_condition(course, distance, surface)

    if not race_ids:
        print(f"  No races found for {course} {surface} {distance}m")
        return {
            'condition': {'features': [], 'targets': []},
            'other': {'features': [], 'targets': []},
        }

    # 直近N年以内のレースIDを取得
    cutoff_date = datetime.now() - timedelta(days=years_limit * 365)

    training_data = {
        'condition': {'features': [], 'targets': []},
        'other': {'features': [], 'targets': []},
    }

    print(f"  Processing {len(race_ids)} races...")

    for i, race_id in enumerate(race_ids, 1):
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(race_ids)} races processed")

        try:
            # そのレースの出走馬を取得
            race_group = get_race_group(race_id)

            if not race_group or len(race_group) == 0:
                continue

            # レース日付を取得
            race_date = race_group[0]['race_date']
            parsed_race_date = parse_date(race_date)
            race_class_value = race_group[0].get('race_class')
            if race_class_value is None:
                continue
            race_class = int(race_class_value)
            if not 0 <= race_class <= 9:
                continue
            model_group = 'condition' if 2 <= race_class <= 4 else 'other'

            # 日付フィルタリング
            if parsed_race_date and parsed_race_date < cutoff_date:
                continue

            # 各馬の特徴量を計算
            for row in race_group:
                horse_id = row['horse_id']
                finish_position = row['finish_position']

                # その馬のレース履歴を取得（今回のレースを除外）
                race_history = get_horse_race_history(horse_id)
                race_history = [r for r in race_history if r.get('race_id') != race_id]

                # 特徴量計算（ターゲットレース条件を渡す）
                features = calculate_horse_features(
                    horse_id, race_history, parsed_race_date,
                    target_race_distance=distance,
                    target_race_surface=surface,
                    target_race_course=course
                )

                if features:
                    # 目的変数：3着以内なら1、それ以外は0
                    target = 1 if finish_position and finish_position <= 3 else 0

                    training_data[model_group]['features'].append(features)
                    training_data[model_group]['targets'].append(target)

        except Exception as e:
            print(f"  Warning: race_id={race_id} error: {e}")
            continue

    for model_group, data in training_data.items():
        features = data['features']
        print(
            f"  {model_group}: {len(features)} samples, "
            f"{len(features[0]) if features else 0} features"
        )
    return training_data

def save_training_data_by_condition(features, targets, course, distance, surface, model_group):
    """学習データを保存"""
    filename = f"training_data_{course}_{surface}_{distance}m_{model_group}.pkl"
    with open(filename, 'wb') as f:
        pickle.dump({'features': features, 'targets': targets}, f)
    print(f"  Saved: {filename}")

if __name__ == '__main__':
    print("学習データ作成を開始します（レース条件ごと、直近10年）...")

    # データ数100件以上のレース条件を取得
    combinations = get_race_conditions()

    if not combinations:
        print("No valid combinations found")
        exit(1)

    print(f"\nTotal combinations to process: {len(combinations)}")

    # 各レース条件ごとに学習データを作成
    for i, combo in enumerate(combinations, 1):
        course = combo['course']
        distance = combo['distance']
        surface = combo['surface']

        print(f"\n[{i}/{len(combinations)}] {course} {surface} {distance}m ({combo['count']} races):")

        training_data = prepare_training_data_by_condition(course, distance, surface, years_limit=10)

        for model_group, data in training_data.items():
            save_training_data_by_condition(
                data['features'],
                data['targets'],
                course,
                distance,
                surface,
                model_group,
            )

    print("\n=== 学習データ作成完了 ===")
