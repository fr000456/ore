import sqlite3
import zlib
import datetime

DB_PATH = "horse_html.db"

def migrate_html_to_compressed():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 既存データを全取得
    cur.execute("SELECT horse_id, html FROM horse_html")
    rows = cur.fetchall()

    print(f"📦 {len(rows)} 件のHTMLを圧縮して保存します...")

    updated_count = 0
    for row in rows:
        horse_id = row["horse_id"]
        html_data = row["html"]

        # すでにbytesならスキップ（多重圧縮防止）
        if isinstance(html_data, bytes):
            print(f"⏩ {horse_id} は既に圧縮済み、スキップ")
            continue

        # 圧縮
        compressed_html = zlib.compress(html_data.encode("utf-8"))

        # 保存
        cur.execute(
            "UPDATE horse_html SET html = ?, saved_at = ? WHERE horse_id = ?",
            (compressed_html, datetime.datetime.now(datetime.UTC).isoformat(), horse_id)
        )
        updated_count += 1

    conn.commit()
    conn.close()
    print(f"✅ 圧縮完了: {updated_count} 件更新しました")

if __name__ == "__main__":
    migrate_html_to_compressed()