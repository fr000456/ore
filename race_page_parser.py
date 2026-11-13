"""Parsers for race-entry information in netkeiba shutuba and result pages."""

import re

from bs4 import BeautifulSoup


HORSE_ID_PATTERN = re.compile(r"/horse/([A-Za-z0-9-]+)")
INTEGER_PATTERN = re.compile(r"^\d+$")
DECIMAL_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")


def _text(element):
    return element.get_text(" ", strip=True) if element else ""


def _integer(value):
    value = value.strip()
    return int(value) if INTEGER_PATTERN.fullmatch(value) else None


def _weight(value):
    value = value.strip()
    return float(value) if DECIMAL_PATTERN.fullmatch(value) else None


def _horse_link(row):
    for link in row.select("a[href]"):
        match = HORSE_ID_PATTERN.search(link.get("href", ""))
        if match:
            return link, match.group(1)
    return None, None


def _shutuba_entries(soup):
    table = soup.select_one("table.Shutuba_Table")
    if table is None:
        raise ValueError("shutuba table table.Shutuba_Table was not found")

    entries = []
    rows = table.select("tr.HorseList")
    if not rows:
        rows = [r for r in table.select("tr") if _horse_link(r)[0] is not None]

    for row in rows:
        horse_link, horse_id = _horse_link(row)

        # 1. 馬番の取得: class*="Umaban" を優先、なければセル走査で判定
        umaban_cell = row.select_one('td[class*="Umaban"]')
        horse_number = _integer(_text(umaban_cell)) if umaban_cell else None

        # 2. 枠番の取得: class*="Waku" を優先
        waku_cell = row.select_one('td[class*="Waku"]')
        gate = _integer(_text(waku_cell)) if waku_cell else None

        # フォールバック: セルから数値を順に探索
        cells = row.find_all(["td", "th"], recursive=False)
        if horse_number is None and len(cells) >= 2:
            num_cells = []
            for c in cells:
                val = _integer(_text(c))
                if val is not None and 1 <= val <= 30:
                    num_cells.append(val)
            if len(num_cells) == 1:
                horse_number = num_cells[0]
            elif len(num_cells) >= 2:
                if gate is None:
                    gate = num_cells[0]
                horse_number = num_cells[1]

        if horse_number is None:
            continue

        # 馬名の取得
        horse_name = _text(horse_link)
        if not horse_name:
            name_cell = row.select_one(".HorseName, .HorseInfo")
            horse_name = _text(name_cell) or (_text(cells[3]) if len(cells) > 3 else "")
        if not horse_name:
            continue

        jockey_cell = row.select_one("td.Jockey")
        weight_cell = row.select_one("td.Barei + td")
        if not weight_cell:
            weight_cell = row.select_one('td[class*="Weight"]')

        entries.append({
            "horse_number": horse_number,
            "horse_id": horse_id,
            "horse_name": horse_name,
            "gate": gate,
            "jockey": _text(jockey_cell) or None,
            "carried_weight": _weight(_text(weight_cell)) if weight_cell else None,
            "finish_position": None,
        })

    return table, entries


def _margin(value):
    if not value:
        return None
    v = value.strip().replace("-", "")
    try:
        return float(v)
    except ValueError:
        return None


def _horse_weight(value):
    if not value:
        return None
    m = re.match(r"^(\d+)", value.strip())
    return int(m.group(1)) if m else None


def _extract_track_condition(soup):
    intro = soup.select_one(".data_intro")
    if intro:
        text = _text(intro)
        m = re.search(r"(芝|ダ|障)[^0-9]*?:\s*(良|稍重|稍|重|不良|不)", text)
        if m:
            cond = m.group(2)
            return "稍" if cond == "稍重" else ("不" if cond == "不良" else cond)
    return None


def _result_entries(soup):
    table = soup.select_one("table.race_table_01")
    if table is None:
        raise ValueError("result table table.race_table_01 was not found")

    track_cond = _extract_track_condition(soup)

    entries = []
    for row in table.select("tr"):
        horse_link, horse_id = _horse_link(row)
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 4:
            continue
        horse_number = _integer(_text(cells[2]))
        if horse_number is None:
            continue
        horse_name = _text(horse_link) or _text(cells[3])
        if not horse_name:
            continue
        weight_value = _text(cells[5]) if len(cells) > 5 else ""
        jockey_value = _text(cells[6]) if len(cells) > 6 else ""

        finish_time = _text(cells[7]) if len(cells) > 7 else None
        margin_val = _margin(_text(cells[8])) if len(cells) > 8 else None
        passing_order = _text(cells[10]) if len(cells) > 10 else None

        last_3f_cell = cells[11] if len(cells) > 11 else None
        last_3f = _weight(_text(last_3f_cell)) if last_3f_cell else None
        last_3f_rank = None
        if last_3f_cell:
            try:
                from race_metadata import get_last_3f_rank
                last_3f_rank = get_last_3f_rank(last_3f_cell)
            except Exception:
                pass

        popularity = _integer(_text(cells[13])) if len(cells) > 13 else None
        horse_weight = _horse_weight(_text(cells[14])) if len(cells) > 14 else None

        entries.append({
            "horse_number": horse_number,
            "horse_id": horse_id,
            "horse_name": horse_name,
            "gate": _integer(_text(cells[1])),
            "jockey": jockey_value or None,
            "carried_weight": _weight(weight_value),
            "finish_position": _integer(_text(cells[0])),
            "finish_time": finish_time or None,
            "margin": margin_val,
            "passing_order": passing_order or None,
            "last_3f": last_3f,
            "last_3f_rank": last_3f_rank,
            "popularity": popularity,
            "horse_weight": horse_weight,
            "track_condition": track_cond,
        })

    return table, entries


def parse_race_page(html, page_type):
    """Parse horse rows from a page; status text is retained only in the HTML."""
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html must be a non-empty string")
    soup = BeautifulSoup(html, "html.parser")
    if page_type == "shutuba":
        table, entries = _shutuba_entries(soup)
    elif page_type == "result":
        table, entries = _result_entries(soup)
    else:
        raise ValueError("page_type must be 'shutuba' or 'result'")

    if not entries:
        raise ValueError(f"{page_type} page contained no horse rows")
    if any(entry["horse_number"] is None for entry in entries):
        raise ValueError(f"{page_type} page contained a row without a horse number")
    horse_numbers = [entry["horse_number"] for entry in entries]
    if len(horse_numbers) != len(set(horse_numbers)):
        raise ValueError(f"{page_type} page contained duplicate horse numbers")

    return {
        "entries": entries,
        "page_title": _text(soup.title),
        "table_class": table.get("class", []),
    }
