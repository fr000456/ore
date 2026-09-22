import gzip
import base64
import sqlite3
from bs4 import BeautifulSoup

# 既存DB（圧縮HTML）
SOURCE_DB = 'horse_html.db'

# 新規DB（解析用）
TARGET_DB = 'horse_analysis.db'

def get_source_connection():
    """既存DB（圧縮HTML）の接続"""
    conn = sqlite3.connect(SOURCE_DB, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def get_target_connection():
    """新規DB（解析用）の接続"""
    conn = sqlite3.connect(TARGET_DB, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def decompress_html(encoded_html):
    """圧縮HTMLを解凍"""
    try:
        decoded = base64.b64decode(encoded_html)
        html_str = gzip.decompress(decoded).decode('utf-8')
        return html_str
    except Exception as e:
        print(f"❌ 解凍エラー: {e}")
        return None

def parse_horse_html(html):
    """馬HTMLを解析して馬基本情報とレース情報を抽出"""
    soup = BeautifulSoup(html, 'html.parser')

    # 馬基本情報の抽出
    horse_data = {
        'horse_id': None,
        'horse_name': None,
        'sire': None,
        'dam': None
    }



      # 馬名の抽出
    # 馬ページ上部の馬名を取得する
    horse_name_element = soup.select_one('.horse_title h1')

    if horse_name_element:
        horse_data['horse_name'] = horse_name_element.get_text(strip=True)
    else:
 
        # フォールバック：戦績テーブルのsummary
        race_table = soup.find('table', class_='db_h_race_results')
        if race_table and race_table.get('summary'):
            summary = race_table.get('summary')
            horse_name = summary.split('の競走戦績')[0] if 'の競走戦績' in summary else summary
            horse_data['horse_name'] = horse_name
    
    # それでも取得できない場合
    if not horse_data['horse_name']:
        horse_data['horse_name'] = horse_data['horse_id'] if horse_data['horse_id'] else "unknown"
        
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
                'horse_id': horse_data['horse_id'],
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

            # 各カラムの抽出（実際のHTML構造に合わせて調整）
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

                # 馬場指数をスキップ
                # タイム
                race_info['finish_time'] = cols[18].text.strip()

                # 着差
                margin_text = cols[19].text.strip()
                race_info['margin'] = float(margin_text) if margin_text.replace('.', '').isdigit() else None

                # タイム指数をスキップ
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
                print(f"⚠️ レース解析エラー: {e}")
                continue

            race_data.append(race_info)

    return horse_data, race_data

def migrate_data():
    """圧縮HTMLから解析用DBへデータ移行"""
    print("🚀 データ移行開始")

    try:
        with get_source_connection() as source_conn, get_target_connection() as target_conn:
            # 既存DBから全てのhorse_idを取得
            cur = source_conn.execute('SELECT horse_id FROM horse_html')
            horse_ids = cur.fetchall()

            print(f"Total horses to migrate: {len(horse_ids)}")

            for i, (horse_id,) in enumerate(horse_ids, 1):
                print(f"Processing {i}/{len(horse_ids)}: horse_id={horse_id}")

                # 圧縮HTMLを取得
                cur = source_conn.execute(
                    'SELECT html FROM horse_html WHERE horse_id = ?',
                    (horse_id,)
                )
                row = cur.fetchone()
                if not row:
                    continue

                # HTML解凍
                html = decompress_html(row[0])
                if not html:
                    continue

                # HTML解析
                horse_data, race_data = parse_horse_html(html)

                # 元のデータベースのhorse_idを使用
                horse_data['horse_id'] = horse_id

                # 馬基本情報を保存
                if horse_data['horse_id']:
                    # horse_idの型を確認
                    try:
                        target_conn.execute('''
                            INSERT OR REPLACE INTO horse_data_hd
                            (horse_id, horse_name, sire, dam)
                            VALUES (?, ?, ?, ?)
                        ''', (
                            horse_data['horse_id'],
                            horse_data['horse_name'],
                            horse_data['sire'],
                            horse_data['dam']
                        ))
                    except Exception as e:
                        print(f"HD INSERTエラー: horse_id={horse_data['horse_id']}, error={e}")
                else:
                    print(f"horse_id取得失敗: 元DB horse_id={horse_id}")

                for race in race_data:
                    # 元のデータベースのhorse_idを使用
                    race['horse_id'] = horse_id

                    # race_idがNoneの場合はスキップ
                    if not race['race_id']:
                        continue

                    try:
                        target_conn.execute('''
                            INSERT OR REPLACE INTO horse_data_dtl
                            (horse_id, race_date, course, race_id,
                             field_size, gate, horse_number, popularity, finish_position,
                             jockey, carried_weight, surface, distance, track_condition,
                             finish_time, margin, passing_order, pace, last_3f, horse_weight)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            race['horse_id'], race['race_date'],
                            race['course'], race['race_id'], race['field_size'],
                            race['gate'], race['horse_number'], race['popularity'],
                            race['finish_position'], race['jockey'], race['carried_weight'],
                            race['surface'], race['distance'], race['track_condition'],
                            race['finish_time'], race['margin'], race['passing_order'],
                            race['pace'], race['last_3f'], race['horse_weight']
                        ))
                    except Exception as e:
                        print(f"DTL INSERTエラー: horse_id={race['horse_id']}, race_id={race['race_id']}, error={e}")

                print(f"Saved {len(race_data)} race records for horse_id={horse_id}")

            print("Data migration completed")

    except Exception as e:
        print(f"❌ 移行エラー: {e}")

if __name__ == '__main__':
    migrate_data()
