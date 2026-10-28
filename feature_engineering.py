import re
import sqlite3
from datetime import datetime
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

SURFACE_FILTERED_FINISH_FEATURES = {
    'last_finish',
    'recent_3_avg_finish',
    'recent_3_top3_rate',
    'recent_3_avg_finish_turf',
    'recent_3_top3_rate_turf',
    'recent_3_avg_finish_dirt',
    'recent_3_top3_rate_dirt',
    'recent_5_avg_finish',
    'recent_5_top3_rate',
    'recent_5_avg_finish_turf',
    'recent_5_top3_rate_turf',
    'recent_5_avg_finish_dirt',
    'recent_5_top3_rate_dirt',
}
NULL_AS_NAN_FEATURES = SURFACE_FILTERED_FINISH_FEATURES | {'prev_last_3f_rank'}

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def parse_date(date_str):
    """日付文字列をパース"""
    normalized_date = normalize_race_date(date_str)
    if normalized_date is None:
        return None
    try:
        return datetime.strptime(normalized_date, '%Y/%m/%d')
    except ValueError:
        return None


def normalize_race_date(date_str):
    """日付文字列から有効な末尾の日付を YYYY/MM/DD 形式で取得"""
    if not date_str:
        return None

    match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2})$', date_str.strip())
    if not match:
        return None

    normalized_date = match.group(1).replace('-', '/')
    try:
        datetime.strptime(normalized_date, '%Y/%m/%d')
    except ValueError:
        return None

    return normalized_date

def days_between(date1, date2):
    """2つの日付の間の日数を計算"""
    if not date1 or not date2:
        return None
    delta = date1 - date2
    return delta.days

