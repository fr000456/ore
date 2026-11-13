import gzip
import base64
import sqlite3
import re
from bs4 import BeautifulSoup

SOURCE_DB = 'horse_html.db'
TARGET_DB = 'horse_analysis.db'


def decompress_html(encoded_html):
    try:
        decoded = base64.b64decode(encoded_html)
        return gzip.decompress(decoded).decode('utf-8')
    except Exception:
        return None


def main():
    source_conn = sqlite3.connect(SOURCE_DB, timeout=10, isolation_level=None)
    target_conn = sqlite3.connect(TARGET_DB, timeout=10, isolation_level=None)

    cur = source_conn.execute('SELECT horse_id, html FROM horse_html')
    total = 0
    updated = 0
    errors = 0

    for horse_id, encoded_html in cur:
        total += 1
        html = decompress_html(encoded_html)
        if not html:
            errors += 1
            continue

        soup = BeautifulSoup(html, 'html.parser')
        race_table = soup.find('table', class_='db_h_race_results')
        if not race_table:
            continue

        updates = []
        for row in race_table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) < 25:
                continue
            distance_text = cols[14].text.strip()
            if '障' not in distance_text:
                continue
            race_link = cols[4].find('a')
            if not race_link:
                continue
            match = race_link['href'].split('/race/')[-1].split('/')[0]
            if not match.isdigit():
                continue
            updates.append((horse_id, int(match)))

        for hid, rid in updates:
            cur2 = target_conn.execute(
                "UPDATE horse_data_dtl SET surface='障害' "
                "WHERE horse_id=? AND race_id=? AND surface='芝'",
                (hid, rid)
            )
            updated += cur2.rowcount

        if total % 500 == 0:
            print(f'{total}頭処理済み / 更新{updated}件')

    print(f'完了: {total}頭処理, {updated}件を障害に更新, 解凍失敗{errors}件')


if __name__ == '__main__':
    main()
