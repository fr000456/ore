import re


RACE_RANK = (
    ('新馬', 0),
    ('未勝利', 1),
    ('1勝', 2),
    ('500万', 2),
    ('2勝', 3),
    ('1000万', 3),
    ('3勝', 4),
    ('1600万', 4),
    ('OP', 5),
    ('L', 6),
    ('GIII', 7),
    ('GII', 8),
    ('GI', 9),
)

PARENTHESIS_PATTERN = re.compile(r'[（(]([^）)]*)[）)]')
LAST_3F_PATTERN = re.compile(r'\d+(?:\.\d+)?')
RANK_CLASS_PATTERN = re.compile(r'rank_([123])')


def get_race_rank(race_name):
    """Return the rank defined by const.js, or None when the title is unknown."""
    if not race_name:
        return None

    for label, rank in RACE_RANK[:2]:
        if label in race_name:
            return rank

    parenthesized_text = ' '.join(PARENTHESIS_PATTERN.findall(race_name))
    for label, rank in RACE_RANK[2:]:
        if label in parenthesized_text:
            return rank

    for label, rank in RACE_RANK[2:8]:
        if label in race_name:
            return rank

    return None


def get_last_3f_rank(cell):
    """Return rank 1-3 from CSS, or 4 for a timed runner outside the top three."""
    last_3f = cell.get_text(strip=True)
    if not LAST_3F_PATTERN.fullmatch(last_3f):
        return None

    for class_name in cell.get('class', []):
        match = RANK_CLASS_PATTERN.fullmatch(class_name)
        if match:
            return int(match.group(1))

    return 4


def get_last_3f_column_index(race_table):
    """Locate the last-3F column using the table header."""
    header_row = race_table.find('tr')
    if header_row is None:
        return None

    for index, cell in enumerate(header_row.find_all(['th', 'td'])):
        if '上り' in cell.get_text(' ', strip=True):
            return index
    return None
