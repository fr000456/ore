"""Back up horse_analysis.db, then add the race-entry tables."""

import argparse
import datetime
from pathlib import Path
import sqlite3

from race_entry_storage import create_race_entry_tables


def migrate(database_path):
    database_path = Path(database_path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"database does not exist: {database_path}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = database_path.with_name(
        f"{database_path.name}.before_race_entry_{timestamp}.bak"
    )
    if backup_path.exists():
        raise FileExistsError(f"backup already exists: {backup_path}")
    source = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
        finally:
            backup.close()
    except Exception:
        if backup_path.exists():
            backup_path.unlink()
        raise
    finally:
        source.close()

    connection = sqlite3.connect(database_path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        create_race_entry_tables(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return backup_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default="horse_analysis.db",
        help="analysis database path (default: horse_analysis.db)",
    )
    args = parser.parse_args()
    backup_path = migrate(args.database)
    print(f"Race-entry tables created. Backup: {backup_path}")


if __name__ == "__main__":
    main()
