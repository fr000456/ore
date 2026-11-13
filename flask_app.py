import gzip
import base64
import datetime
import time
import sqlite3
import pickle
import os
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from horse_html_setup import get_connection, init_db
from bs4 import BeautifulSoup
from feature_engineering import (
    NULL_AS_NAN_FEATURES,
    apply_promotion_second_boost,
    calculate_horse_features,
    get_promotion_second_context_values,
    get_horse_race_history,
    normalize_race_date,
    parse_date,
)
from race_metadata import (
    get_last_3f_column_index,
    get_last_3f_rank,
    get_race_rank,
)
from race_entry_storage import save_race_page

# 解析用DB
ANALYSIS_DB = 'horse_analysis.db'

def get_analysis_connection():
    """解析用DBの接続"""
    conn = sqlite3.connect(ANALYSIS_DB, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def race_has_recorded_winner(race_id):
    """Return whether the analysis DB has a recorded winner for this race."""
    connection = get_analysis_connection()
    try:
        return connection.execute(
            '''
            SELECT 1
            FROM horse_data_dtl
            WHERE race_id = ? AND finish_position = 1
            LIMIT 1
            ''',
            (race_id,),
        ).fetchone() is not None
    finally:
        connection.close()


import sys

# Windowsのcp932コンソールで絵文字入りprintがUnicodeEncodeErrorになるのを防ぐ
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = Flask(__name__)
CORS(app)

import re


BACKTEST_PAGE = '''
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>過去レースの指数検証</title>
  <style>
    body { font-family: sans-serif; margin: 2rem auto; max-width: 1000px; padding: 0 1rem; color: #222; }
    input, button { font: inherit; padding: .6rem; }
    input { width: min(32rem, 90%); }
    button { cursor: pointer; }
    #status { margin: 1rem 0; white-space: pre-wrap; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border-bottom: 1px solid #ddd; padding: .55rem; text-align: left; }
    th { background: #f3f3f3; }
    .number { text-align: right; }
  </style>
</head>
<body>
  <h1>過去レースの指数検証</h1>
  <p>レースIDまたはnetkeibaのレースURLを入力してください。</p>
  <p>出走表に表示されている全馬を検証する場合は、出馬表ページの「AI予想」ボタンをご利用ください。</p>
  <form id="backtest-form">
    <input id="race-id" name="race_id" placeholder="例: 202605021211 またはレースURL" required>
    <button id="run-button" type="submit">検証する</button>
  </form>
  <div id="status" role="status"></div>
  <div id="result"></div>
  <script>
    const form = document.getElementById("backtest-form");
    const input = document.getElementById("race-id");
    const status = document.getElementById("status");
    const result = document.getElementById("result");
    const button = document.getElementById("run-button");

    function cell(tag, value, className) {
      const element = document.createElement(tag);
      element.textContent = value;
      if (className) element.className = className;
      return element;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const match = input.value.match(/(?:race_id=)?(\\d{12})/);
      if (!match) {
        status.textContent = "12桁のレースID、またはレースURLを入力してください。";
        result.replaceChildren();
        return;
      }

      button.disabled = true;
      status.textContent = "過去データだけでモデルを作成して予測しています。しばらくお待ちください…";
      result.replaceChildren();
      try {
        const response = await fetch("/backtest/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ race_id: match[1] })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "検証に失敗しました。");

        status.textContent = `${data.race_date} ${data.course} ${data.surface}${data.distance}m / 学習データ最終日: ${data.training_through_date}`;
        const table = document.createElement("table");
        const head = document.createElement("thead");
        const header = document.createElement("tr");
        ["順位", "馬ID", "AI指数", "実着順"].forEach((label) => header.appendChild(cell("th", label)));
        head.appendChild(header);
        table.appendChild(head);

        const body = document.createElement("tbody");
        data.predictions.forEach((prediction, index) => {
          const row = document.createElement("tr");
          row.appendChild(cell("td", prediction.excluded ? "対象外" : String(index + 1), "number"));
          row.appendChild(cell("td", prediction.horse_id));
          row.appendChild(cell("td", prediction.excluded ? "対象外" : `${(prediction.probability * 100).toFixed(1)}%`, "number"));
          row.appendChild(cell("td", prediction.actual_finish == null ? "-" : `${prediction.actual_finish}着`, "number"));
          body.appendChild(row);
        });
        table.appendChild(body);
        result.appendChild(table);
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
'''

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
        'dam': None,
        'banushi': None
    }

    # 馬主マークURLの抽出（.db_prof_table 内の最初のimg）
    prof_table = soup.find(class_='db_prof_table')
    if prof_table:
        prof_img = prof_table.find('img')
        if prof_img and prof_img.get('src'):
            horse_data['banushi'] = prof_img['src']

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
                    # 障3110 → 障害3110m、ダ1600 → ダート1600m、芝1800 → 芝1800m
                    if '障' in distance_text:
                        race_info['surface'] = '障害'
                    elif 'ダ' in distance_text:
                        race_info['surface'] = 'ダート'
                    else:
                        race_info['surface'] = '芝'
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


