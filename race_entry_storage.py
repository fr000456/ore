"""Persistence helpers for additive race-level collection tables."""

import datetime
import json
import math
import re
import sqlite3
import uuid

from race_page_parser import parse_race_page


RACE_ID_PATTERN = re.compile(r"^\d{12}$")
PAGE_TYPES = {"shutuba", "result"}

CREATE_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS race_master (
        race_id TEXT PRIMARY KEY NOT NULL,
        race_date TEXT,
        course TEXT,
        surface TEXT,
        distance INTEGER,
        race_class TEXT,
        declared_field_size INTEGER,
        race_name TEXT,
        race_status TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS race_entry (
        race_id TEXT NOT NULL,
        horse_number INTEGER NOT NULL,
        horse_id TEXT,
        horse_name TEXT,
        gate INTEGER,
        jockey TEXT,
        carried_weight REAL,
        finish_position INTEGER,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        PRIMARY KEY (race_id, horse_number),
        FOREIGN KEY (race_id) REFERENCES race_master(race_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS race_entry_snapshot (
        snapshot_id TEXT PRIMARY KEY NOT NULL,
        race_id TEXT NOT NULL,
        page_type TEXT NOT NULL CHECK (page_type IN ('shutuba', 'result')),
        fetched_at TEXT NOT NULL,
        source_url TEXT NOT NULL,
        html_body TEXT NOT NULL,
        entries_json TEXT NOT NULL,
        FOREIGN KEY (race_id) REFERENCES race_master(race_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_race_entry_horse_id
    ON race_entry(horse_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_race_entry_snapshot_race_fetched
    ON race_entry_snapshot(race_id, fetched_at)
    """,
)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_race_entry_tables(connection):
    """Create only the new race collection tables and indexes."""
    for statement in CREATE_TABLE_STATEMENTS:
        connection.execute(statement)


def _optional_text(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    value = value.strip()
    return value or None


def _optional_integer(value, field, minimum=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer or null")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _normalize_race(race, entry_count):
    if not isinstance(race, dict):
        raise ValueError("race must be an object")
    race_id = race.get("race_id")
    if not isinstance(race_id, str) or not RACE_ID_PATTERN.fullmatch(race_id):
        raise ValueError("race.race_id must be a 12-digit string")

    normalized = {"race_id": race_id}
    for field in ("race_date", "course", "surface", "race_name", "race_status", "track_condition"):
        normalized[field] = _optional_text(race.get(field), f"race.{field}")
    race_class = race.get("race_class")
    if isinstance(race_class, int) and not isinstance(race_class, bool):
        race_class = str(race_class)
    normalized["race_class"] = _optional_text(race_class, "race.race_class")
    normalized["distance"] = _optional_integer(
        race.get("distance"), "race.distance", minimum=1
    )
    field_size = _optional_integer(
        race.get("declared_field_size"), "race.declared_field_size", minimum=1
    )
    normalized["declared_field_size"] = (
        entry_count if field_size is None else field_size
    )
    return normalized


def _normalize_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError("each entry must be an object")
    horse_number = _optional_integer(
        entry.get("horse_number"), "entry.horse_number", minimum=1
    )
    if horse_number is None:
        raise ValueError("entry.horse_number is required")
    horse_id = _optional_text(entry.get("horse_id"), "entry.horse_id")
    finish_position = _optional_integer(
        entry.get("finish_position"), "entry.finish_position", minimum=1
    )
    weight = entry.get("carried_weight")
    if weight is not None:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("entry.carried_weight must be numeric or null")
        weight = float(weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(
                "entry.carried_weight must be finite and greater than zero"
            )
    res = {
        "horse_number": horse_number,
        "horse_id": horse_id,
        "horse_name": _optional_text(entry.get("horse_name"), "entry.horse_name"),
        "gate": _optional_integer(entry.get("gate"), "entry.gate", minimum=1),
        "jockey": _optional_text(entry.get("jockey"), "entry.jockey"),
        "carried_weight": weight,
        "finish_position": finish_position,
    }
    for key in (
        "finish_time", "passing_order", "track_condition", "margin",
        "last_3f", "last_3f_rank", "popularity", "horse_weight", "pace"
    ):
        if key in entry:
            res[key] = entry[key]
    return res


def save_race_page(
    connection,
    *,
    race,
    page_type,
    fetched_at,
    source_url,
    html,
    snapshot_id=None,
):
    """Atomically upsert race and entry data and append its source snapshot."""
    if not isinstance(page_type, str) or page_type not in PAGE_TYPES:
        raise ValueError("page_type must be 'shutuba' or 'result'")
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url must be a non-empty string")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html must be a non-empty string")
    if len(html.encode("utf-8")) > 10 * 1024 * 1024:
        raise ValueError("html exceeds the 10 MiB limit")
    if fetched_at is None:
        fetched_at = utc_now()
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        raise ValueError("fetched_at must be a non-empty string")
    if snapshot_id is None:
        snapshot_id = str(uuid.uuid4())
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("snapshot_id must be a non-empty string")

    parsed = parse_race_page(html, page_type)
    entries = [_normalize_entry(entry) for entry in parsed["entries"]]
    race_values = _normalize_race(race, len(entries))
    race_id = race_values["race_id"]
    serialized_entries = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    now = utc_now()

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO race_master (
                race_id, race_date, course, surface, distance, race_class,
                declared_field_size, race_name, race_status, first_seen_at,
                last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(race_id) DO UPDATE SET
                race_date = COALESCE(excluded.race_date, race_master.race_date),
                course = COALESCE(excluded.course, race_master.course),
                surface = COALESCE(excluded.surface, race_master.surface),
                distance = COALESCE(excluded.distance, race_master.distance),
                race_class = COALESCE(excluded.race_class, race_master.race_class),
                declared_field_size = COALESCE(
                    excluded.declared_field_size, race_master.declared_field_size
                ),
                race_name = COALESCE(excluded.race_name, race_master.race_name),
                race_status = COALESCE(excluded.race_status, race_master.race_status),
                last_seen_at = excluded.last_seen_at
            """,
            (
                race_id,
                race_values["race_date"],
                race_values["course"],
                race_values["surface"],
                race_values["distance"],
                race_values["race_class"],
                race_values["declared_field_size"],
                race_values["race_name"],
                race_values["race_status"],
                now,
                now,
            ),
        )

        for entry in entries:
            connection.execute(
                """
                INSERT INTO race_entry (
                    race_id, horse_number, horse_id, horse_name, gate, jockey,
                    carried_weight, finish_position, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(race_id, horse_number) DO UPDATE SET
                    horse_id = COALESCE(excluded.horse_id, race_entry.horse_id),
                    horse_name = COALESCE(excluded.horse_name, race_entry.horse_name),
                    gate = COALESCE(excluded.gate, race_entry.gate),
                    jockey = COALESCE(excluded.jockey, race_entry.jockey),
                    carried_weight = COALESCE(
                        excluded.carried_weight, race_entry.carried_weight
                    ),
                    finish_position = COALESCE(
                        excluded.finish_position, race_entry.finish_position
                    ),
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    race_id,
                    entry["horse_number"],
                    entry["horse_id"],
                    entry["horse_name"],
                    entry["gate"],
                    entry["jockey"],
                    entry["carried_weight"],
                    entry["finish_position"],
                    now,
                    now,
                ),
            )

        connection.execute(
            """
            INSERT INTO race_entry_snapshot (
                snapshot_id, race_id, page_type, fetched_at, source_url,
                html_body, entries_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_id) DO NOTHING
            """,
            (
                snapshot_id,
                race_id,
                page_type,
                fetched_at,
                source_url.strip(),
                html,
                serialized_entries,
            ),
        )

        # page_type == 'result' の場合、各出走馬の horse_data_dtl に今回のレース結果を追加・更新
        if page_type == "result":
            has_dtl = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='horse_data_dtl'"
            ).fetchone() is not None
            if has_dtl:
                for entry in entries:
                    if not entry.get("horse_id"):
                        continue
                    # 外部キー制約 (horse_data_hd) を満たすために登録（存在しない場合のみ）
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO horse_data_hd (horse_id, horse_name)
                        VALUES (?, ?)
                        """,
                        (entry["horse_id"], entry.get("horse_name")),
                    )

                    # horse_data_dtl に確定結果を保存
                    dtl_values = (
                        entry["horse_id"],
                        race_values["race_date"],
                        race_values["course"],
                        int(race_id) if str(race_id).isdigit() else race_id,
                        race_values["declared_field_size"],
                        entry.get("gate"),
                        entry.get("horse_number"),
                        entry.get("popularity"),
                        entry.get("finish_position"),
                        entry.get("jockey"),
                        entry.get("carried_weight"),
                        race_values.get("surface"),
                        race_values.get("distance"),
                        entry.get("track_condition") or race_values.get("track_condition"),
                        entry.get("finish_time"),
                        entry.get("margin"),
                        entry.get("passing_order"),
                        entry.get("pace"),
                        entry.get("last_3f"),
                        entry.get("horse_weight"),
                        race_values.get("race_class"),
                        entry.get("last_3f_rank"),
                    )
                    connection.execute(
                        """
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
                            popularity = COALESCE(excluded.popularity, horse_data_dtl.popularity),
                            finish_position = COALESCE(excluded.finish_position, horse_data_dtl.finish_position),
                            jockey = excluded.jockey,
                            carried_weight = excluded.carried_weight,
                            surface = excluded.surface,
                            distance = excluded.distance,
                            track_condition = COALESCE(excluded.track_condition, horse_data_dtl.track_condition),
                            finish_time = COALESCE(excluded.finish_time, horse_data_dtl.finish_time),
                            margin = COALESCE(excluded.margin, horse_data_dtl.margin),
                            passing_order = COALESCE(excluded.passing_order, horse_data_dtl.passing_order),
                            pace = COALESCE(excluded.pace, horse_data_dtl.pace),
                            last_3f = COALESCE(excluded.last_3f, horse_data_dtl.last_3f),
                            horse_weight = COALESCE(excluded.horse_weight, horse_data_dtl.horse_weight),
                            race_class = COALESCE(excluded.race_class, horse_data_dtl.race_class),
                            last_3f_rank = COALESCE(excluded.last_3f_rank, horse_data_dtl.last_3f_rank)
                        """,
                        dtl_values,
                    )

        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise

    return {
        "race_id": race_id,
        "entry_count": len(entries),
        "snapshot_id": snapshot_id,
        "page_type": page_type,
        "page_title": parsed["page_title"],
    }
