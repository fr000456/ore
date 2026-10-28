import gzip
import base64
import datetime
import time
import sqlite3
import pickle
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from horse_html_setup import get_connection, init_db
from bs4 import BeautifulSoup
from feature_engineering import (
    NULL_AS_NAN_FEATURES,
    calculate_horse_features,
    get_horse_race_history,
    normalize_race_date,
    parse_date,
)
from race_metadata import (
    get_last_3f_column_index,
    get_last_3f_rank,
    get_race_rank,
)

# 解析用DB
ANALYSIS_DB = 'horse_analysis.db'

def get_analysis_connection():
    """解析用DBの接続"""
    conn = sqlite3.connect(ANALYSIS_DB, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

app = Flask(__name__)
CORS(app)

import re

def count_race_tr(html: str) -> int:
    """
    .db_h_race_results テーブルの tr 数を文字列検索でカウント
    正規表現対応版: 複数クラス・改行・大文字小文字に対応
    """
    # テーブルタグを正規表現で検索
    m = re.search(r'<table[^>]*class="[^"]*db_h_race_results[^"]*"[^>]*>', html, re.IGNORECASE)
    if not m:
        return 0

    start_idx = m.start()

    # 終了タグを探す
    end_idx = html.find('</table>', start_idx)
    table_html = html[start_idx:end_idx] if end_idx != -1 else html[start_idx:]

    # <tr>タグを正規表現で正確にカウント
    tr_matches = re.findall(r'<tr[^>]*>', table_html)
    tr_count = len(tr_matches)

    # ヘッダー行の有無を確認
    has_header = '<thead>' in table_html or '<th>' in table_html

    # ヘッダー行を除外
    if has_header:
        tr_count = max(0, tr_count - 1)

    return tr_count

def parse_horse_html(html, horse_id):
    """馬HTMLを解析して馬基本情報とレース情報を抽出"""
    soup = BeautifulSoup(html, 'html.parser')

    # 馬基本情報の抽出
    horse_data = {
        'horse_id': horse_id,
        'horse_name': None,
        'sire': None,
        'dam': None
    }

    # 馬名の抽出（レース成績テーブルのsummary属性から）
    race_table = soup.find('table', class_='db_h_race_results')
    if race_table and race_table.get('summary'):
        summary = race_table.get('summary')
        # "プロメテドールの競走戦績" → "プロメテドール"
        horse_name = summary.split('の競走戦績')[0] if 'の競走戦績' in summary else summary
        horse_data['horse_name'] = horse_name
    else:
        # フォールバック: titleタグ
        title = soup.find('title')
        if title:
            horse_data['horse_name'] = title.text.strip()

    # 馬名が取得できない場合、horse_idをそのまま馬名として使用
    if not horse_data['horse_name']:
        horse_data['horse_name'] = horse_id

    # レース情報の抽出
    race_data = []
    race_table = soup.find('table', class_='db_h_race_results')
    if race_table:
        last_3f_column_index = get_last_3f_column_index(race_table)
        rows = race_table.find_all('tr')[1:]  # ヘッダーを除外
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 25:
                continue

            race_info = {
                'horse_id': horse_id,
                'race_date': None,
                'course': None,
                'race_id': None,
                'field_size': None,
                'gate': None,
                'horse_number': None,
                'popularity': None,
                'finish_position': None,
                'jockey': None,
                'carried_weight': None,
                'surface': None,
                'distance': None,
                'track_condition': None,
                'finish_time': None,
                'margin': None,
                'passing_order': None,
                'pace': None,
                'last_3f': None,
                'horse_weight': None,
                'race_class': None,
                'last_3f_rank': None
            }

            # 各カラムの抽出
            try:
                # 日付
                date_link = cols[0].find('a')
                if date_link:
                    race_info['race_date'] = normalize_race_date(date_link.text)

                # 開催
                course_link = cols[1].find('a')
                if course_link:
                    course_text = course_link.text.strip()
                    # 前後の数字を削除して場所名だけを保存
                    race_info['course'] = re.sub(r'^[0-9]+|[0-9]+$', '', course_text)

                # レース名（race_id抽出用）
                race_info['race_class'] = get_race_rank(
                    cols[4].get_text(' ', strip=True)
                )
                race_link = cols[4].find('a')
                if race_link:
                    href = race_link['href']
                    # race_idをURLから抽出
                    match = href.split('/race/')[-1].split('/')[0]
                    race_info['race_id'] = int(match) if match.isdigit() else None

                # 頭数
                race_info['field_size'] = int(cols[6].text.strip()) if cols[6].text.strip().isdigit() else None

                # 枠番
                race_info['gate'] = int(cols[7].text.strip()) if cols[7].text.strip().isdigit() else None

                # 馬番
                race_info['horse_number'] = int(cols[8].text.strip()) if cols[8].text.strip().isdigit() else None

                # 人気
                popularity_text = cols[10].text.strip()
                race_info['popularity'] = int(popularity_text) if popularity_text.isdigit() else None

                # 着順
                finish_text = cols[11].text.strip()
                race_info['finish_position'] = int(finish_text) if finish_text.isdigit() else None

                # 騎手
                jockey_link = cols[12].find('a')
                if jockey_link:
                    race_info['jockey'] = jockey_link.text.strip()

                # 斤量
                weight_text = cols[13].text.strip()
                race_info['carried_weight'] = float(weight_text) if weight_text.replace('.', '').isdigit() else None

                # 距離
                distance_text = cols[14].text.strip()
                if distance_text:
                    # ダ1600 → ダート1600m、芝1800 → 芝1800m
                    race_info['surface'] = 'ダート' if 'ダ' in distance_text else '芝'
                    race_info['distance'] = int(''.join(filter(str.isdigit, distance_text)))

                # 馬場状態
                race_info['track_condition'] = cols[16].text.strip()

                # タイム
                race_info['finish_time'] = cols[18].text.strip()

                # 着差
                margin_text = cols[19].text.strip()
                race_info['margin'] = float(margin_text) if margin_text and margin_text.replace('.', '').replace('-', '').isdigit() else None

                # 通過
                race_info['passing_order'] = cols[25].text.strip()

                # ペース
                race_info['pace'] = cols[26].text.strip()

                # 上り3F
                if last_3f_column_index is not None and last_3f_column_index < len(cols):
                    last_3f_cell = cols[last_3f_column_index]
                    race_info['last_3f'] = last_3f_cell.get_text(strip=True)
                    race_info['last_3f_rank'] = get_last_3f_rank(last_3f_cell)

                # 馬体重（カッコを除去）
                weight_text = cols[28].text.strip()
                if weight_text:
                    # 498(0) → 498、498(+14) → 498
                    weight_text = weight_text.split('(')[0].split('+')[0]
                    race_info['horse_weight'] = int(weight_text) if weight_text.isdigit() else None

            except Exception as e:
                continue

            race_data.append(race_info)

    return horse_data, race_data

@app.route('/save', methods=['POST'])
def save_html():
    try:
        data = request.get_json()
        horse_id = data.get('horseId')
        html = data.get('html')
        force = data.get('force', False)
        saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not horse_id or not html:
            return jsonify({'error': 'Invalid data'}), 400

        race_count = count_race_tr(html)

        # HTML解析
        horse_data, race_data = parse_horse_html(html, horse_id)

        # gzip圧縮 + base64エンコード
        compressed_html = gzip.compress(html.encode('utf-8'))
        encoded_html = base64.b64encode(compressed_html).decode('ascii')

        for attempt in range(5):
            try:
                with get_connection() as conn:
                    # horse_data_dtlのレコード数を取得して出走数判定
                    with get_analysis_connection() as analysis_conn:
                        cur = analysis_conn.execute('SELECT COUNT(*) FROM horse_data_dtl WHERE horse_id = ?', (horse_id,))
                        row = cur.fetchone()
                        db_race_count = row[0] if row else 0

                    if not force and db_race_count >= race_count:
                        # Skip {horse_id}: DB {db_race_count} race_count {race_count}
                        pass
                        return jsonify({'message': f'{horse_id} skipped (same race_count: {race_count})'}), 200

                    conn.execute('''
                        INSERT OR REPLACE INTO horse_html (horse_id, html, saved_at, race_count)
                        VALUES (?, ?, ?, ?)
                    ''', (horse_id, encoded_html, saved_at, race_count))

                    # OK {horse_id}: saved (race_count: {race_count})
                    pass

                # 解析データの保存
                try:
                    with get_analysis_connection() as analysis_conn:
                        # 馬基本情報の保存（存在しない場合のみINSERT）
                        analysis_conn.execute('''
                            INSERT OR IGNORE INTO horse_data_hd
                            (horse_id, horse_name, sire, dam)
                            VALUES (?, ?, ?, ?)
                        ''', (
                            horse_data['horse_id'],
                            horse_data['horse_name'],
                            horse_data['sire'],
                            horse_data['dam']
                        ))

                        # レース情報の保存
                        saved_race_count = 0
                        for race in race_data:
                            if race['race_id']:  # race_idがある場合のみ保存
                                try:
                                    values = (
                                        race['horse_id'], race['race_date'],
                                        race['course'], race['race_id'], race['field_size'],
                                        race['gate'], race['horse_number'], race['popularity'],
                                        race['finish_position'], race['jockey'], race['carried_weight'],
                                        race['surface'], race['distance'], race['track_condition'],
                                        race['finish_time'], race['margin'], race['passing_order'],
                                        race['pace'], race['last_3f'], race['horse_weight'],
                                        race['race_class'], race['last_3f_rank']
                                    )

                                    analysis_conn.execute('''
                                        INSERT INTO horse_data_dtl
                                        (horse_id, race_date, course, race_id,
                                         field_size, gate, horse_number, popularity, finish_position,
                                         jockey, carried_weight, surface, distance, track_condition,
                                         finish_time, margin, passing_order, pace, last_3f, horse_weight,
                                         race_class, last_3f_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        ON CONFLICT(horse_id, race_id) DO UPDATE SET
                                            race_date = excluded.race_date,
                                            course = excluded.course,
                                            field_size = excluded.field_size,
                                            gate = excluded.gate,
                                            horse_number = excluded.horse_number,
                                            popularity = excluded.popularity,
                                            finish_position = excluded.finish_position,
                                            jockey = excluded.jockey,
                                            carried_weight = excluded.carried_weight,
                                            surface = excluded.surface,
                                            distance = excluded.distance,
                                            track_condition = excluded.track_condition,
                                            finish_time = excluded.finish_time,
                                            margin = excluded.margin,
                                            passing_order = excluded.passing_order,
                                            pace = excluded.pace,
                                            last_3f = excluded.last_3f,
                                            horse_weight = excluded.horse_weight,
                                            race_class = COALESCE(excluded.race_class, horse_data_dtl.race_class),
                                            last_3f_rank = COALESCE(excluded.last_3f_rank, horse_data_dtl.last_3f_rank)
                                    ''', values)
                                    saved_race_count += 1
                                except Exception as e:
                                    continue

                except Exception as e:
                    # Warning: analysis data save error: {e}
                    pass

                return jsonify({'message': f'{horse_id} saved (race_count: {race_count})'}), 200

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    # Warning: horse_html.db is locked (retry {attempt + 1}/5)
                    pass
                    time.sleep(1)
                else:
                    return jsonify({'error': f'Database error: {e}'}), 500

        return jsonify({'error': 'Database is locked'}), 500

    except Exception as e:
        return jsonify({'error': f'Unexpected error: {e}'}), 500

    return jsonify({'message': f'{horse_id} saved (race_count: {race_count})'}), 200

@app.route('/html/<horse_id>', methods=['GET'])
def get_html(horse_id):
    """
    特定 horse_id の HTML を返す（base64 + gzip のデコード込み）
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                'SELECT html FROM horse_html WHERE horse_id = ?',
                (horse_id,)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'not found'}), 404

            encoded_html = row[0]

            # Base64 → gzip → UTF-8
            try:
                decoded = base64.b64decode(encoded_html)
                html_str = gzip.decompress(decoded).decode('utf-8')
            except Exception as e:
                return jsonify({'error': f'decode error: {e}'}), 500

            return jsonify({'horseId': horse_id, 'html': html_str}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# モデルをグローバルにキャッシュ
model = None
feature_columns = None
models_cache = {}  # レース条件ごとのモデルキャッシュ

def load_model_by_condition(course, distance, surface, model_group=None):
    """レース条件に応じてモデルを読み込む"""
    group_suffix = f"_{model_group}" if model_group else ""
    model_key = f"{course}_{surface}_{distance}m{group_suffix}"

    # キャッシュにあれば返す
    if model_key in models_cache:
        return models_cache[model_key]

    # モデルファイル名
    model_filename = f"model_{course}_{surface}_{distance}m{group_suffix}.pkl"

    try:
        with open(model_filename, 'rb') as f:
            data = pickle.load(f)
            models_cache[model_key] = data
            # Model loaded: {model_filename}
            pass
            return data
    except FileNotFoundError:
        # Model not found: {model_filename}
        pass
        return None

def load_model_if_needed():
    """モデルが読み込まれていない場合に読み込む（古いAPIの互換性用）"""
    global model, feature_columns
    if model is None:
        try:
            with open('model.pkl', 'rb') as f:
                model = pickle.load(f)
            # 特徴量カラムを保存（学習時と同じ順序で）
            with open('training_data.pkl', 'rb') as f:
                data = pickle.load(f)
                all_features = data['features']
                # 不要なカラムを除いた特徴量名を取得
                cols_to_drop = ['horse_id', 'last_jockey']
                if all_features:
                    feature_columns = [k for k in all_features[0].keys() if k not in cols_to_drop]
                else:
                    feature_columns = []
            # Model loaded successfully
            pass
        except FileNotFoundError:
            # Model file not found. Please run train_model.py first
            return False
    return True

def prepare_features_for_prediction(features_dict, model_feature_columns=None):
    """
    予測用に特徴量を前処理
    
    Args:
        features_dict: 特徴量の辞書
        model_feature_columns: モデルの特徴量カラム名（指定された場合）
    
    Returns:
        前処理済みの特徴量（numpy array）
    """
    # 不要なカラムを削除
    cols_to_drop = [
        'horse_id', 'last_jockey',
        # 馬場適性（削除）
        'top3_rate_condition_良', 'top3_rate_condition_稍', 'top3_rate_condition_重', 'top3_rate_condition_不',
        # 距離適性（古い、削除）
        'top3_rate_distance_short', 'top3_rate_distance_medium', 'top3_rate_distance_long',
        # コース適性（古い、削除）
        'top3_rate_course_東京', 'top3_rate_course_中山', 'top3_rate_course_京都', 'top3_rate_course_阪神', 'top3_rate_course_新潟',
        # 芝・ダート適性（古い、削除）
        'top3_rate_surface_芝', 'top3_rate_surface_ダート',
        # 斤量系（削除）
        'avg_carried_weight', 'weight_change',
        # 馬体系（削除）
        'avg_horse_weight', 'horse_weight_change',
        # 古いkyori系（削除）
        'is_diff_distance_from_prev', 'same_distance_experience',
        # 古いdirt系（削除）
        'has_dirt_experience'
    ]
    
    # モデルの特徴量カラムが指定されている場合
    if model_feature_columns and len(model_feature_columns) > 0:
        row = []
        for col in model_feature_columns:
            value = features_dict.get(col)
            if value is None:
                row.append(np.nan if col in NULL_AS_NAN_FEATURES else 0.0)
            else:
                row.append(float(value))
        X = np.array([row])
    # グローバルのfeature_columnsがある場合
    elif feature_columns and len(feature_columns) > 0:
        row = []
        for col in feature_columns:
            value = features_dict.get(col)
            if value is None:
                row.append(0.0)
            else:
                row.append(float(value))
        X = np.array([row])
    else:
        # feature_columnsがない場合、辞書から作成
        row = []
        for key, value in features_dict.items():
            if key not in cols_to_drop:
                if value is None:
                    row.append(0.0)
                else:
                    row.append(float(value))
        X = np.array([row])
    
    return X

@app.route('/predict', methods=['POST'])
def predict():
    """
    出走馬の3着以内確率を予測
    
    Request:
        {
            "horse_ids": ["horse_id1", "horse_id2", ...],
            "race_date": "2024/01/01"  # オプション
        }
    
    Response:
        {
            "predictions": [
                {
                    "horse_id": "horse_id1",
                    "probability": 0.35,
                    "features": {...}
                },
                ...
            ]
        }
    """
    try:
        data = request.get_json()
        horse_ids = data.get('horse_ids', [])
        race_date = data.get('race_date', None)
        race_distance = data.get('race_distance', None)
        race_surface = data.get('race_surface', None)
        race_course = data.get('race_course', None)
        race_class = data.get('race_class')
        
        if not horse_ids:
            return jsonify({'error': 'horse_ids is required'}), 400
        
        # レース条件が提供されている場合、レース条件ごとのモデルを使用
        if race_course and race_distance and race_surface:
            if race_class is None:
                return jsonify({'error': 'race_class is required for race-condition prediction'}), 400
            try:
                race_class = int(race_class)
            except (TypeError, ValueError):
                return jsonify({'error': 'race_class must be an integer from 0 to 9'}), 400
            if not 0 <= race_class <= 9:
                return jsonify({'error': 'race_class must be an integer from 0 to 9'}), 400

            model_group = 'condition' if 2 <= race_class <= 4 else 'other'
            # 競走条件とクラス区分に一致するモデルを読み込む
            model_data = load_model_by_condition(
                race_course,
                race_distance,
                race_surface,
                model_group,
            )
            if not model_data:
                return jsonify({
                    'error': (
                        f'Model not found for {race_course} {race_surface} '
                        f'{race_distance}m ({model_group})'
                    )
                }), 404

            model_instance = model_data['model']
            model_feature_columns = model_data['feature_columns']
        else:
            # レース条件が提供されていない場合、単一モデルを使用（互換性用）
            if not load_model_if_needed():
                return jsonify({'error': 'Model not found. Please train the model first.'}), 404
            model_instance = model
            model_feature_columns = feature_columns

        from feature_engineering import calculate_horse_features, get_horse_race_history, parse_date
        
        predictions = []
        
        for horse_id in horse_ids:
            try:
                # レース履歴を取得
                race_history = get_horse_race_history(horse_id)
                
                # レース日付をパース
                parsed_race_date = parse_date(race_date) if race_date else None
                
                # 特徴量を計算
                try:
                    features = calculate_horse_features(horse_id, race_history, parsed_race_date, race_distance, race_surface, race_course)
                except Exception as e:
                    predictions.append({
                        'horse_id': horse_id,
                        'probability': 0.0,
                        'error': f'Feature calculation error: {str(e)}'
                    })
                    continue
                
                if features is None or (isinstance(features, dict) and len(features) == 0):
                    predictions.append({
                        'horse_id': horse_id,
                        'probability': 0.0,
                        'error': 'No features calculated'
                    })
                    continue
                
                # 特徴量を前処理
                try:
                    X = prepare_features_for_prediction(features, model_feature_columns)
                except Exception as e:
                    predictions.append({
                        'horse_id': horse_id,
                        'probability': 0.0,
                        'error': f'Feature preparation error: {str(e)}'
                    })
                    continue
                
                # 予測
                try:
                    probability = model_instance.predict(X, num_iteration=model_instance.best_iteration)[0]
                except Exception as e:
                    predictions.append({
                        'horse_id': horse_id,
                        'probability': 0.0,
                        'error': f'Prediction error: {str(e)}'
                    })
                    continue
                
                predictions.append({
                    'horse_id': horse_id,
                    'probability': float(probability),
                    'features': features
                })
            
            except Exception as e:
                predictions.append({
                    'horse_id': horse_id,
                    'probability': 0.0,
                    'error': str(e)
                })
        
        # 確率でソート
        predictions.sort(key=lambda x: x['probability'], reverse=True)
        
        # Final predictions: {predictions}
        pass
        
        return jsonify({
            'predictions': predictions,
            'model_loaded': True
        }), 200
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        # Error in predict: {str(e)}
        pass
        # Error detail: {error_detail}
        pass
        return jsonify({'error': str(e)}), 500

@app.route('/predict_single', methods=['POST'])
def predict_single():
    """
    単一の馬の3着以内確率を予測（簡易版）
    
    Request:
        {
            "horse_id": "horse_id1",
            "race_date": "2024/01/01"  # オプション
        }
    
    Response:
        {
            "horse_id": "horse_id1",
            "probability": 0.35,
            "features": {...}
        }
    """
    try:
        # モデルを読み込み
        if not load_model_if_needed():
            return jsonify({'error': 'Model not found. Please train the model first.'}), 404
        
        data = request.get_json()
        horse_id = data.get('horse_id')
        race_date = data.get('race_date', None)
        race_distance = data.get('race_distance', None)
        race_surface = data.get('race_surface', None)
        race_course = data.get('race_course', None)
        
        if not horse_id:
            return jsonify({'error': 'horse_id is required'}), 400
        
        from feature_engineering import calculate_horse_features, get_horse_race_history, parse_date
        
        # レース履歴を取得
        race_history = get_horse_race_history(horse_id)
        
        # レース日付をパース
        parsed_race_date = parse_date(race_date) if race_date else None
        
        # 特徴量を計算
        features = calculate_horse_features(horse_id, race_history, parsed_race_date, race_distance, race_surface, race_course)
        
        if not features:
            return jsonify({'error': 'No features calculated'}), 400
        
        # 特徴量を前処理
        X = prepare_features_for_prediction(features)
        
        # 予測
        probability = model.predict(X, num_iteration=model.best_iteration)[0]
        
        return jsonify({
            'horse_id': horse_id,
            'probability': float(probability),
            'features': features
        }), 200
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        # Error in predict_single: {str(e)}
        pass
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True)
