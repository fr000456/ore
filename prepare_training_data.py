import sqlite3
import numpy as np
from datetime import datetime, timedelta
from feature_engineering import calculate_horse_features, get_horse_race_history, parse_date, days_between

DB_PATH = 'horse_analysis.db'

def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def get_race_group(race_id):
    """
    特定のrace_idの出走馬を取得
    
    Args:
        race_id: レースID
    
    Returns:
        出走馬の辞書のリスト
    """
    conn = get_connection()
    query = f'''
        SELECT horse_id, race_date, finish_position 
        FROM horse_data_dtl
        WHERE race_id = {race_id}
    '''
    try:
        cur = conn.execute(query)
        columns = [description[0] for description in cur.description]
        rows = cur.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error reading race group for race_id={race_id}: {e}")
        data = []
    finally:
        conn.close()
    return data

def get_all_race_ids(min_horses=3):
    """
    一定数以上の出走馬がいるrace_idを取得
    
    Args:
        min_horses: 最少出走馬数
    
    Returns:
        race_idのリスト
    """
    conn = get_connection()
    query = f'''
        SELECT race_id, COUNT(*) as horse_count
        FROM horse_data_dtl
        GROUP BY race_id
        HAVING horse_count >= {min_horses}
        ORDER BY race_id
    '''
    try:
        cur = conn.execute(query)
        race_ids = [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error getting race ids: {e}")
        race_ids = []
    finally:
        conn.close()
    return race_ids

def prepare_training_data(race_ids=None, sample_size=None, years_limit=10):
    """
    学習データを準備
    
    Args:
        race_ids: 使用するrace_idのリスト（Noneの場合は全て）
        sample_size: サンプリングするレース数（Noneの場合は全て）
        years_limit: 直何年のデータを使うか（デフォルト10年）
    
    Returns:
        特徴量のリストと目的変数のリスト
    """
    if race_ids is None:
        race_ids = get_all_race_ids()
    
    if sample_size and len(race_ids) > sample_size:
        race_ids = np.random.choice(race_ids, sample_size, replace=False).tolist()
    
    # 直近N年以内のレースIDを取得
    cutoff_date = datetime.now() - timedelta(days=years_limit * 365)

    all_features = []
    all_targets = []
    
    print(f"処理対象レース数: {len(race_ids)}")
    print(f"直近{years_limit}年のデータを使用（{cutoff_date.strftime('%Y-%m-%d')}以降）")
    
    for i, race_id in enumerate(race_ids, 1):
        if i % 100 == 0:
            print(f"進捗: {i}/{len(race_ids)} レース処理済")
        
        try:
            # そのレースの出走馬を取得
            race_group = get_race_group(race_id)
            
            if not race_group or len(race_group) == 0:
                continue
            
            # レース日付を取得
            race_date = race_group[0]['race_date']
            parsed_race_date = parse_date(race_date)
            
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
                
                # 特徴量計算
                features = calculate_horse_features(horse_id, race_history, parsed_race_date)
                
                if features:
                    # 目的変数：3着以内なら1、それ以外は0
                    target = 1 if finish_position and finish_position <= 3 else 0
                    
                    all_features.append(features)
                    all_targets.append(target)
        
        except Exception as e:
            print(f"Warning: race_id={race_id} error: {e}")
            continue
    
    print(f"\n学習データ作成完了:")
    print(f"  サンプル数: {len(all_features)}")
    if all_features:
        print(f"  特徴量数: {len(all_features[0])}")
    print(f"  3着以内率: {np.mean(all_targets):.3f}")
    
    return all_features, all_targets

def split_data_by_time(all_features, all_targets, train_ratio=0.8):
    """
    時系列でデータを分割（古いデータで学習、新しいデータで検証）
    
    Args:
        all_features: 特徴量のリスト
        all_targets: 目的変数のリスト
        train_ratio: 学習データの比率
    
    Returns:
        学習用と検証用のデータ
    """
    # インデックスで分割
    split_idx = int(len(all_features) * train_ratio)
    
    X_train = all_features[:split_idx]
    X_test = all_features[split_idx:]
    y_train = all_targets[:split_idx]
    y_test = all_targets[split_idx:]
    
    print(f"\nデータ分割:")
    print(f"  学習用: {len(X_train)} サンプル")
    print(f"  検証用: {len(X_test)} サンプル")
    print(f"  学習用3着以内率: {np.mean(y_train):.3f}")
    print(f"  検証用3着以内率: {np.mean(y_test):.3f}")
    
    return X_train, X_test, y_train, y_test

def save_training_data(all_features, all_targets, output_path='training_data.pkl'):
    """学習データを保存"""
    import pickle
    data = {
        'features': all_features,
        'targets': all_targets
    }
    with open(output_path, 'wb') as f:
        pickle.dump(data, f)
    print(f"学習データを保存: {output_path}")

def load_training_data(input_path='training_data.pkl'):
    """学習データを読み込み"""
    import pickle
    with open(input_path, 'rb') as f:
        data = pickle.load(f)
    return data['features'], data['targets']

if __name__ == '__main__':
    # 直近10年のデータで学習データ作成
    print("学習データ作成を開始します（直近10年）...")
    
    all_features, all_targets = prepare_training_data(sample_size=None, years_limit=10)
    
    if len(all_features) > 0:
        print("\nFeature columns:")
        print(len(all_features[0]))
        
        # データを分割
        X_train, X_test, y_train, y_test = split_data_by_time(all_features, all_targets)
        
        # 保存
        save_training_data(all_features, all_targets)
    else:
        print("No data created")
