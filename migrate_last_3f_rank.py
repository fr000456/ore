import argparse
import base64
import gzip
import re
import sqlite3

from bs4 import BeautifulSoup
from race_metadata import get_last_3f_rank

SOURCE_DB = 'horse_html.db'
TARGET_DB = 'horse_analysis.db'
BATCH_SIZE = 100

RACE_ID_PATTERN = re.compile(r'/race/(\d+)')
def migrate_last_3f_rank(dry_run=False):
    source_conn = sqlite3.connect(SOURCE_DB, timeout=30)
    target_conn = sqlite3.connect(TARGET_DB, timeout=30)

    try:
        target_columns = {
            row[1] for row in target_conn.execute('PRAGMA table_info(horse_data_dtl)')
        }
        if 'last_3f_rank' not in target_columns:
            raise RuntimeError(
                'horse_data_dtl.last_3f_rank is missing; add the column before migration'
            )

        target_rows = target_conn.execute(
            'SELECT horse_id, race_id FROM horse_data_dtl'
        ).fetchall()
        target_keys = set(target_rows)
        del target_rows

        total_horses = source_conn.execute(
            'SELECT COUNT(*) FROM horse_html'
        ).fetchone()[0]
        source_rows = source_conn.execute(
            'SELECT horse_id, html FROM horse_html ORDER BY horse_id'
        )

        processed_horses = 0
        timed_html_rows = 0
        matched_rows = 0
        updated_rows = 0
        unmatched_rows = 0
        failed_horses = 0
        rank_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        pending_updates = []

        update_sql = '''
            UPDATE horse_data_dtl
            SET last_3f_rank = ?
            WHERE horse_id = ? AND race_id = ? AND last_3f_rank IS NULL
        '''

        for horse_id, encoded_html in source_rows:
            processed_horses += 1
            try:
                html = gzip.decompress(base64.b64decode(encoded_html)).decode('utf-8')
                soup = BeautifulSoup(html, 'html.parser')
                race_table = soup.find('table', class_='db_h_race_results')
                if race_table is None:
                    continue

                for row in race_table.find_all('tr')[1:]:
                    cells = row.find_all('td')
                    if len(cells) <= 23:
                        continue

                    rank = get_last_3f_rank(cells[23])
                    if rank is None:
                        continue

                    race_link = cells[4].find('a')
                    match = RACE_ID_PATTERN.search(
                        race_link.get('href', '') if race_link else ''
                    )
                    if match is None:
                        unmatched_rows += 1
                        continue

                    timed_html_rows += 1
                    race_id = int(match.group(1))
                    key = (horse_id, race_id)
                    if key not in target_keys:
                        unmatched_rows += 1
                        continue

                    matched_rows += 1
                    rank_counts[rank] += 1
                    if not dry_run:
                        pending_updates.append((rank, horse_id, race_id))

            except (OSError, ValueError, UnicodeDecodeError) as error:
                failed_horses += 1
                print(f'Warning: failed to parse horse_id={horse_id}: {error}')

            if not dry_run and processed_horses % BATCH_SIZE == 0:
                cursor = target_conn.executemany(update_sql, pending_updates)
                updated_rows += cursor.rowcount
                pending_updates.clear()
                target_conn.commit()
                print(
                    f'Progress: {processed_horses}/{total_horses} horses, '
                    f'{updated_rows} rows updated'
                )

        if not dry_run and pending_updates:
            cursor = target_conn.executemany(update_sql, pending_updates)
            updated_rows += cursor.rowcount
            target_conn.commit()

        mode = 'Dry run' if dry_run else 'Migration complete'
        print(f'{mode}: {processed_horses}/{total_horses} horses processed')
        print(f'Timed HTML rows: {timed_html_rows}')
        print(f'Matched horse_id/race_id rows: {matched_rows}')
        print(f'Updated last_3f_rank rows: {updated_rows}')
        print(f'Unmatched rows skipped: {unmatched_rows}')
        print(f'HTML parse failures: {failed_horses}')
        print(f'Ranks (1/2/3/4+): {rank_counts}')
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Count matching rows without updating horse_data_dtl',
    )
    arguments = parser.parse_args()
    migrate_last_3f_rank(dry_run=arguments.dry_run)
