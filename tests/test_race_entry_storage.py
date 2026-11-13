import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask_app import app
from migrate_race_entry_db import migrate
from race_entry_storage import create_race_entry_tables
from race_page_parser import parse_race_page


SHUTUBA_HTML = """
<html><title>Test race</title><body>
<table class="Shutuba_Table"><tbody><tr class="HorseList">
<td class="Waku1 Txt_C">1</td><td class="Umaban1 Txt_C">2</td>
<td class="CheckMark">--</td>
<td class="HorseInfo"><a href="/horse/2024100001/">テスト馬</a></td>
<td class="Barei Txt_C">牡3</td><td class="Txt_C">56.0</td>
<td class="Jockey"><a href="/jockey/00001/">騎手名</a></td>
</tr></tbody></table>
</body></html>
"""

RESULT_HTML = """
<html><title>Test result</title><body>
<table class="race_table_01"><tbody><tr>
<td class="txt_r">2</td><td class="w4ml">1</td><td class="txt_r">2</td>
<td class="txt_l"><a href="/horse/2024100001/">テスト馬</a></td>
<td class="txt_c">牡3</td><td class="txt_c">56</td>
<td class="txt_l">騎手名</td>
</tr></tbody></table>
</body></html>
"""


class RaceEntryStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "analysis.db"
        self.connection = sqlite3.connect(
            self.database_path, isolation_level=None
        )
        self.connection.execute("PRAGMA foreign_keys = ON")
        create_race_entry_tables(self.connection)
        self.client = app.test_client()
        self.race = {
            "race_id": "202611010101",
            "race_date": "2026/11/01",
            "course": "東京",
            "surface": "芝",
            "distance": 1600,
            "race_class": "3",
            "declared_field_size": 1,
            "race_name": "テストレース",
        }

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def _post(self, page_type="shutuba", html=SHUTUBA_HTML, **extra):
        payload = {
            "race": self.race,
            "page_type": page_type,
            "fetched_at": "2026-11-06T00:00:00+00:00",
            "source_url": "https://example.test/race",
            "html": html,
        }
        payload.update(extra)
        with patch("flask_app.get_analysis_connection") as get_connection:
            get_connection.return_value = sqlite3.connect(
                self.database_path, isolation_level=None
            )
            response = self.client.post("/save_race", json=payload)
        return response

    def test_api_saves_race_entries_and_snapshot(self):
        response = self._post()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["entry_count"], 1)

        race = self.connection.execute(
            "SELECT race_id, declared_field_size FROM race_master"
        ).fetchone()
        entry = self.connection.execute(
            """
            SELECT horse_number, horse_id, horse_name, gate, jockey,
                   carried_weight, finish_position
            FROM race_entry
            """
        ).fetchone()
        snapshot = self.connection.execute(
            """
            SELECT page_type, source_url, html_body, entries_json
            FROM race_entry_snapshot
            """
        ).fetchone()
        self.assertEqual(race, ("202611010101", 1))
        self.assertEqual(
            entry,
            (2, "2024100001", "テスト馬", 1, "騎手名", 56.0, None),
        )
        self.assertEqual(snapshot[0:3], (
            "shutuba",
            "https://example.test/race",
            SHUTUBA_HTML,
        ))
        self.assertEqual(json.loads(snapshot[3])[0]["horse_id"], "2024100001")

    def test_result_pages_store_only_numeric_finish_and_keep_each_snapshot(self):
        first = self._post(
            page_type="result",
            html=RESULT_HTML,
            snapshot_id="retryable-snapshot",
        )
        retry = self._post(
            page_type="result",
            html=RESULT_HTML,
            snapshot_id="retryable-snapshot",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(
            self.connection.execute(
                "SELECT finish_position FROM race_entry"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM race_entry_snapshot"
            ).fetchone()[0],
            1,
        )

        nonnumeric = RESULT_HTML.replace(">2</td>", ">中</td>", 1)
        response = self._post(page_type="result", html=nonnumeric)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.connection.execute(
                "SELECT finish_position FROM race_entry"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM race_entry_snapshot"
            ).fetchone()[0],
            2,
        )

    def test_null_values_do_not_replace_existing_entry_data(self):
        response = self._post(page_type="result", html=RESULT_HTML)
        self.assertEqual(response.status_code, 200)

        sparse_html = """
        <table class="Shutuba_Table"><tr class="HorseList">
        <td>1</td><td>2</td><td>--</td><td>テスト馬</td>
        </tr></table>
        """
        response = self._post(
            page_type="shutuba",
            html=sparse_html,
            race={"race_id": self.race["race_id"]},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            self.connection.execute(
                """
                SELECT horse_id, horse_name, gate, jockey, carried_weight,
                       finish_position
                FROM race_entry
                """
            ).fetchone(),
            ("2024100001", "テスト馬", 1, "騎手名", 56.0, 2),
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT race_name, declared_field_size FROM race_master"
            ).fetchone(),
            ("テストレース", 1),
        )

    def test_parser_keeps_horse_without_profile_link_and_rejects_bad_rows(self):
        html = SHUTUBA_HTML.replace(
            '<a href="/horse/2024100001/">テスト馬</a>', "テスト馬"
        )
        parsed = parse_race_page(html, "shutuba")
        self.assertEqual(parsed["entries"][0]["horse_id"], None)
        self.assertEqual(parsed["entries"][0]["horse_name"], "テスト馬")

        response = self._post(page_type="other")
        self.assertEqual(response.status_code, 400)

    def test_migration_backs_up_before_adding_only_new_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "existing.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO legacy VALUES (1)")
            connection.commit()
            connection.close()

            backup = migrate(database)

            self.assertTrue(backup.is_file())
            backup_connection = sqlite3.connect(backup)
            try:
                self.assertEqual(
                    backup_connection.execute(
                        "SELECT COUNT(*) FROM legacy"
                    ).fetchone()[0],
                    1,
                )
                self.assertIsNone(
                    backup_connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'table' AND name = 'race_master'
                        """
                    ).fetchone()
                )
            finally:
                backup_connection.close()
            migrated_connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    migrated_connection.execute(
                        "SELECT COUNT(*) FROM legacy"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    {
                        row[0]
                        for row in migrated_connection.execute(
                            """
                            SELECT name FROM sqlite_master
                            WHERE type = 'table'
                            """
                        )
                    },
                    {"legacy", "race_master", "race_entry", "race_entry_snapshot"},
                )
            finally:
                migrated_connection.close()


if __name__ == "__main__":
    unittest.main()
