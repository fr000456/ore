import gzip
import base64
import sqlite3
import datetime
import time
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = 'horse_html.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_db():
    if not os.path.exists(DB_PATH):
        with get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS horse_html (
                    horse_id TEXT PRIMARY KEY,
                    html TEXT NOT NULL,  -- 既存列名に対応
                    saved_at TEXT NOT NULL,
                    race_count INTEGER DEFAULT 0
                )
            ''')
            print("✅ DB 初期化完了")

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

    # <tr> をカウント
    return table_html.count('<tr')

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
                    print(f"⚠️ DB is locked (retry {attempt + 1}/5)")
                    time.sleep(1)
                else:
                    return jsonify({'error': f'Database error: {e}'}), 500

        return jsonify({'error': 'Database is locked'}), 500

    except Exception as e:
        return jsonify({'error': f'Unexpected error: {e}'}), 500

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
