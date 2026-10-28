import argparse
import base64
import gzip
import re
import sqlite3
from collections import Counter

from bs4 import BeautifulSoup
from race_metadata import get_race_rank


SOURCE_DB = 'horse_html.db'
TARGET_DB = 'horse_analysis.db'
BATCH_SIZE = 100

RACE_ID_PATTERN = re.compile(r'/race/(\d+)')


def migrate_race_class(dry_run=False):
    source_conn = sqlite3.connect(SOURCE_DB, timeout=30)
    target_conn = sqlite3.connect(TARGET_DB, timeout=30)

    try:
        target_columns = {
            row[1] for row in target_conn.execute('PRAGMA table_info(horse_data_dtl)')
        }
        if 'race_class' not in target_columns:
            raise RuntimeError(
                'horse_data_dtl.race_class is missing; add the column before migration'
            )

        total_horses = source_conn.execute(
            'SELECT COUNT(*) FROM horse_html'
        ).fetchone()[0]
        source_rows = source_conn.execute(
            'SELECT horse_id, html FROM horse_html ORDER BY horse_id'
        )

        processed_horses = 0
        classified_html_rows = 0
        matched_rows = 0
        updated_rows = 0
        unmatched_rows = 0
        unclassified_rows = 0
        failed_horses = 0
        class_counts = Counter()
        unclassified_titles = Counter()

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
                    if len(cells) <= 4:
                        continue

                    race_name = cells[4].get_text(' ', strip=True)
                    race_rank = get_race_rank(race_name)
                    if race_rank is None:
                        unclassified_rows += 1
                        unclassified_titles[race_name] += 1
                        continue

                    race_link = cells[4].find('a')
                    match = RACE_ID_PATTERN.search(
                        race_link.get('href', '') if race_link else ''
                    )
                    if match is None:
                        unmatched_rows += 1
                        continue

                    classified_html_rows += 1
                    race_id = int(match.group(1))
                    existing = target_conn.execute(
                        '''
                        SELECT race_class
                        FROM horse_data_dtl
                        WHERE horse_id = ? AND race_id = ?
                        ''',
                        (horse_id, race_id),
                    ).fetchone()
                    if existing is None:
                        unmatched_rows += 1
                        continue

                    matched_rows += 1
                    class_counts[race_rank] += 1
                    if not dry_run and existing[0] is None:
                        cursor = target_conn.execute(
                            '''
                            UPDATE horse_data_dtl
                            SET race_class = ?
                            WHERE horse_id = ? AND race_id = ? AND race_class IS NULL
                            ''',
                            (race_rank, horse_id, race_id),
                        )
                        updated_rows += cursor.rowcount

            except (OSError, ValueError, UnicodeDecodeError) as error:
                failed_horses += 1
                print(f'Warning: failed to parse horse_id={horse_id}: {error}')

            if not dry_run and processed_horses % BATCH_SIZE == 0:
                target_conn.commit()
                print(
                    f'Progress: {processed_horses}/{total_horses} horses, '
                    f'{updated_rows} rows updated'
                )

        if not dry_run:
            target_conn.commit()

        mode = 'Dry run' if dry_run else 'Migration complete'
        print(f'{mode}: {processed_horses}/{total_horses} horses processed')
        print(f'Classified HTML rows: {classified_html_rows}')
        print(f'Matched horse_id/race_id rows: {matched_rows}')
        print(f'Updated race_class rows: {updated_rows}')
        print(f'Unmatched rows skipped: {unmatched_rows}')
        print(f'Unclassified race titles skipped: {unclassified_rows}')
        print(f'HTML parse failures: {failed_horses}')
        print(f'Rows by race rank: {dict(sorted(class_counts.items()))}')
        if unclassified_titles:
            print(f'Unclassified title examples: {unclassified_titles.most_common(10)}')
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
    migrate_race_class(dry_run=arguments.dry_run)