def calculate_horse_features(horse_id, race_history, target_race_date=None, target_race_distance=None, target_race_surface=None, target_race_course=None):
    """
    特定の馬の特徴量を計算
    
    Args:
        horse_id: 馬ID
        race_history: その馬の過去レース履歴（辞書のリスト）
        target_race_date: 予測対象のレース日付（Noneの場合は最新レースを対象）
        target_race_distance: 予測対象のレース距離
        target_race_surface: 予測対象のレース馬場（芝・ダート）
        target_race_course: 予測対象のレース競馬場
    
    Returns:
        特徴量の辞書
    """
    if not race_history or len(race_history) == 0:
        return {}
    
    # 日付でソート
    race_history = sorted(race_history, key=lambda x: x.get('race_date', ''), reverse=True)
    
    # ターゲットレース日付
    if target_race_date is None:
        target_race_date = parse_date(race_history[0].get('race_date')) if race_history else None
    
    # target_race_dateより後のレースを除外（AI予測時に未来のレースを含まないように）
    if target_race_date:
        race_history = [r for r in race_history if parse_date(r.get('race_date')) < target_race_date]

    features = {
        'horse_id': horse_id,
        'total_races': len(race_history),
        'prev_last_3f_rank': race_history[0].get('last_3f_rank') if race_history else None,
    }
    
    # === 過去成績系特徴量 ===
    
    # Recent form uses only matching-surface results within each recent-race window.
    recent_windows = {
        3: race_history[:3],
        5: race_history[:5],
    }
    for window_size, window_races in recent_windows.items():
        matching_races = [
            race for race in window_races
            if not target_race_surface or race.get('surface') == target_race_surface
        ]
        valid_finish = [
            race for race in matching_races
            if race.get('finish_position') is not None
        ]
        avg_key = f'recent_{window_size}_avg_finish'
        top3_key = f'recent_{window_size}_top3_rate'
        features[avg_key] = (
            sum(race['finish_position'] for race in valid_finish) / len(valid_finish)
            if valid_finish else None
        )
        features[top3_key] = (
            sum(1 for race in valid_finish if race['finish_position'] <= 3) / len(valid_finish)
            if valid_finish else None
        )

    # === 芝・ダート別の着順統計 ===

    # 全体の着順（芝）
    turf_races = [r for r in race_history if r.get('surface') == '芝']
    if turf_races:
        valid_finish = [r for r in turf_races if r.get('finish_position') is not None]
        if valid_finish:
            features['overall_avg_finish_turf'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['overall_top3_rate_turf'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['overall_avg_finish_turf'] = None
            features['overall_top3_rate_turf'] = 0
    else:
        features['overall_avg_finish_turf'] = None
        features['overall_top3_rate_turf'] = 0
    
    # 全体の着順（ダート）
    dirt_races = [r for r in race_history if r.get('surface') == 'ダート']
    if dirt_races:
        valid_finish = [r for r in dirt_races if r.get('finish_position') is not None]
        if valid_finish:
            features['overall_avg_finish_dirt'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['overall_top3_rate_dirt'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['overall_avg_finish_dirt'] = None
            features['overall_top3_rate_dirt'] = 0
    else:
        features['overall_avg_finish_dirt'] = None
        features['overall_top3_rate_dirt'] = 0

    for surface, suffix in (('芝', 'turf'), ('ダート', 'dirt')):
        for window_size, window_races in recent_windows.items():
            avg_key = f'recent_{window_size}_avg_finish_{suffix}'
            top3_key = f'recent_{window_size}_top3_rate_{suffix}'
            if target_race_surface and surface != target_race_surface:
                features[avg_key] = None
                features[top3_key] = None
                continue

            surface_races = [
                race for race in window_races
                if race.get('surface') == surface
            ]
            valid_finish = [
                race for race in surface_races
                if race.get('finish_position') is not None
            ]
            features[avg_key] = (
                sum(race['finish_position'] for race in valid_finish) / len(valid_finish)
                if valid_finish else None
            )
            features[top3_key] = (
                sum(1 for race in valid_finish if race['finish_position'] <= 3) / len(valid_finish)
                if valid_finish else None
            )
    
    # 全体の3着以内率
    valid_finish = [r for r in race_history if r.get('finish_position') is not None]
    if valid_finish:
        features['overall_top3_rate'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        features['overall_avg_finish'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
    else:
        features['overall_top3_rate'] = 0
        features['overall_avg_finish'] = None
    
    # === 休み明け・間隔系特徴量 ===
    
    if len(race_history) > 1 and target_race_date:
        # 前走からの間隔
        prev_date = parse_date(race_history[0].get('race_date'))
        days_since_last = days_between(target_race_date, prev_date)
        features['days_since_last_race'] = days_since_last
        
        # 休み明けフラグ（90日以上）
        features['is_long_break'] = 1 if days_since_last and days_since_last >= 90 else 0
        
        # 連闘フラグ（9日以内）
        features['is_consecutive'] = 1 if days_since_last and days_since_last <= 9 else 0
        
        # 中一週フラグ（10-16日）
        features['is_short_break'] = 1 if days_since_last and 10 <= days_since_last <= 16 else 0
        
        # 斟き目フラグ（休み明け後の2走目、3走目）
        for i in range(len(race_history) - 1):
            if i == 0:
                continue
            date1 = parse_date(race_history[i-1].get('race_date'))
            date2 = parse_date(race_history[i].get('race_date'))
            date_diff = days_between(date1, date2)
            if date_diff and date_diff >= 90:
                if i == 1:
                    features['is_tataki_2nd'] = 1
                elif i == 2:
                    features['is_tataki_3rd'] = 1
                break
        
        if 'is_tataki_2nd' not in features:
            features['is_tataki_2nd'] = 0
        if 'is_tataki_3rd' not in features:
            features['is_tataki_3rd'] = 0
    else:
        features['days_since_last_race'] = None
        features['is_long_break'] = 0
        features['is_consecutive'] = 0
        features['is_short_break'] = 0
        features['is_tataki_2nd'] = 0
        features['is_tataki_3rd'] = 0
    
    # === 距離適性（予想するレースの距離に合わせる） ===
    
    if target_race_distance:
        # 今回の距離での3着以内率
        dist_races = [r for r in race_history if r.get('distance') == target_race_distance]
        if dist_races:
            valid_finish = [r for r in dist_races if r.get('finish_position') is not None]
            if valid_finish:
                features['top3_rate_target_distance'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features['top3_rate_target_distance'] = 0
        else:
            features['top3_rate_target_distance'] = 0
    else:
        features['top3_rate_target_distance'] = 0
    
    # === コース適性（予想するレースのコースに合わせる） ===
    
    if target_race_course:
        # 今回のコースでの3着以内率
        course_races = [r for r in race_history if target_race_course in r.get('course', '')]
        if course_races:
            valid_finish = [r for r in course_races if r.get('finish_position') is not None]
            if valid_finish:
                features['top3_rate_target_course'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features['top3_rate_target_course'] = 0
        else:
            features['top3_rate_target_course'] = 0
    else:
        features['top3_rate_target_course'] = 0
    
    # === 芝・ダート適性（予想するレースの馬場に合わせる） ===
    
    if target_race_surface:
        # 今回の馬場での3着以内率
        surface_races = [r for r in race_history if r.get('surface') == target_race_surface]
        if surface_races:
            valid_finish = [r for r in surface_races if r.get('finish_position') is not None]
            if valid_finish:
                features['top3_rate_target_surface'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features['top3_rate_target_surface'] = 0
        else:
            features['top3_rate_target_surface'] = 0
    else:
        features['top3_rate_target_surface'] = 0
    
    # === 人気・着順系 ===
    
    if len(race_history) > 0:
        features['last_popularity'] = race_history[0].get('popularity')
        last_race_matches_surface = (
            not target_race_surface
            or race_history[0].get('surface') == target_race_surface
        )
        features['last_finish'] = (
            race_history[0].get('finish_position')
            if last_race_matches_surface else None
        )
    else:
        features['last_popularity'] = None
        features['last_finish'] = None
    
    valid_pop = [r for r in race_history if r.get('popularity') is not None]
    if valid_pop:
        features['avg_popularity'] = sum(r['popularity'] for r in valid_pop) / len(valid_pop)
    else:
        features['avg_popularity'] = None
    
    # === 昇級二戦目系（着順パターンで近似） ===
    
    # 前々走の着順
    if len(race_history) >= 2:
        features['prev2_finish'] = race_history[1].get('finish_position')
    else:
        features['prev2_finish'] = None
    
    # 前々走の距離
    if len(race_history) >= 2:
        features['prev2_distance'] = race_history[1].get('distance')
    else:
        features['prev2_distance'] = None
    
    # 前々走と前走の間隔
    if len(race_history) >= 2:
        date1 = parse_date(race_history[0].get('race_date'))
        date2 = parse_date(race_history[1].get('race_date'))
        features['prev2_to_prev_interval'] = days_between(date1, date2)
    else:
        features['prev2_to_prev_interval'] = None
    
    # 昇級二戦目フラグ（着順パターンで近似）
    # 前々走1着、前走が着順不良（5着以下）、間隔が短い（14日以内）
    if len(race_history) >= 2:
        prev2_finish = race_history[1].get('finish_position')

        if prev2_finish == 1:
            features['is_promotion_2nd'] = 1
        else:
            features['is_promotion_2nd'] = 0
    else:
        features['is_promotion_2nd'] = 0
    
    # === 距離短縮・拡大系 ===
    
    if target_race_distance and len(race_history) >= 1:
        prev_distance = race_history[0].get('distance')
        if prev_distance:
            features['prev_distance_diff'] = target_race_distance - prev_distance
            features['is_distance_shortening'] = 1 if target_race_distance < prev_distance else 0
            features['is_distance_expanding'] = 1 if target_race_distance > prev_distance else 0
        else:
            features['prev_distance_diff'] = None
            features['is_distance_shortening'] = 0
            features['is_distance_expanding'] = 0

        # 今回の距離経験回数
        same_distance_count = sum(1 for r in race_history if r.get('distance') == target_race_distance)
        features['target_distance_experience_count'] = same_distance_count
        features['is_first_time_distance'] = 1 if same_distance_count == 0 else 0
    else:
        features['prev_distance_diff'] = None
        features['is_distance_shortening'] = 0
        features['is_distance_expanding'] = 0
        features['target_distance_experience_count'] = 0
        features['is_first_time_distance'] = 0

    # === 二戦目系 ===

    # ダート二戦目フラグ（ダート未勝利戦でダート経験あり）
    if target_race_surface == 'ダート':
        dirt_count = sum(1 for r in race_history if r.get('surface') == 'ダート')
        features['is_dirt_2nd'] = 1 if dirt_count == 1 else 0
    else:
        features['is_dirt_2nd'] = 0

    # 短縮二戦目フラグ（距離短縮して二戦目）
    if target_race_distance and len(race_history) >= 2:
        prev2_distance = race_history[1].get('distance')
        prev_distance = race_history[0].get('distance')
        if prev2_distance and prev_distance and target_race_distance:
            # 前々走から前走で短縮し、今回も短縮している
            if prev2_distance > prev_distance and prev_distance > target_race_distance:
                features['is_shortening_2nd'] = 1
            else:
                features['is_shortening_2nd'] = 0
        else:
            features['is_shortening_2nd'] = 0
    else:
        features['is_shortening_2nd'] = 0
    
    # 昇級二戦目フラグ（着順パターンで近似）
    # 前々走1着、前走が着順不良（5着以下）、間隔が短い（14日以内）
    if len(race_history) >= 2:
        prev2_finish = race_history[1].get('finish_position')

        if prev2_finish == 1:
            features['is_promotion_2nd'] = 1
        else:
            features['is_promotion_2nd'] = 0
    else:
        features['is_promotion_2nd'] = 0

    # クラス情報がないため、2走前の1着を昇級と仮定し、前走5着以下を凡走扱いにする
    prev_finish = race_history[0].get('finish_position') if race_history else None
    prev2_finish = race_history[1].get('finish_position') if len(race_history) >= 2 else None
    features['is_win_then_poor_finish_2nd'] = int(
        prev2_finish == 1
        and isinstance(prev_finish, (int, float))
        and prev_finish >= 5
    )

    # === コース代わりの成績 ===

    if target_race_course and len(race_history) >= 1:
        prev_course = race_history[0].get('course')
        # 前走と今回でコースが異なる場合
        if prev_course and target_race_course not in prev_course:
            # 今回のコースでの成績を計算
            course_races = [r for r in race_history if target_race_course in r.get('course', '')]
            if course_races:
                valid_finish = [r for r in course_races if r.get('finish_position') is not None]
                if valid_finish:
                    features['prev_course_change_score'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
                else:
                    features['prev_course_change_score'] = 0
            else:
                features['prev_course_change_score'] = 0
        else:
            features['prev_course_change_score'] = 0
    else:
        features['prev_course_change_score'] = 0
    
    # === ペース・タイム系 ===
    
    valid_last3f = [r for r in race_history if r.get('last_3f') and r.get('last_3f') != '']
    if valid_last3f:
        last3f_numeric = []
        for r in valid_last3f:
            try:
                last3f_numeric.append(float(r['last_3f']))
            except:
                pass
        if last3f_numeric:
            features['avg_last_3f'] = sum(last3f_numeric) / len(last3f_numeric)
        else:
            features['avg_last_3f'] = None
    else:
        features['avg_last_3f'] = None
    
    return features

def get_horse_race_history(horse_id):
    """特定の馬のレース履歴を取得"""
    conn = get_connection()
    # SQLインジェクション対策：horse_idをエスケープ
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
        # 辞書のリストに変換
        data = [dict(zip(columns, row)) for row in rows]
        return data
    except Exception as e:
        print(f"Error reading race history for {horse_id}: {e}")
        return []
    finally:
        conn.close()

def calculate_features_for_horses(horse_ids, target_race_date=None):
    """
    複数の馬の特徴量を一括計算
    
    Args:
        horse_ids: 馬IDのリスト
        target_race_date: 予測対象のレース日付
    
    Returns:
        特徴量の辞書のリスト
    """
    all_features = []
    
    for horse_id in horse_ids:
        race_history = get_horse_race_history(horse_id)
        features = calculate_horse_features(horse_id, race_history, target_race_date)
        all_features.append(features)
    
    return all_features

if __name__ == '__main__':
    # テスト実行
    conn = get_connection()
    cur = conn.execute('SELECT horse_id FROM horse_data_hd LIMIT 5')
    test_horses = [row[0] for row in cur.fetchall()]
    conn.close()
    
    print(f"テスト対象馬: {test_horses}")
    
    for horse_id in test_horses:
        race_history = get_horse_race_history(horse_id)
        features = calculate_horse_features(horse_id, race_history)
        print(f"\n馬ID: {horse_id}")
        print(f"特徴量数: {len(features)}")
        print(f"総レース数: {features.get('total_races', 0)}")
        print(f"最近3走平均着順: {features.get('recent_3_avg_finish')}")
        print(f"最近3走3着以内率: {features.get('recent_3_top3_rate')}")