@app.route('/debug_last_saved', methods=['GET'])
def debug_last_saved():
    """直近に保存されたレース結果と horse_data_dtl の状況を確認するデバッグAPI"""
    try:
        with get_analysis_connection() as conn:
            latest_race = conn.execute('''
                SELECT race_id, race_date, course, surface, distance, race_name, last_seen_at
                FROM race_master
                ORDER BY last_seen_at DESC
                LIMIT 1
            ''').fetchone()

            if not latest_race:
                return jsonify({'message': 'race_master is empty'}), 200

            race_id = latest_race[0]
            entries = conn.execute('''
                SELECT horse_number, horse_id, horse_name, gate, jockey, finish_position
                FROM race_entry
                WHERE race_id = ?
                ORDER BY finish_position ASC NULLS LAST, horse_number ASC
            ''', (race_id,)).fetchall()

            dtl_records = conn.execute('''
                SELECT horse_id, race_date, course, race_id, finish_position, jockey, finish_time, margin, last_3f
                FROM horse_data_dtl
                WHERE race_id = ?
                ORDER BY finish_position ASC NULLS LAST
            ''', (race_id,)).fetchall()

            return jsonify({
                'latest_race': {
                    'race_id': latest_race[0],
                    'race_date': latest_race[1],
                    'course': latest_race[2],
                    'surface': latest_race[3],
                    'distance': latest_race[4],
                    'race_name': latest_race[5],
                    'last_seen_at': latest_race[6],
                },
                'race_entry_count': len(entries),
                'race_entries_preview': [
                    {'num': e[0], 'id': e[1], 'name': e[2], 'gate': e[3], 'jockey': e[4], 'finish': e[5]}
                    for e in entries[:5]
                ],
                'horse_data_dtl_count': len(dtl_records),
                'horse_data_dtl_preview': [
                    {'id': d[0], 'date': d[1], 'course': d[2], 'finish': d[4], 'jockey': d[5], 'time': d[6], 'margin': d[7], '3f': d[8]}
                    for d in dtl_records[:5]
                ],
            }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save_race', methods=['POST'])
def save_race():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object body is required'}), 400

    connection = None
    try:
        connection = get_analysis_connection()
        result = save_race_page(
            connection,
            race=data.get('race'),
            page_type=data.get('page_type'),
            fetched_at=data.get('fetched_at'),
            source_url=data.get('source_url'),
            html=data.get('html'),
            snapshot_id=data.get('snapshot_id'),
        )
        print(f"🏁 [save_race] {data.get('page_type')} 保存完了: race_id={result.get('race_id')} ({result.get('entry_count')}頭)", flush=True)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except sqlite3.Error as error:
        app.logger.exception('Failed to save race page')
        return jsonify({'error': f'Database error: {error}'}), 500
    finally:
        if connection is not None:
            connection.close()

    return jsonify(result), 200


@app.route('/save_horse_for_race', methods=['POST'])
def save_horse_for_race():
    """
    出馬表ボタン用: 馬ページHTMLを受け取り、shutuba_date より前の過去走のみ
    horse_data_dtl に保存する。

    出走数比較は /save と同じ方式（HTML出走数 vs DB出走数）。
    /save とは独立しており、/save の動作を変更しない。
    """
    try:
        data = request.get_json()
        horse_id = data.get('horseId')
        html = data.get('html')
        shutuba_date = data.get('raceDate')   # 'YYYY/MM/DD'
        force = data.get('force', False)

        if not horse_id or not html:
            return jsonify({'error': 'Invalid data'}), 400
        if not shutuba_date or not isinstance(shutuba_date, str):
            return jsonify({'error': 'raceDate is required (YYYY/MM/DD)'}), 400

        # --- 既存関数をそのまま再利用 ---
        race_count = count_race_tr(html)
        horse_data, race_data = parse_horse_html(html, horse_id)

        # gzip圧縮 + base64エンコード（horse_html.db 保存用）
        compressed_html = gzip.compress(html.encode('utf-8'))
        encoded_html = base64.b64encode(compressed_html).decode('ascii')
        saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # データリーク防止: shutuba_date より前の過去走のみ対象
        filtered_race_data = [
            r for r in race_data
            if r.get('race_date') and r['race_date'] < shutuba_date
        ]

        try:
            with get_analysis_connection() as analysis_conn:
                # --- /save と同じ出走数比較ロジック ---
                cur = analysis_conn.execute(
                    'SELECT COUNT(*) FROM horse_data_dtl WHERE horse_id = ?',
                    (horse_id,)
                )
                row = cur.fetchone()
                db_race_count = row[0] if row else 0

                # horse_html.db にすでにHTMLが保存されているか確認
                html_exists = False
                try:
                    with get_connection() as html_check_conn:
                        h_row = html_check_conn.execute(
                            'SELECT 1 FROM horse_html WHERE horse_id = ?',
                            (horse_id,)
                        ).fetchone()
                        html_exists = h_row is not None
                except Exception:
                    pass

                # 出走数比較（ただし horse_html.db にまだHTMLがない場合は保存を継続する）
                if not force and db_race_count >= race_count and html_exists:
                    print(f"⏩ [save_horse_for_race] {horse_id} スキップ (DB出走数:{db_race_count} >= HTML出走数:{race_count})", flush=True)
                    return jsonify({
                        'message': f'{horse_id} skipped (db={db_race_count} >= html={race_count})',
                        'skipped': True,
                        'db_race_count': db_race_count,
                        'html_race_count': race_count,
                    }), 200

                # 1. horse_html.db に保存（GET /html/<horse_id> で「適性」「解析」ボタンが利用するため）
                for attempt in range(5):
                    try:
                        with get_connection() as html_conn:
                            html_conn.execute('''
                                INSERT OR REPLACE INTO horse_html (horse_id, html, saved_at, race_count)
                                VALUES (?, ?, ?, ?)
                            ''', (horse_id, encoded_html, saved_at, race_count))
                        break
                    except sqlite3.OperationalError:
                        time.sleep(0.5)

                # 2. 馬基本情報: banushiのみ上書き更新、血統情報は既存値を保持
                analysis_conn.execute('''
                    INSERT INTO horse_data_hd
                    (horse_id, horse_name, sire, dam, banushi)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(horse_id) DO UPDATE SET
                        banushi = COALESCE(excluded.banushi, horse_data_hd.banushi)
                ''', (
                    horse_data['horse_id'],
                    horse_data['horse_name'],
                    horse_data['sire'],
                    horse_data['dam'],
                    horse_data['banushi'],
                ))

                # 過去走保存: /save と同じ INSERT ... ON CONFLICT DO UPDATE
                # ただし対象は shutuba_date より前のレースのみ
                saved_count = 0
                for race in filtered_race_data:
                    if not race['race_id']:
                        continue
                    try:
                        values = (
                            race['horse_id'], race['race_date'],
                            race['course'], race['race_id'], race['field_size'],
                            race['gate'], race['horse_number'], race['popularity'],
                            race['finish_position'], race['jockey'], race['carried_weight'],
                            race['surface'], race['distance'], race['track_condition'],
                            race['finish_time'], race['margin'], race['passing_order'],
                            race['pace'], race['last_3f'], race['horse_weight'],
                            race['race_class'], race['last_3f_rank'],
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
                        saved_count += 1
                    except Exception:
                        continue

        except sqlite3.Error as e:
            app.logger.exception('save_horse_for_race: DB error for %s', horse_id)
            return jsonify({'error': f'Database error: {e}'}), 500

        print(f"✅ [save_horse_for_race] {horse_id} 保存完了 (対象日前過去走:{saved_count}件 / HTML出走数:{race_count} / DB既存:{db_race_count})", flush=True)
        return jsonify({
            'message': f'{horse_id} saved ({saved_count} races before {shutuba_date})',
            'skipped': False,
            'saved_count': saved_count,
        }), 200

    except Exception as e:
        return jsonify({'error': f'Unexpected error: {e}'}), 500


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
                        # 馬基本情報の保存（banushiのみ上書き更新、他は既存値を保持）
                        analysis_conn.execute('''
                            INSERT INTO horse_data_hd
                            (horse_id, horse_name, sire, dam, banushi)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(horse_id) DO UPDATE SET
                                banushi = COALESCE(excluded.banushi, horse_data_hd.banushi)
                        ''', (
                            horse_data['horse_id'],
                            horse_data['horse_name'],
                            horse_data['sire'],
                            horse_data['dam'],
                            horse_data['banushi']
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
promotion_second_context_model = None
jra_dirt_maiden_model_data = None
jra_turf_2000_upper_model_data = None
jra_turf_1200_upper_model_data = None


def load_promotion_second_context_model():
    """Load the pooled context model for promotion-second predictions."""
    global promotion_second_context_model
    if promotion_second_context_model is None:
        with open('promotion_second_context.pkl', 'rb') as f:
            promotion_second_context_model = pickle.load(f)
    return promotion_second_context_model

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


def load_jra_dirt_maiden_model():
    """Load the pooled JRA dirt maiden model once."""
    global jra_dirt_maiden_model_data
    if jra_dirt_maiden_model_data is None:
        from dirt_maiden_model import DIRT_MAIDEN_MODEL_FILE

        with open(DIRT_MAIDEN_MODEL_FILE, 'rb') as model_file:
            jra_dirt_maiden_model_data = pickle.load(model_file)
    return jra_dirt_maiden_model_data


def load_jra_turf_2000_upper_model():
    """Load the pooled JRA turf 2000m upper-class model once."""
    global jra_turf_2000_upper_model_data
    if jra_turf_2000_upper_model_data is None:
        from jra_turf_2000_upper_model import MODEL_FILE

        with open(MODEL_FILE, 'rb') as model_file:
            jra_turf_2000_upper_model_data = pickle.load(model_file)
    return jra_turf_2000_upper_model_data


def load_jra_turf_1200_upper_model():
    """Load the pooled JRA turf 1200m upper-class model once."""
    global jra_turf_1200_upper_model_data
    if jra_turf_1200_upper_model_data is None:
        from jra_turf_1200_upper_model import MODEL_FILE

        with open(MODEL_FILE, 'rb') as model_file:
            jra_turf_1200_upper_model_data = pickle.load(model_file)
    return jra_turf_1200_upper_model_data


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
        'last_jockey',  # horse_idはtrain_models_by_condition.pyで既に削除済み
        'last_popularity',  # 人気系（削除）
        'avg_popularity',   # 人気系（削除）
        'prev_course',  # 文字列特徴量（削除）
        'prev_distance',  # 文字列特徴量（削除）
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

@app.route('/backtest', methods=['GET'])
def backtest_page():
    return render_template_string(BACKTEST_PAGE)


@app.route('/backtest/run', methods=['POST'])
def run_backtest():
    data = request.get_json(silent=True) or {}
    race_id = data.get('race_id')
    if not isinstance(race_id, str) or re.fullmatch(r'\d{12}', race_id) is None:
        return jsonify({'error': 'race_id must be a 12-digit race ID'}), 400

    try:
        from backtest_race import backtest_race
        predictions = backtest_race(
            race_id,
            target_race=data.get('target_race'),
        )
    except ValueError as error:
        app.logger.warning('Backtest could not run for %s: %s', race_id, error)
        return jsonify({'error': str(error)}), 422
    except Exception as error:
        app.logger.exception('Backtest failed for %s', race_id)
        return jsonify({'error': f'バックテスト中にエラーが発生しました: {error}'}), 500

    if not predictions:
        return jsonify({'error': '検証結果に出走馬がありません。'}), 500

    return jsonify({
        'race_id': race_id,
        'race_date': predictions[0]['race_date'],
        'course': predictions[0]['course'],
        'surface': predictions[0]['surface'],
        'distance': predictions[0]['distance'],
        'training_through_date': predictions[0]['training_through_date'],
        'prediction_mode': 'backtest',
        'predictions': [
            {
                'horse_id': row['horse_id'],
                'probability': row['probability'],
                'excluded': row.get('excluded', False),
                'error': row.get('error'),
                'actual_finish': row['actual_finish'],
                'features': row['features'],
            }
            for row in predictions
        ],
    })


@app.route('/batch_horse_data', methods=['POST'])
def batch_horse_data():
    """
    出走馬の過去レースデータを一括取得する。

    Request:
        {
            "horse_ids": ["horse_id1", "horse_id2", ...],
            "race_date": "2024/01/01"  # オプション。この日より前のレースのみ取得
        }

    Response:
        {
            "horses": {
                "horse_id1": {
                    "horse_id": "horse_id1",
                    "horse_name": "馬名",
                    "sire": "父",
                    "dam": "母",
                    "race_history": [
                        {
                            "race_date": "2024/01/01",
                            "course": "東京",
                            "race_id": "202401010101",
                            "field_size": 18,
                            "gate": 3,
                            "horse_number": 5,
                            "popularity": 2,
                            "finish_position": 1,
                            "jockey": "騎手名",
                            "carried_weight": 57.0,
                            "surface": "芝",
                            "distance": 1400,
                            "track_condition": "良",
                            "finish_time": "1:20.5",
                            "margin": 0.0,
                            "passing_order": "3-3-2-1",
                            "pace": "H",
                            "last_3f": 35.2,
                            "horse_weight": 480,
                            "race_class": "3勝クラス",
                            "last_3f_rank": 1
                        }
                    ]
                }
            }
        }
    """
    try:
        data = request.get_json()
        horse_ids = data.get('horse_ids', [])
        race_date = data.get('race_date', None)

        if not isinstance(horse_ids, list) or not horse_ids:
            return jsonify({'error': 'horse_ids is required'}), 400

        # 重複排除
        horse_ids = list(dict.fromkeys(horse_ids))

        parsed_race_date = None
        if isinstance(race_date, str):
            try:
                parsed_race_date = parse_date(race_date)
            except Exception:
                parsed_race_date = None

        placeholders = ','.join(['?'] * len(horse_ids))

        with get_analysis_connection() as conn:
            # 馬基本情報を一括取得
            hd_rows = conn.execute(f'''
                SELECT horse_id, horse_name, sire, dam, banushi
                FROM horse_data_hd
                WHERE horse_id IN ({placeholders})
            ''', horse_ids).fetchall()
            horse_master = {}
            for row in hd_rows:
                horse_master[row[0]] = {
                    'horse_id': row[0],
                    'horse_name': row[1],
                    'sire': row[2],
                    'dam': row[3],
                    'banushi': row[4],
                }

            # 過去レース情報を一括取得
            if parsed_race_date is not None:
                target_date_str = parsed_race_date.strftime('%Y/%m/%d')
                dtl_cur = conn.execute(f'''
                    SELECT *
                    FROM horse_data_dtl
                    WHERE horse_id IN ({placeholders})
                      AND race_date < ?
                    ORDER BY horse_id, race_date DESC
                ''', (*horse_ids, target_date_str))
            else:
                dtl_cur = conn.execute(f'''
                    SELECT *
                    FROM horse_data_dtl
                    WHERE horse_id IN ({placeholders})
                    ORDER BY horse_id, race_date DESC
                ''', horse_ids)

            columns = [d[0] for d in dtl_cur.description] if dtl_cur.description else []
            dtl_rows = dtl_cur.fetchall()

        # 馬ごとにグループ化
        horse_histories = {}
        for row in dtl_rows:
            row_dict = dict(zip(columns, row))
            hid = row_dict['horse_id']
            if hid not in horse_histories:
                horse_histories[hid] = []
            horse_histories[hid].append(row_dict)

        # レスポンス構築
        horses = {}
        for hid in horse_ids:
            master = horse_master.get(hid, {
                'horse_id': hid,
                'horse_name': None,
                'sire': None,
                'dam': None,
                'banushi': None,
            })
            horses[hid] = {
                'horse_id': master['horse_id'],
                'horse_name': master['horse_name'],
                'sire': master['sire'],
                'dam': master['dam'],
                'banushi': master['banushi'],
                'race_history': horse_histories.get(hid, []),
            }

        return jsonify({'horses': horses}), 200

    except Exception as e:
        app.logger.exception('batch_horse_data failed')
        return jsonify({'error': str(e)}), 500


@app.route('/save_banushi', methods=['POST'])
def save_banushi():
    """
    馬主マークURLを保存する。

    Request:
        {
            "horse_id": "horse_id",
            "banushi": "https://example.com/mark.png"
        }

    Response:
        {
            "success": true
        }
    """
    try:
        data = request.get_json()
        horse_id = data.get('horse_id')
        banushi = data.get('banushi')

        if not horse_id:
            return jsonify({'error': 'horse_id is required'}), 400

        with get_analysis_connection() as conn:
            # 馬が存在するか確認
            cur = conn.execute('SELECT 1 FROM horse_data_hd WHERE horse_id = ?', (horse_id,))
            if not cur.fetchone():
                # 馬が存在しない場合は新規作成
                conn.execute('''
                    INSERT INTO horse_data_hd (horse_id, horse_name, sire, dam, banushi)
                    VALUES (?, ?, ?, ?, ?)
                ''', (horse_id, None, None, None, banushi))
            else:
                # 既存の馬のbanushiを更新
                conn.execute('''
                    UPDATE horse_data_hd
                    SET banushi = ?
                    WHERE horse_id = ?
                ''', (banushi, horse_id))

        return jsonify({'success': True}), 200

    except Exception as e:
        app.logger.exception('save_banushi failed')
        return jsonify({'error': str(e)}), 500


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
        horse_gates = data.get('horse_gates')
        parsed_race_date = parse_date(race_date) if isinstance(race_date, str) else None
        
        if not isinstance(horse_ids, list) or not horse_ids:
            return jsonify({'error': 'horse_ids is required'}), 400
        if not isinstance(horse_gates, list) and horse_gates is not None:
            return jsonify({'error': 'horse_gates must be an array'}), 400
        if horse_gates is None:
            horse_gates = [None] * len(horse_ids)
        if len(horse_gates) != len(horse_ids):
            return jsonify({'error': 'horse_gates must match the number of horse_ids'}), 400

        from feature_engineering import parse_field_size, parse_gate
        target_field_size = data.get('field_size', len(horse_ids))
        target_field_size = parse_field_size(target_field_size)
        if target_field_size is None:
            return jsonify({'error': 'field_size must be an integer from 1 to 30'}), 400
        parsed_horse_gates = []
        for gate in horse_gates:
            parsed_gate = parse_gate(gate)
            if gate is not None and parsed_gate is None:
                return jsonify({'error': 'horse_gates values must be null or integers from 1 to 8'}), 400
            parsed_horse_gates.append(parsed_gate)
        
        model_group = None
        model_feature_columns = None
        use_jra_dirt_maiden_model = False
        use_jra_turf_2000_upper = False
        use_jra_turf_1200_upper = False
        model_data_warning = None
        # レース条件が提供されている場合、レース条件ごとのモデルを使用
        if race_course and race_distance and race_surface:
            if parsed_race_date is None:
                return jsonify({
                    'error': 'race_date is required and must be a valid YYYY/MM/DD date',
                }), 400
            if race_class is None:
                return jsonify({'error': 'race_class is required for race-condition prediction'}), 400
            try:
                race_class = int(race_class)
            except (TypeError, ValueError):
                return jsonify({'error': 'race_class must be an integer from 0 to 9'}), 400
            if not 0 <= race_class <= 9:
                return jsonify({'error': 'race_class must be an integer from 0 to 9'}), 400

            race_id = data.get('race_id')
            is_today_race = parsed_race_date.date() == datetime.date.today()
            if is_today_race and race_id is not None:
                if not isinstance(race_id, str) or re.fullmatch(r'\d{12}', race_id) is None:
                    return jsonify({'error': 'race_id must be a 12-digit race ID'}), 400
                if race_has_recorded_winner(race_id):
                    from backtest_race import backtest_race

                    target_race = {
                        'race_date': parsed_race_date.strftime('%Y/%m/%d'),
                        'course': race_course,
                        'surface': race_surface,
                        'distance': race_distance,
                        'race_class': race_class,
                        'field_size': target_field_size,
                        'horses': [
                            {
                                'horse_id': str(horse_id),
                                'gate': parsed_horse_gates[index],
                            }
                            for index, horse_id in enumerate(horse_ids)
                        ],
                    }
                    try:
                        backtest_predictions = backtest_race(
                            race_id,
                            target_race=target_race,
                        )
                    except ValueError as error:
                        app.logger.warning(
                            'Same-day backtest could not run for %s: %s',
                            race_id,
                            error,
                        )
                        return jsonify({'error': str(error)}), 422
                    except Exception as error:
                        app.logger.exception(
                            'Same-day backtest failed for %s',
                            race_id,
                        )
                        return jsonify({
                            'error': (
                                f'バックテスト中にエラーが発生しました: {error}'
                            ),
                        }), 500
                    if not backtest_predictions:
                        return jsonify({
                            'error': '検証結果に出走馬がありません。',
                        }), 500
                    response = {
                        'predictions': [
                            {
                                'horse_id': row['horse_id'],
                                'probability': row['probability'],
                                'excluded': row.get('excluded', False),
                                'error': row.get('error'),
                                'actual_finish': row.get('actual_finish'),
                                'features': row.get('features'),
                            }
                            for row in backtest_predictions
                        ],
                        'race_date': parsed_race_date.strftime('%Y/%m/%d'),
                        'model_loaded': True,
                        'model_group': backtest_predictions[0].get('model_group'),
                        'prediction_mode': 'backtest',
                        'training_through_date': backtest_predictions[0].get(
                            'training_through_date'
                        ),
                    }
                    if (
                        backtest_predictions[0].get('model_group')
                        == 'jra_dirt_maiden'
                    ):
                        try:
                            response['model_data_quality_warning'] = (
                                load_jra_dirt_maiden_model().get(
                                    'data_quality_warning'
                                )
                            )
                        except FileNotFoundError:
                            response['model_data_quality_warning'] = (
                                'Training data contains incomplete race fields; '
                                'probabilities may be biased.'
                            )
                    elif (
                        backtest_predictions[0].get('model_group')
                        == 'jra_turf_2000_upper'
                    ):
                        response['model_data_quality_warning'] = (
                            load_jra_turf_2000_upper_model().get(
                                'data_quality_warning'
                            )
                        )
                    elif (
                        backtest_predictions[0].get('model_group')
                        == 'jra_turf_1200_upper'
                    ):
                        response['model_data_quality_warning'] = (
                            load_jra_turf_1200_upper_model().get(
                                'data_quality_warning'
                            )
                        )
                    return jsonify(response), 200

            from dirt_maiden_model import (
                is_debut_horse,
                is_jra_dirt_maiden,
            )
            from jra_turf_2000_upper_model import (
                is_jra_turf_2000_upper,
            )
            from jra_turf_1200_upper_model import (
                is_jra_turf_1200_upper,
            )

            use_jra_dirt_maiden_model = is_jra_dirt_maiden(
                race_course,
                race_surface,
                race_class,
            )
            use_jra_turf_2000_upper = is_jra_turf_2000_upper(
                race_course,
                race_surface,
                race_distance,
                race_class,
            )
            use_jra_turf_1200_upper = is_jra_turf_1200_upper(
                race_course,
                race_surface,
                race_distance,
                race_class,
            )
            if use_jra_dirt_maiden_model:
                try:
                    model_data = load_jra_dirt_maiden_model()
                except FileNotFoundError:
                    return jsonify({
                        'error': (
                            'JRA dirt maiden model is not trained. '
                            'Run dirt_maiden_model.py after verifying the '
                            'race data completeness.'
                        )
                    }), 404
                model_group = 'jra_dirt_maiden'
                model_data_warning = model_data.get('data_quality_warning')
            elif use_jra_turf_2000_upper:
                try:
                    model_data = load_jra_turf_2000_upper_model()
                except FileNotFoundError:
                    return jsonify({
                        'error': (
                            'JRA turf 2000m upper-class model is not '
                            'trained. Run jra_turf_2000_upper_model.py.'
                        )
                    }), 404
                model_group = 'jra_turf_2000_upper'
                model_data_warning = model_data.get('data_quality_warning')
            elif use_jra_turf_1200_upper:
                try:
                    model_data = load_jra_turf_1200_upper_model()
                except FileNotFoundError:
                    return jsonify({
                        'error': (
                            'JRA turf 1200m upper-class model is not '
                            'trained. Run jra_turf_1200_upper_model.py.'
                        )
                    }), 404
                model_group = 'jra_turf_1200_upper'
                model_data_warning = model_data.get('data_quality_warning')
            else:
                model_group = (
                    'condition' if 2 <= race_class <= 4 else 'other'
                )
                model_data = load_model_by_condition(
                    race_course,
                    race_distance,
                    race_surface,
                    model_group,
                )
                if not model_data:
                    return jsonify({
                        'error': (
                            f'Model not found for {race_course} '
                            f'{race_surface} {race_distance}m '
                            f'({model_group})'
                        )
                    }), 404

            model_instance = model_data['model']
            model_feature_columns = model_data.get('feature_columns')
        else:
            # レース条件が提供されていない場合はエラーを返す
            return jsonify({'error': 'race_course, race_distance, race_surface, and race_class are required'}), 400

        if model_feature_columns is None:
            app.logger.error(
                'Prediction model for %s did not provide feature columns',
                model_group,
            )
            return jsonify({
                'error': 'The selected prediction model has no feature columns',
            }), 500

        from feature_engineering import calculate_horse_features, get_horse_race_history
        
        predictions = []
        
        for horse_index, horse_id in enumerate(horse_ids):
            try:
                # レース履歴を取得
                race_history = get_horse_race_history(horse_id)
                
                # 特徴量を計算
                try:
                    features = calculate_horse_features(
                        horse_id,
                        race_history,
                        parsed_race_date,
                        race_distance,
                        race_surface,
                        race_course,
                        race_class,
                        target_gate=parsed_horse_gates[horse_index],
                        target_field_size=target_field_size,
                    )
                    if use_jra_dirt_maiden_model:
                        from dirt_maiden_model import add_dirt_maiden_features

                        add_dirt_maiden_features(
                            features,
                            race_history,
                            parsed_race_date,
                            race_distance,
                            race_course,
                        )
                    if use_jra_turf_2000_upper or use_jra_turf_1200_upper:
                        from jra_turf_2000_upper_model import (
                            add_jra_course_features,
                        )

                        add_jra_course_features(features, race_course)
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

                if (
                    use_jra_dirt_maiden_model
                    and is_debut_horse(features)
                ):
                    predictions.append({
                        'horse_id': horse_id,
                        'probability': None,
                        'excluded': True,
                        'error': '初出走で過去走がないため、予測対象外です。',
                        'features': features,
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
                    if model_group == 'condition' and features.get('is_promotion_2nd') == 1:
                        context_artifact = load_promotion_second_context_model()
                        context_values = np.asarray([
                            [
                                np.nan if value is None else float(value)
                                for value in get_promotion_second_context_values(features)
                            ]
                        ])
                        context_probability = context_artifact['model'].predict_proba(
                            context_values
                        )[0, 1]
                        probability = apply_promotion_second_boost(
                            probability,
                            features.get('is_promotion_2nd'),
                            context_probability=context_probability,
                            context_base_rate=context_artifact['base_rate'],
                        )
                    elif model_group == 'condition':
                        probability = apply_promotion_second_boost(
                            probability,
                            features.get('is_promotion_2nd'),
                        )

                    # 近走の成績と得意コース・距離のバランスを調整
                    from feature_engineering import apply_recent_performance_balance
                    probability = apply_recent_performance_balance(
                        probability,
                        features,
                        threshold_recent=6,
                        threshold_performance=0.3,
                        penalty_factor=0.3,
                        rescue_factor=1.35,
                        bonus_factor=1.0,
                    )
                    from feature_engineering import (
                        apply_unwon_maiden_class_challenge_penalty,
                    )
                    probability = apply_unwon_maiden_class_challenge_penalty(
                        probability,
                        features,
                    )
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
        predictions.sort(
            key=lambda item: (
                not item.get('excluded', False),
                item.get('probability') or 0,
            ),
            reverse=True,
        )
        
        # Final predictions: {predictions}
        pass
        
        response = {
            'predictions': predictions,
            'race_date': parsed_race_date.strftime('%Y/%m/%d') if parsed_race_date else None,
            'model_loaded': True,
            'model_group': model_group,
            'prediction_mode': 'live',
        }
        if model_data_warning:
            response['model_data_quality_warning'] = model_data_warning
        return jsonify(response), 200
    
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
        # 単一モデルは廃止されたため、エラーを返す
        return jsonify({'error': 'predict_single endpoint is deprecated. Use /predict with race conditions instead.'}), 400
        
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
