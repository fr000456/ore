import sqlite3
from datetime import datetime
from collections import defaultdict

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def parse_date(date_str):
    """日付文字列をパース"""
    if not date_str:
        return None
    try:
        # YYYY-MM-DD形式
        if '-' in date_str:
            return datetime.strptime(date_str, '%Y-%m-%d')
        # YYYY/MM/DD形式
        elif '/' in date_str:
            return datetime.strptime(date_str, '%Y/%m/%d')
    except:
        return None
    return None

def days_between(date1, date2):
    """2つの日付の間の日数を計算"""
    if not date1 or not date2:
        return None
    delta = date1 - date2
    return delta.days

def calculate_horse_features(horse_id, race_history, target_race_date=None):
    """
    特定の馬の特徴量を計算
    
    Args:
        horse_id: 馬ID
        race_history: その馬の過去レース履歴（辞書のリスト）
        target_race_date: 予測対象のレース日付（Noneの場合は最新レースを対象）
    
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
    
    features = {
        'horse_id': horse_id,
        'total_races': len(race_history),
    }
    
    # === 過去成績系特徴量 ===
    
    # 最近3走の着順
    recent_3 = race_history[:3]
    if len(recent_3) > 0:
        valid_finish = [r for r in recent_3 if r.get('finish_position') is not None]
        if valid_finish:
            features['recent_3_avg_finish'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['recent_3_top3_rate'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['recent_3_avg_finish'] = None
            features['recent_3_top3_rate'] = 0
    else:
        features['recent_3_avg_finish'] = None
        features['recent_3_top3_rate'] = 0
    
    # 最近5走の着順
    recent_5 = race_history[:5]
    if len(recent_5) > 0:
        valid_finish = [r for r in recent_5 if r.get('finish_position') is not None]
        if valid_finish:
            features['recent_5_avg_finish'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['recent_5_top3_rate'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['recent_5_avg_finish'] = None
            features['recent_5_top3_rate'] = 0
    else:
        features['recent_5_avg_finish'] = None
        features['recent_5_top3_rate'] = 0
    
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
    
    # === 馬場適性 ===
    
    for condition in ['良', '稍', '重', '不']:
        cond_races = [r for r in race_history if r.get('track_condition') == condition]
        if cond_races:
            valid_finish = [r for r in cond_races if r.get('finish_position') is not None]
            if valid_finish:
                features[f'top3_rate_condition_{condition}'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features[f'top3_rate_condition_{condition}'] = 0
        else:
            features[f'top3_rate_condition_{condition}'] = 0
    
    # === 距離適性 ===
    
    for dist_cat in ['short', 'medium', 'long']:
        dist_races = []
        for r in race_history:
            dist = r.get('distance')
            if dist:
                if dist < 1400:
                    cat = 'short'
                elif dist <= 1800:
                    cat = 'medium'
                else:
                    cat = 'long'
                if cat == dist_cat:
                    dist_races.append(r)
        
        if dist_races:
            valid_finish = [r for r in dist_races if r.get('finish_position') is not None]
            if valid_finish:
                features[f'top3_rate_distance_{dist_cat}'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features[f'top3_rate_distance_{dist_cat}'] = 0
        else:
            features[f'top3_rate_distance_{dist_cat}'] = 0
    
    # === コース適性 ===
    
    major_courses = ['東京', '中山', '京都', '阪神', '新潟']
    for course in major_courses:
        course_races = [r for r in race_history if course in r.get('course', '')]
        if course_races:
            valid_finish = [r for r in course_races if r.get('finish_position') is not None]
            if valid_finish:
                features[f'top3_rate_course_{course}'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features[f'top3_rate_course_{course}'] = 0
        else:
            features[f'top3_rate_course_{course}'] = 0
    
    # === 芝・ダート適性 ===
    
    for surface in ['芝', 'ダート']:
        surface_races = [r for r in race_history if r.get('surface') == surface]
        if surface_races:
            valid_finish = [r for r in surface_races if r.get('finish_position') is not None]
            if valid_finish:
                features[f'top3_rate_surface_{surface}'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features[f'top3_rate_surface_{surface}'] = 0
        else:
            features[f'top3_rate_surface_{surface}'] = 0
    
    # === 人気・着順系 ===
    
    if len(race_history) > 0:
        features['last_popularity'] = race_history[0].get('popularity')
        features['last_finish'] = race_history[0].get('finish_position')
    else:
        features['last_popularity'] = None
        features['last_finish'] = None
    
    valid_pop = [r for r in race_history if r.get('popularity') is not None]
    if valid_pop:
        features['avg_popularity'] = sum(r['popularity'] for r in valid_pop) / len(valid_pop)
    else:
        features['avg_popularity'] = None
    
    # === 斤量系 ===
    
    valid_weight = [r for r in race_history if r.get('carried_weight') is not None]
    if valid_weight:
        features['avg_carried_weight'] = sum(r['carried_weight'] for r in valid_weight) / len(valid_weight)
    else:
        features['avg_carried_weight'] = None
    
    if len(race_history) >= 2:
        cw0 = race_history[0].get('carried_weight')
        cw1 = race_history[1].get('carried_weight')
        if cw0 is not None and cw1 is not None:
            features['weight_change'] = cw0 - cw1
        else:
            features['weight_change'] = None
    else:
        features['weight_change'] = None
    
    # === 騎手系 ===
    
    if len(race_history) > 0:
        features['last_jockey'] = race_history[0].get('jockey')
    else:
        features['last_jockey'] = None
    
    # === 馬体系 ===
    
    valid_horse_weight = [r for r in race_history if r.get('horse_weight') is not None]
    if valid_horse_weight:
        features['avg_horse_weight'] = sum(r['horse_weight'] for r in valid_horse_weight) / len(valid_horse_weight)
    else:
        features['avg_horse_weight'] = None
    
    if len(race_history) >= 2:
        hw0 = race_history[0].get('horse_weight')
        hw1 = race_history[1].get('horse_weight')
        if hw0 is not None and hw1 is not None:
            features['horse_weight_change'] = hw0 - hw1
        else:
            features['horse_weight_change'] = None
    else:
        features['horse_weight_change'] = None
    
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
