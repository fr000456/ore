import gzip
import base64
import datetime
import time
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from horse_html_setup import get_connection, init_db
from bs4 import BeautifulSoup

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
                'horse_weight': None
            }

            # 各カラムの抽出
            try:
                # 日付
                date_link = cols[0].find('a')
                if date_link:
                    race_info['race_date'] = date_link.text.strip()

                # 開催
                course_link = cols[1].find('a')
                if course_link:
                    race_info['course'] = course_link.text.strip()

                # レース名（race_id抽出用）
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
                race_info['margin'] = float(margin_text) if margin_text.replace('.', '').isdigit() else None

                # 通過
                race_info['passing_order'] = cols[21].text.strip()

                # ペース
                race_info['pace'] = cols[22].text.strip()

                # 上り3F
                race_info['last_3f'] = cols[23].text.strip()

                # 馬体重（カッコを除去）
                weight_text = cols[24].text.strip()
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

        # gzip圧縮 + base64エンコード
        compressed_html = gzip.compress(html.encode('utf-8'))
        encoded_html = base64.b64encode(compressed_html).decode('ascii')

        for attempt in range(5):
            try:
                with get_connection() as conn:
                    cur = conn.execute('SELECT race_count FROM horse_html WHERE horse_id = ?', (horse_id,))
                    row = cur.fetchone()

                    if not force and row and row[0] >= race_count:
                        print(f"⏩ {horse_id}: DB {row[0]} 出走数 {race_count} スキップ")
                        return jsonify({'message': f'{horse_id} skipped (same race_count: {race_count})'}), 200

                    conn.execute('''
                        INSERT OR REPLACE INTO horse_html (horse_id, html, saved_at, race_count)
                        VALUES (?, ?, ?, ?)
                    ''', (horse_id, encoded_html, saved_at, race_count))

                    print(f"✅ {horse_id}: 保存（出走数 {race_count}）")
                    return jsonify({'message': f'{horse_id} saved (race_count: {race_count})'}), 200

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    print(f"⚠️ horse_html.db is locked (retry {attempt + 1}/5)")
                    time.sleep(1)
                else:
                    return jsonify({'error': f'Database error: {e}'}), 500

        return jsonify({'error': 'Database is locked'}), 500

    except Exception as e:
        return jsonify({'error': f'Unexpected error: {e}'}), 500

    # 解析データの保存（一時的に無効化）
    """
    try:
        horse_data, race_data = parse_horse_html(html, horse_id)

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
                            race['pace'], race['last_3f'], race['horse_weight']
                        )

                        analysis_conn.execute('''
                            INSERT OR REPLACE INTO horse_data_dtl
                            (horse_id, race_date, course, race_id,
                             field_size, gate, horse_number, popularity, finish_position,
                             jockey, carried_weight, surface, distance, track_condition,
                             finish_time, margin, passing_order, pace, last_3f, horse_weight)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', values)
                        saved_race_count += 1
                    except Exception as e:
                        continue

    except Exception as e:
        pass
    """

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
    
if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True)
