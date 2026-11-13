import math
import re
import sqlite3
from bisect import bisect_left
from datetime import datetime
from collections import defaultdict
from functools import lru_cache

DB_PATH = 'horse_analysis.db'
PROMOTION_SECOND_ODDS_MULTIPLIER = 1.15
PROMOTION_SECOND_CONTEXT_SHRINKAGE = 0.5
RECENT_PERFORMANCE_MARGIN_WEIGHT = 0.24
RECENT_PERFORMANCE_CLASS_WEIGHT = 0.86
UNWON_MAIDEN_CLASS_CHALLENGE_PROBABILITY_FACTOR = 0.35
PROMOTION_SECOND_CONTEXT_FEATURES = (
    'promotion_2nd_prev_finish',
    'promotion_2nd_prev_margin',
    'promotion_2nd_prev_course_match',
    'promotion_2nd_prev_abs_distance_diff',
    'promotion_2nd_prev_last_3f_rank',
    'promotion_2nd_prev_to_prev_interval',
    'promotion_2nd_prev_to_target_interval',
    'target_course_experience_count',
    'top3_rate_target_course',
    'target_distance_surface_experience_count',
    'top3_rate_target_distance_surface',
    'is_tataki_2nd',
    'promotion_2nd_prev_good_result',
    'promotion_2nd_good_target_course_record',
    'promotion_2nd_good_target_distance_record',
    'promotion_2nd_good_result_after_layoff',
)
PROMOTION_SECOND_RESULT_FEATURES_TO_RECALCULATE = (
    'last_finish',
    'recent_3_avg_finish',
    'recent_3_top3_rate',
    'recent_3_avg_finish_turf',
    'recent_3_top3_rate_turf',
    'recent_3_avg_finish_dirt',
    'recent_3_top3_rate_dirt',
    'recent_5_avg_finish',
    'recent_5_top3_rate',
    'recent_5_avg_finish_turf',
    'recent_5_top3_rate_turf',
    'recent_5_avg_finish_dirt',
    'recent_5_top3_rate_dirt',
    'overall_avg_finish',
    'overall_top3_rate',
    'overall_avg_finish_turf',
    'overall_top3_rate_turf',
    'overall_avg_finish_dirt',
    'overall_top3_rate_dirt',
    'top3_rate_target_distance',
    'top3_rate_target_distance_surface',
    'top3_rate_target_course',
    'top3_rate_target_surface',
    'top3_rate_target_condition',
    'top3_rate_target_class',
    'target_surface_recent_6_race_count',
    'target_surface_recent_6_assessable_count',
    'target_surface_recent_6_good_count',
    'target_surface_recent_6_good_rate',
    'target_surface_recent_6_has_good',
    'prev_course_change_score',
    'avg_last_3f',
    'recent_1_avg_finish_target_surface',
    'recent_1_avg_margin_target_surface',
    'recent_1_avg_class_delta_target_surface',
    'recent_1_class_margin_finish',
    'recent_3_avg_finish_target_surface',
    'recent_3_avg_margin_target_surface',
    'recent_3_avg_class_delta_target_surface',
    'recent_3_class_margin_finish',
    'recent_5_avg_finish_target_surface',
    'recent_5_avg_margin_target_surface',
    'recent_5_avg_class_delta_target_surface',
    'recent_5_class_margin_finish',
    'is_unwon_maiden_class_challenge',
)
COURSE_GATE_BIAS_PRIOR_STARTERS = 100
HORSE_GATE_PREFERENCE_PRIOR_STARTS = 5
GATE_POSITION_GROUPS = ('inside', 'middle', 'outside')

SURFACE_FILTERED_FINISH_FEATURES = {
    'last_finish',
    'recent_3_avg_finish',
    'recent_3_top3_rate',
    'recent_3_avg_finish_turf',
    'recent_3_top3_rate_turf',
    'recent_3_avg_finish_dirt',
    'recent_3_top3_rate_dirt',
    'recent_5_avg_finish',
    'recent_5_top3_rate',
    'recent_5_avg_finish_turf',
    'recent_5_top3_rate_turf',
    'recent_5_avg_finish_dirt',
    'recent_5_top3_rate_dirt',
}
NULL_AS_NAN_FEATURES = SURFACE_FILTERED_FINISH_FEATURES | {
    'prev_last_3f_rank',
    'target_race_class',
    'prev_race_class',
    'race_class_change',
    'is_class_up',
    'is_class_down',
    'target_gate',
    'target_field_size',
    'target_gate_position',
    'top3_rate_target_condition',
    'top3_rate_target_distance_surface',
    'top3_rate_target_class',
    'is_promotion_2nd',
    'is_shortening_2nd',
    'target_surface_recent_6_good_rate',
    'target_surface_recent_6_has_good',
    'promotion_2nd_prev_course_match',
    'promotion_2nd_prev_distance_diff',
    'promotion_2nd_prev_finish',
    'promotion_2nd_prev_margin',
    'promotion_2nd_prev_last_3f_rank',
    'promotion_2nd_prev_to_prev_interval',
    'promotion_2nd_prev_to_target_interval',
    'target_gate_group',
    'course_gate_group_top3_rate',
    'course_gate_group_expected_rate',
    'course_gate_group_advantage',
    'horse_gate_group_top3_rate',
    'horse_gate_group_advantage',
}


def parse_race_class(value):
    if value is None:
        return None
    try:
        race_class = int(value)
    except (TypeError, ValueError):
        return None
    return race_class if 0 <= race_class <= 9 else None


def is_unwon_maiden_class_challenge(race_history, target_race_class):
    """Identify a first one-win-class start after maiden starts without a win."""
    if parse_race_class(target_race_class) != 2:
        return False

    maiden_starts = [
        race for race in race_history
        if parse_race_class(race.get('race_class')) == 1
    ]
    if not maiden_starts:
        return False

    has_maiden_win = any(race.get('finish_position') == 1 for race in maiden_starts)
    has_one_win_class_start = any(
        parse_race_class(race.get('race_class')) == 2
        for race in race_history
    )
    return not has_maiden_win and not has_one_win_class_start


def apply_unwon_maiden_class_challenge_penalty(probability, features):
    if features.get('is_unwon_maiden_class_challenge') != 1:
        return probability
    return probability * UNWON_MAIDEN_CLASS_CHALLENGE_PROBABILITY_FACTOR


def should_neutralize_promotion_second_previous_result(finish, margin):
    qualifies_as_not_a_heavy_loss = (
        isinstance(finish, (int, float)) and finish <= 8
    ) or (
        isinstance(margin, (int, float)) and margin <= 1.0
    )
    has_no_top_three_finish = (
        not isinstance(finish, (int, float)) or finish > 3
    )
    return qualifies_as_not_a_heavy_loss and has_no_top_three_finish


def get_promotion_second_context_values(features):
    previous_result_ignored = (
        features.get('promotion_2nd_prev_result_ignored') == 1
        or (
            features.get('is_promotion_2nd') == 1
            and should_neutralize_promotion_second_previous_result(
                features.get('promotion_2nd_prev_finish'),
                features.get('promotion_2nd_prev_margin'),
            )
        )
    )
    previous_finish = (
        None
        if previous_result_ignored
        else features.get('promotion_2nd_prev_finish')
    )
    previous_margin = (
        None
        if previous_result_ignored
        else features.get('promotion_2nd_prev_margin')
    )
    previous_interval = features.get('promotion_2nd_prev_to_prev_interval')
    course_experience = features.get('target_course_experience_count') or 0
    course_top3_rate = features.get('top3_rate_target_course')
    distance_experience = features.get('target_distance_surface_experience_count') or 0
    distance_top3_rate = features.get('top3_rate_target_distance_surface')

    previous_good_result = features.get('promotion_2nd_prev_good_result')
    if previous_good_result is None and not previous_result_ignored:
        previous_good_result = (
            int(previous_finish <= 5 and previous_margin < 1.0)
            if (
                isinstance(previous_finish, (int, float))
                and isinstance(previous_margin, (int, float))
            )
            else None
        )
    good_course_record = (
        int(course_experience > 0 and course_top3_rate >= 0.5)
        if course_top3_rate is not None
        else None
    )
    good_distance_record = (
        int(distance_experience > 0 and distance_top3_rate >= 0.5)
        if distance_top3_rate is not None
        else None
    )

    values = {
        'promotion_2nd_prev_finish': previous_finish,
        'promotion_2nd_prev_margin': previous_margin,
        'promotion_2nd_prev_course_match': features.get(
            'promotion_2nd_prev_course_match'
        ),
        'promotion_2nd_prev_abs_distance_diff': (
            abs(features['promotion_2nd_prev_distance_diff'])
            if features.get('promotion_2nd_prev_distance_diff') is not None
            else None
        ),
        'promotion_2nd_prev_last_3f_rank': (
            None
            if (
                previous_result_ignored
                and not (
                    isinstance(
                        features.get('promotion_2nd_prev_last_3f_rank'),
                        (int, float),
                    )
                    and features['promotion_2nd_prev_last_3f_rank'] <= 3
                )
            )
            else features.get('promotion_2nd_prev_last_3f_rank')
        ),
        'promotion_2nd_prev_to_prev_interval': features.get(
            'promotion_2nd_prev_to_prev_interval'
        ),
        'promotion_2nd_prev_to_target_interval': features.get(
            'promotion_2nd_prev_to_target_interval'
        ),
        'target_course_experience_count': course_experience,
        'top3_rate_target_course': course_top3_rate,
        'target_distance_surface_experience_count': distance_experience,
        'top3_rate_target_distance_surface': distance_top3_rate,
        'is_tataki_2nd': features.get('is_tataki_2nd'),
        'promotion_2nd_prev_good_result': previous_good_result,
        'promotion_2nd_good_target_course_record': good_course_record,
        'promotion_2nd_good_target_distance_record': good_distance_record,
        'promotion_2nd_good_result_after_layoff': features.get(
            'promotion_2nd_good_result_after_layoff'
        ) if previous_result_ignored else (
            int(previous_good_result == 1 and previous_interval >= 90)
            if previous_good_result is not None and previous_interval is not None
            else None
        ),
    }
    return [values[name] for name in PROMOTION_SECOND_CONTEXT_FEATURES]


def apply_promotion_second_boost(
    probability,
    is_promotion_second,
    context_probability=None,
    context_base_rate=None,
):
    probability = float(probability)
    if is_promotion_second != 1 or not 0.0 < probability < 1.0:
        return probability

    odds = probability / (1.0 - probability)
    adjusted_odds = odds * PROMOTION_SECOND_ODDS_MULTIPLIER
    if (
        context_probability is not None
        and context_base_rate is not None
        and 0.0 < context_probability < 1.0
        and 0.0 < context_base_rate < 1.0
    ):
        context_odds_ratio = (
            context_probability / (1.0 - context_probability)
        ) / (
            context_base_rate / (1.0 - context_base_rate)
        )
        context_odds_ratio = min(max(context_odds_ratio, 1.0), 2.0)
        adjusted_odds *= context_odds_ratio ** PROMOTION_SECOND_CONTEXT_SHRINKAGE
    return adjusted_odds / (1.0 + adjusted_odds)


def parse_gate(value):
    if value is None:
        return None
    try:
        gate = int(value)
    except (TypeError, ValueError):
        return None
    return gate if 1 <= gate <= 8 else None


def parse_field_size(value):
    if value is None:
        return None
    try:
        field_size = int(value)
    except (TypeError, ValueError):
        return None
    return field_size if 1 <= field_size <= 30 else None


def normalized_gate_position(gate, field_size):
    gate = parse_gate(gate)
    field_size = parse_field_size(field_size)
    if gate is None or field_size is None:
        return None

    gate_count = min(field_size, 8)
    if gate > gate_count:
        return None
    if gate_count == 1:
        return 0.0
    return (gate - 1) / (gate_count - 1)


def gate_position_group(gate, field_size):
    position = normalized_gate_position(gate, field_size)
    if position is None:
        return None
    if position <= 1 / 3:
        return 0
    if position <= 2 / 3:
        return 1
    return 2


@lru_cache(maxsize=1)
def get_course_gate_history():
    """Build daily cumulative gate outcomes by course, surface, and distance."""
    conn = get_connection()
    try:
        rows = conn.execute(
            '''
            SELECT race_date, course, surface, distance, race_id, field_size,
                   gate, finish_position
            FROM horse_data_dtl
            WHERE course IS NOT NULL AND surface IS NOT NULL
                  AND distance IS NOT NULL AND gate IS NOT NULL
            '''
        ).fetchall()
    finally:
        conn.close()

    daily = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(
                lambda: {
                    'starters': 0,
                    'top3': 0,
                    'expected_top3': 0.0,
                    'races': set(),
                }
            )
        )
    )
    for race_date, course, surface, distance, race_id, field_size, gate, finish in rows:
        parsed_date = parse_date(race_date)
        parsed_field_size = parse_field_size(field_size)
        parsed_gate = parse_gate(gate)
        if (
            parsed_date is None
            or parsed_field_size is None
            or parsed_gate is None
        ):
            continue
        group = gate_position_group(parsed_gate, parsed_field_size)
        if group is None:
            continue

        day = parsed_date.strftime('%Y/%m/%d')
        stats = daily[(course, surface, int(distance))][day][group]
        stats['starters'] += 1
        stats['top3'] += int(finish is not None and finish <= 3)
        stats['expected_top3'] += min(3, parsed_field_size) / parsed_field_size
        stats['races'].add(race_id)

    history = {}
    for condition, day_stats in daily.items():
        dates = sorted(day_stats)
        cumulative = {
            group: {
                'starters': [0],
                'top3': [0],
                'expected_top3': [0.0],
                'races': [0],
            }
            for group in range(len(GATE_POSITION_GROUPS))
        }
        for day in dates:
            for group in range(len(GATE_POSITION_GROUPS)):
                stats = day_stats[day].get(group, {})
                values = cumulative[group]
                values['starters'].append(
                    values['starters'][-1] + stats.get('starters', 0)
                )
                values['top3'].append(
                    values['top3'][-1] + stats.get('top3', 0)
                )
                values['expected_top3'].append(
                    values['expected_top3'][-1]
                    + stats.get('expected_top3', 0.0)
                )
                values['races'].append(
                    values['races'][-1] + len(stats.get('races', ()))
                )
        history[condition] = (dates, cumulative)
    return history


def get_course_gate_bias(course, surface, distance, race_date, gate, field_size):
    group = gate_position_group(gate, field_size)
    if group is None or not course or not surface or not distance or not race_date:
        return {
            'target_gate_group': group,
            'course_gate_group_starter_count': 0,
            'course_gate_group_race_count': 0,
            'course_gate_group_top3_rate': None,
            'course_gate_group_expected_rate': None,
            'course_gate_group_advantage': None,
        }

    condition_history = get_course_gate_history().get(
        (course, surface, int(distance))
    )
    if condition_history is None:
        return {
            'target_gate_group': group,
            'course_gate_group_starter_count': 0,
            'course_gate_group_race_count': 0,
            'course_gate_group_top3_rate': None,
            'course_gate_group_expected_rate': None,
            'course_gate_group_advantage': None,
        }

    dates, cumulative = condition_history
    index = bisect_left(dates, race_date)
    values = cumulative[group]
    starters = values['starters'][index]
    top3 = values['top3'][index]
    expected_top3 = values['expected_top3'][index]
    if starters == 0:
        return {
            'target_gate_group': group,
            'course_gate_group_starter_count': 0,
            'course_gate_group_race_count': 0,
            'course_gate_group_top3_rate': None,
            'course_gate_group_expected_rate': None,
            'course_gate_group_advantage': None,
        }

    observed_rate = top3 / starters
    expected_rate = expected_top3 / starters
    shrinkage = starters / (starters + COURSE_GATE_BIAS_PRIOR_STARTERS)
    return {
        'target_gate_group': group,
        'course_gate_group_starter_count': starters,
        'course_gate_group_race_count': values['races'][index],
        'course_gate_group_top3_rate': observed_rate,
        'course_gate_group_expected_rate': expected_rate,
        'course_gate_group_advantage': (
            (observed_rate - expected_rate) * shrinkage
        ),
    }


def get_horse_gate_preference(race_history, gate, field_size):
    group = gate_position_group(gate, field_size)
    valid_history = [
        race for race in race_history
        if race.get('finish_position') is not None
    ]
    overall_rate = (
        sum(race['finish_position'] <= 3 for race in valid_history)
        / len(valid_history)
        if valid_history
        else None
    )
    group_history = [
        race for race in valid_history
        if gate_position_group(race.get('gate'), race.get('field_size')) == group
    ] if group is not None else []
    group_top3 = sum(race['finish_position'] <= 3 for race in group_history)
    group_rate = (
        group_top3 / len(group_history)
        if group_history
        else None
    )
    advantage = None
    if group_history and overall_rate is not None:
        shrunk_rate = (
            group_top3 + HORSE_GATE_PREFERENCE_PRIOR_STARTS * overall_rate
        ) / (
            len(group_history) + HORSE_GATE_PREFERENCE_PRIOR_STARTS
        )
        advantage = shrunk_rate - overall_rate
    return {
        'horse_gate_group_experience_count': len(group_history),
        'horse_gate_group_top3_rate': group_rate,
        'horse_gate_group_advantage': advantage,
    }


def get_connection():
    """データベース接続"""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def parse_date(date_str):
    """日付文字列をパース"""
    normalized_date = normalize_race_date(date_str)
    if normalized_date is None:
        return None
    try:
        return datetime.strptime(normalized_date, '%Y/%m/%d')
    except ValueError:
        return None


def normalize_race_date(date_str):
    """日付文字列から有効な末尾の日付を YYYY/MM/DD 形式で取得"""
    if not date_str:
        return None

    match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2})$', date_str.strip())
    if not match:
        return None

    normalized_date = match.group(1).replace('-', '/')
    try:
        datetime.strptime(normalized_date, '%Y/%m/%d')
    except ValueError:
        return None

    return normalized_date

def days_between(date1, date2):
    """2つの日付の間の日数を計算"""
    if not date1 or not date2:
        return None
    delta = date1 - date2
    return delta.days

def calculate_horse_features(
    horse_id,
    race_history,
    target_race_date=None,
    target_race_distance=None,
    target_race_surface=None,
    target_race_course=None,
    target_race_class=None,
    target_gate=None,
    target_field_size=None,
    _allow_promotion_second_result_ignoring=True,
):
    """
    特定の馬の特徴量を計算
    
    Args:
        horse_id: 馬ID
        race_history: その馬の過去レース履歴（辞書のリスト）
        target_race_date: 予測対象のレース日付（Noneの場合は最新レースを対象）
        target_race_distance: 予測対象のレース距離
        target_race_surface: 予測対象のレース馬場（芝・ダート）
        target_race_course: 予測対象のレース競馬場
        target_race_class: 予測対象のレースクラス（0〜9）
        target_gate: 予測対象の枠番（1〜8）
        target_field_size: 予測対象レースの出走頭数
    
    Returns:
        特徴量の辞書
    """
    if not race_history and target_race_date is None:
        return {}
    
    race_history = race_history or []
    
    # 日付でソート
    race_history = sorted(race_history, key=lambda x: x.get('race_date', ''), reverse=True)
    
    # ターゲットレース日付
    if target_race_date is None:
        target_race_date = parse_date(race_history[0].get('race_date')) if race_history else None
    
    # target_race_dateより後のレースを除外（AI予測時に未来のレースを含まないように）
    if target_race_date:
        race_history = [r for r in race_history if parse_date(r.get('race_date')) < target_race_date]
    
    # コース名から数字を削除して統一
    if target_race_course:
        target_race_course = re.sub(r'[0-9]', '', target_race_course)

    features = {
        'horse_id': horse_id,
        'total_races': len(race_history),
        'prev_last_3f_rank': race_history[0].get('last_3f_rank') if race_history else None,
    }
    target_gate = parse_gate(target_gate)
    target_field_size = parse_field_size(target_field_size)
    features['target_gate'] = target_gate
    features['target_field_size'] = target_field_size
    features['target_gate_position'] = normalized_gate_position(
        target_gate,
        target_field_size,
    )
    target_gate_date = (
        target_race_date.strftime('%Y/%m/%d')
        if isinstance(target_race_date, datetime)
        else normalize_race_date(target_race_date)
    )
    features.update(
        get_course_gate_bias(
            target_race_course,
            target_race_surface,
            target_race_distance,
            target_gate_date,
            target_gate,
            target_field_size,
        )
    )
    features.update(
        get_horse_gate_preference(
            race_history,
            target_gate,
            target_field_size,
        )
    )
    target_class = parse_race_class(target_race_class)
    previous_class = (
        parse_race_class(race_history[0].get('race_class'))
        if race_history else None
    )
    features['target_race_class'] = target_class
    features['prev_race_class'] = previous_class
    features['race_class_change'] = (
        target_class - previous_class
        if target_class is not None and previous_class is not None
        else None
    )
    features['is_class_up'] = (
        int(target_class > previous_class)
        if target_class is not None and previous_class is not None
        else None
    )
    features['is_class_down'] = (
        int(target_class < previous_class)
        if target_class is not None and previous_class is not None
        else None
    )
    features['is_unwon_maiden_class_challenge'] = int(
        is_unwon_maiden_class_challenge(race_history, target_class)
    )
    target_class_races = [
        race for race in race_history
        if target_class is not None
        and parse_race_class(race.get('race_class')) == target_class
        and race.get('finish_position') is not None
    ]
    features['target_class_experience_count'] = len(target_class_races)
    features['top3_rate_target_class'] = (
        sum(
            1 for race in target_class_races
            if race['finish_position'] <= 3
        ) / len(target_class_races)
        if target_class_races else None
    )
    
    # === 過去成績系特徴量 ===
    
    # Recent form uses only matching-surface results within each recent-race window.
    recent_windows = {
        3: race_history[:3],
        5: race_history[:5],
    }
    recent_surface_races = [
        race for race in race_history
        if target_race_surface
        and race.get('surface') == target_race_surface
    ][:6]
    assessable_surface_races = []
    for race in recent_surface_races:
        finish = race.get('finish_position')
        try:
            margin = float(race.get('margin'))
        except (TypeError, ValueError):
            continue
        if finish is not None and math.isfinite(margin):
            assessable_surface_races.append((finish, margin))

    good_surface_race_count = sum(
        1 for finish, margin in assessable_surface_races
        if finish <= 5 and margin < 1.0
    )
    features['target_surface_recent_6_race_count'] = len(recent_surface_races)
    features['target_surface_recent_6_assessable_count'] = len(
        assessable_surface_races
    )
    features['target_surface_recent_6_good_count'] = good_surface_race_count
    features['target_surface_recent_6_good_rate'] = (
        good_surface_race_count / len(assessable_surface_races)
        if assessable_surface_races else None
    )
    features['target_surface_recent_6_has_good'] = (
        int(good_surface_race_count > 0)
        if recent_surface_races else None
    )

    for window_size, window_races in recent_windows.items():
        matching_races = [
            race for race in window_races
            if not target_race_surface or race.get('surface') == target_race_surface
        ]
        valid_finish = [
            race for race in matching_races
            if race.get('finish_position') is not None
        ]
        avg_key = f'recent_{window_size}_avg_finish'
        top3_key = f'recent_{window_size}_top3_rate'
        features[avg_key] = (
            sum(race['finish_position'] for race in valid_finish) / len(valid_finish)
            if valid_finish else None
        )
        features[top3_key] = (
            sum(1 for race in valid_finish if race['finish_position'] <= 3) / len(valid_finish)
            if valid_finish else None
        )

    target_surface_history = [
        race for race in race_history
        if not target_race_surface or race.get('surface') == target_race_surface
    ]
    for window_size in (1, 3, 5):
        recent_surface_races = target_surface_history[:window_size]
        valid_finish_races = [
            race for race in recent_surface_races
            if isinstance(race.get('finish_position'), (int, float))
        ]
        finish_key = f'recent_{window_size}_avg_finish_target_surface'
        margin_key = f'recent_{window_size}_avg_margin_target_surface'
        class_delta_key = f'recent_{window_size}_avg_class_delta_target_surface'
        score_key = f'recent_{window_size}_class_margin_finish'
        features[finish_key] = (
            sum(race['finish_position'] for race in valid_finish_races)
            / len(valid_finish_races)
            if valid_finish_races else None
        )

        valid_margins = []
        valid_class_deltas = []
        for race in valid_finish_races:
            try:
                margin = float(race.get('margin'))
            except (TypeError, ValueError):
                continue
            if math.isfinite(margin):
                valid_margins.append(margin)

            race_class = parse_race_class(race.get('race_class'))
            if target_class is not None and race_class is not None:
                valid_class_deltas.append(target_class - race_class)

        average_margin = (
            sum(valid_margins) / len(valid_margins)
            if valid_margins else None
        )
        average_class_delta = (
            sum(valid_class_deltas) / len(valid_class_deltas)
            if valid_class_deltas else None
        )
        features[margin_key] = average_margin
        features[class_delta_key] = average_class_delta
        features[score_key] = (
            features[finish_key]
            + RECENT_PERFORMANCE_MARGIN_WEIGHT * (average_margin or 0.0)
            + RECENT_PERFORMANCE_CLASS_WEIGHT * (average_class_delta or 0.0)
            if features[finish_key] is not None
            else None
        )

    # === 芝・ダート別の着順統計 ===

    # 全体の着順（芝）
    turf_races = [r for r in race_history if r.get('surface') == '芝']
    if turf_races:
        valid_finish = [r for r in turf_races if r.get('finish_position') is not None]
        if valid_finish:
            features['overall_avg_finish_turf'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['overall_top3_rate_turf'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['overall_avg_finish_turf'] = None
            features['overall_top3_rate_turf'] = 0
    else:
        features['overall_avg_finish_turf'] = None
        features['overall_top3_rate_turf'] = 0
    
    # 全体の着順（ダート）
    dirt_races = [r for r in race_history if r.get('surface') == 'ダート']
    if dirt_races:
        valid_finish = [r for r in dirt_races if r.get('finish_position') is not None]
        if valid_finish:
            features['overall_avg_finish_dirt'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
            features['overall_top3_rate_dirt'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        else:
            features['overall_avg_finish_dirt'] = None
            features['overall_top3_rate_dirt'] = 0
    else:
        features['overall_avg_finish_dirt'] = None
        features['overall_top3_rate_dirt'] = 0

    for surface, suffix in (('芝', 'turf'), ('ダート', 'dirt')):
        for window_size, window_races in recent_windows.items():
            avg_key = f'recent_{window_size}_avg_finish_{suffix}'
            top3_key = f'recent_{window_size}_top3_rate_{suffix}'
            if target_race_surface and surface != target_race_surface:
                features[avg_key] = None
                features[top3_key] = None
                continue

            surface_races = [
                race for race in window_races
                if race.get('surface') == surface
            ]
            valid_finish = [
                race for race in surface_races
                if race.get('finish_position') is not None
            ]
            features[avg_key] = (
                sum(race['finish_position'] for race in valid_finish) / len(valid_finish)
                if valid_finish else None
            )
            features[top3_key] = (
                sum(1 for race in valid_finish if race['finish_position'] <= 3) / len(valid_finish)
                if valid_finish else None
            )
    
    # 全体の3着以内率
    valid_finish = [r for r in race_history if r.get('finish_position') is not None]
    if valid_finish:
        features['overall_top3_rate'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
        features['overall_avg_finish'] = sum(r['finish_position'] for r in valid_finish) / len(valid_finish)
    else:
        features['overall_top3_rate'] = 0
        features['overall_avg_finish'] = None
    
    # === 休み明け・間隔系特徴量 ===
    
    if len(race_history) > 1 and target_race_date:
        # 前走からの間隔
        prev_date = parse_date(race_history[0].get('race_date'))
        days_since_last = days_between(target_race_date, prev_date)
        features['days_since_last_race'] = days_since_last
        
        # 休み明けフラグ（90日以上）
        features['is_long_break'] = 1 if days_since_last and days_since_last >= 90 else 0
        
        # 連闘フラグ（9日以内）
        features['is_consecutive'] = 1 if days_since_last and days_since_last <= 9 else 0
        
        # 中一週フラグ（10-16日）
        features['is_short_break'] = 1 if days_since_last and 10 <= days_since_last <= 16 else 0
        
        # 斟き目フラグ（休み明け後の2走目、3走目）
        for i in range(len(race_history) - 1):
            if i == 0:
                continue
            date1 = parse_date(race_history[i-1].get('race_date'))
            date2 = parse_date(race_history[i].get('race_date'))
            date_diff = days_between(date1, date2)
            if date_diff and date_diff >= 90:
                if i == 1:
                    features['is_tataki_2nd'] = 1
                elif i == 2:
                    features['is_tataki_3rd'] = 1
                break
        
        if 'is_tataki_2nd' not in features:
            features['is_tataki_2nd'] = 0
        if 'is_tataki_3rd' not in features:
            features['is_tataki_3rd'] = 0
    else:
        features['days_since_last_race'] = None
        features['is_long_break'] = 0
        features['is_consecutive'] = 0
        features['is_short_break'] = 0
        features['is_tataki_2nd'] = 0
        features['is_tataki_3rd'] = 0
    
    # === 距離適性（予想するレースの距離に合わせる） ===

    dist_races = [
        race for race in race_history
        if target_race_distance
        and race.get('distance') == target_race_distance
        and race.get('finish_position') is not None
    ]
    features['top3_rate_target_distance'] = (
        sum(1 for race in dist_races if race['finish_position'] <= 3)
        / len(dist_races)
        if dist_races else 0
    )
    distance_surface_races = [
        race for race in race_history
        if target_race_distance
        and target_race_surface
        and race.get('distance') == target_race_distance
        and race.get('surface') == target_race_surface
        and race.get('finish_position') is not None
    ]
    features['target_distance_surface_experience_count'] = len(
        distance_surface_races
    )
    features['top3_rate_target_distance_surface'] = (
        sum(
            1 for race in distance_surface_races
            if race['finish_position'] <= 3
        ) / len(distance_surface_races)
        if distance_surface_races else None
    )

    # === 距離実績の詳細化（各距離での3着内率） ===
    for dist in [1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 3000]:
        dist_races_detail = [
            race for race in race_history
            if race.get('distance') == dist
            and race.get('finish_position') is not None
        ]
        features[f'top3_rate_{dist}m'] = (
            sum(1 for race in dist_races_detail if race['finish_position'] <= 3)
            / len(dist_races_detail)
            if dist_races_detail else None
        )

    # === コース適性（予想するレースのコースに合わせる） ===

    if target_race_course:
        # 今回のコースでの3着以内率
        course_races = [r for r in race_history if target_race_course in r.get('course', '')]
        if course_races:
            valid_finish = [r for r in course_races if r.get('finish_position') is not None]
            if valid_finish:
                features['top3_rate_target_course'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
            else:
                features['top3_rate_target_course'] = 0
        else:
            features['top3_rate_target_course'] = 0
    else:
        features['top3_rate_target_course'] = 0

    # === 競馬場実績の詳細化（各競馬場での3着内率） ===
    jra_courses = ['東京', '中京', '新潟', '中山', '福島', '函館', '札幌', '阪神', '京都', '小倉']
    for course in jra_courses:
        course_races_detail = [
            race for race in race_history
            if course in race.get('course', '')
            and race.get('finish_position') is not None
        ]
        features[f'top3_rate_{course}'] = (
            sum(1 for race in course_races_detail if race['finish_position'] <= 3)
            / len(course_races_detail)
            if course_races_detail else None
        )

    # === 芝・ダート適性（予想するレースの馬場に合わせる） ===
    
    surface_races = [
        race for race in race_history
        if target_race_surface
        and race.get('surface') == target_race_surface
        and race.get('finish_position') is not None
    ]
    features['top3_rate_target_surface'] = (
        sum(1 for race in surface_races if race['finish_position'] <= 3)
        / len(surface_races)
        if surface_races else 0
    )

    target_course_races = [
        race for race in race_history
        if target_race_course
        and target_race_course in (race.get('course') or '')
        and race.get('finish_position') is not None
    ]
    target_condition_races = [
        race for race in race_history
        if target_race_course
        and target_race_surface
        and target_race_distance
        and target_race_course in (race.get('course') or '')
        and race.get('surface') == target_race_surface
        and race.get('distance') == target_race_distance
        and race.get('finish_position') is not None
    ]
    features['target_course_experience_count'] = len(target_course_races)
    features['target_surface_experience_count'] = len(surface_races)
    features['target_condition_experience_count'] = len(target_condition_races)
    features['top3_rate_target_condition'] = (
        sum(
            1 for race in target_condition_races
            if race['finish_position'] <= 3
        ) / len(target_condition_races)
        if target_condition_races else None
    )
    
    # === 人気・着順系 ===
    
    if len(race_history) > 0:
        features['last_popularity'] = race_history[0].get('popularity')
        last_race_matches_surface = (
            not target_race_surface
            or race_history[0].get('surface') == target_race_surface
        )
        features['last_finish'] = (
            race_history[0].get('finish_position')
            if last_race_matches_surface else None
        )
    else:
        features['last_popularity'] = None
        features['last_finish'] = None
    
    valid_pop = [r for r in race_history if r.get('popularity') is not None]
    if valid_pop:
        features['avg_popularity'] = sum(r['popularity'] for r in valid_pop) / len(valid_pop)
    else:
        features['avg_popularity'] = None
    
    # === 昇級二戦目系 ===

    # 前々走の着順
    if len(race_history) >= 2:
        features['prev2_finish'] = race_history[1].get('finish_position')
    else:
        features['prev2_finish'] = None

    # 前々走の距離
    if len(race_history) >= 2:
        features['prev2_distance'] = race_history[1].get('distance')
    else:
        features['prev2_distance'] = None

    # === 前走の距離・競馬場フラグ ===

    # 前走の距離
    if len(race_history) >= 1:
        prev_distance = race_history[0].get('distance')
        features['prev_distance'] = prev_distance

        # 前走の距離フラグ
        for dist in [1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 3000]:
            features[f'prev_distance_is_{dist}m'] = (
                1 if prev_distance == dist else 0
                if prev_distance is not None else None
            )
    else:
        features['prev_distance'] = None
        for dist in [1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 3000]:
            features[f'prev_distance_is_{dist}m'] = None

    # 前走の競馬場
    if len(race_history) >= 1:
        prev_course = race_history[0].get('course')
        features['prev_course'] = prev_course

        # 前走の競馬場フラグ
        jra_courses = ['東京', '中京', '新潟', '中山', '福島', '函館', '札幌', '阪神', '京都', '小倉']
        for course in jra_courses:
            features[f'prev_course_is_{course}'] = (
                1 if course in (prev_course or '') else 0
                if prev_course is not None else None
            )
    else:
        features['prev_course'] = None
        jra_courses = ['東京', '中京', '新潟', '中山', '福島', '函館', '札幌', '阪神', '京都', '小倉']
        for course in jra_courses:
            features[f'prev_course_is_{course}'] = None
    
    # 前々走と前走の間隔
    if len(race_history) >= 2:
        date1 = parse_date(race_history[0].get('race_date'))
        date2 = parse_date(race_history[1].get('race_date'))
        features['prev2_to_prev_interval'] = days_between(date1, date2)
    else:
        features['prev2_to_prev_interval'] = None
    
    previous_class = (
        parse_race_class(race_history[0].get('race_class'))
        if len(race_history) >= 1 else None
    )
    previous_previous_finish = (
        race_history[1].get('finish_position')
        if len(race_history) >= 2 else None
    )
    features['is_promotion_2nd'] = (
        int(
            previous_class == target_class
            and previous_previous_finish == 1
        )
        if (
            target_class is not None
            and previous_class is not None
            and previous_previous_finish is not None
        )
        else None
    )
    is_promotion_second = features['is_promotion_2nd'] == 1
    promotion_second_previous_race = race_history[0] if race_history else {}
    promotion_second_previous_previous_race = (
        race_history[1] if len(race_history) >= 2 else {}
    )
    previous_race_course = promotion_second_previous_race.get('course')
    features['promotion_2nd_prev_course_match'] = (
        int(target_race_course in previous_race_course)
        if (
            is_promotion_second
            and target_race_course
            and isinstance(previous_race_course, str)
        )
        else None
    )
    previous_race_distance = promotion_second_previous_race.get('distance')
    features['promotion_2nd_prev_distance_diff'] = (
        target_race_distance - previous_race_distance
        if (
            is_promotion_second
            and isinstance(target_race_distance, (int, float))
            and isinstance(previous_race_distance, (int, float))
        )
        else None
    )
    features['promotion_2nd_prev_abs_distance_diff'] = (
        abs(features['promotion_2nd_prev_distance_diff'])
        if features['promotion_2nd_prev_distance_diff'] is not None
        else None
    )
    previous_race_finish = promotion_second_previous_race.get('finish_position')
    features['promotion_2nd_prev_finish'] = (
        previous_race_finish if is_promotion_second else None
    )
    try:
        previous_race_margin = float(promotion_second_previous_race.get('margin'))
    except (TypeError, ValueError):
        previous_race_margin = None
    features['promotion_2nd_prev_margin'] = (
        previous_race_margin
        if is_promotion_second
        and previous_race_margin is not None
        and math.isfinite(previous_race_margin)
        else None
    )
    features['promotion_2nd_prev_last_3f_rank'] = (
        promotion_second_previous_race.get('last_3f_rank')
        if is_promotion_second
        else None
    )
    features['promotion_2nd_prev_to_prev_interval'] = (
        features['prev2_to_prev_interval'] if is_promotion_second else None
    )
    promotion_second_previous_date = parse_date(
        promotion_second_previous_race.get('race_date')
    )
    features['promotion_2nd_prev_to_target_interval'] = (
        days_between(target_race_date, promotion_second_previous_date)
        if is_promotion_second and target_race_date and promotion_second_previous_date
        else None
    )
    features['promotion_2nd_prev_good_result'] = (
        int(
            promotion_second_previous_race.get('finish_position') <= 5
            and features['promotion_2nd_prev_margin'] < 1.0
        )
        if (
            is_promotion_second
            and isinstance(promotion_second_previous_race.get('finish_position'), (int, float))
            and features['promotion_2nd_prev_margin'] is not None
        )
        else None
    )
    features['promotion_2nd_good_target_course_record'] = (
        int(
            features['target_course_experience_count'] > 0
            and features['top3_rate_target_course'] >= 0.5
        )
        if is_promotion_second and features['top3_rate_target_course'] is not None
        else None
    )
    features['promotion_2nd_good_target_distance_record'] = (
        int(
            features['target_distance_surface_experience_count'] > 0
            and features['top3_rate_target_distance_surface'] >= 0.5
        )
        if (
            is_promotion_second
            and features['top3_rate_target_distance_surface'] is not None
        )
        else None
    )
    features['promotion_2nd_good_result_after_layoff'] = (
        int(
            features['promotion_2nd_prev_good_result'] == 1
            and features['promotion_2nd_prev_to_prev_interval'] >= 90
        )
        if (
            features['promotion_2nd_prev_good_result'] is not None
            and features['promotion_2nd_prev_to_prev_interval'] is not None
        )
        else None
    )

    # === 距離短縮・拡大系 ===
    
    if target_race_distance and len(race_history) >= 1:
        prev_distance = race_history[0].get('distance')
        if prev_distance:
            features['prev_distance_diff'] = target_race_distance - prev_distance
            features['is_distance_shortening'] = 1 if target_race_distance < prev_distance else 0
            features['is_distance_expanding'] = 1 if target_race_distance > prev_distance else 0
        else:
            features['prev_distance_diff'] = None
            features['is_distance_shortening'] = 0
            features['is_distance_expanding'] = 0

        # 今回の距離経験回数
        same_distance_count = sum(1 for r in race_history if r.get('distance') == target_race_distance)
        features['target_distance_experience_count'] = same_distance_count
        features['is_first_time_distance'] = 1 if same_distance_count == 0 else 0
    else:
        features['prev_distance_diff'] = None
        features['is_distance_shortening'] = 0
        features['is_distance_expanding'] = 0
        features['target_distance_experience_count'] = 0
        features['is_first_time_distance'] = int(bool(target_race_distance))

    # === 二戦目系 ===

    # ダート二戦目フラグ（ダート未勝利戦でダート経験あり）
    if target_race_surface == 'ダート':
        dirt_count = sum(1 for r in race_history if r.get('surface') == 'ダート')
        features['is_dirt_2nd'] = 1 if dirt_count == 1 else 0
    else:
        features['is_dirt_2nd'] = 0

    # The previous same-surface run must be the shortest on that surface,
    # and today's distance must be its second start at that distance.
    surface_distances = [
        race.get('distance')
        for race in race_history
        if target_race_surface and race.get('surface') == target_race_surface
        and isinstance(race.get('distance'), (int, float))
        and race.get('distance') > 0
    ]
    same_surface_target_distance_races = [
        race for race in race_history
        if target_race_surface
        and race.get('surface') == target_race_surface
        and race.get('distance') == target_race_distance
    ]
    previous_race_is_target_surface = (
        bool(race_history)
        and race_history[0].get('surface') == target_race_surface
    )
    features['is_shortening_2nd'] = (
        int(
            previous_race_is_target_surface
            and race_history[0].get('distance') == target_race_distance
            and len(same_surface_target_distance_races) == 1
            and bool(surface_distances)
            and race_history[0].get('distance') == min(surface_distances)
        )
        if target_race_surface and target_race_distance and surface_distances
        else None
    )
    
    # Previous win followed by a poor finish; class movement is captured separately.
    prev_finish = race_history[0].get('finish_position') if race_history else None
    prev2_finish = race_history[1].get('finish_position') if len(race_history) >= 2 else None
    features['is_win_then_poor_finish_2nd'] = int(
        prev2_finish == 1
        and isinstance(prev_finish, (int, float))
        and prev_finish >= 5
    )

    # === コース代わりの成績 ===

    if target_race_course and len(race_history) >= 1:
        prev_course = race_history[0].get('course')
        # 前走と今回でコースが異なる場合
        if prev_course and target_race_course not in prev_course:
            # 今回のコースでの成績を計算
            course_races = [r for r in race_history if target_race_course in r.get('course', '')]
            if course_races:
                valid_finish = [r for r in course_races if r.get('finish_position') is not None]
                if valid_finish:
                    features['prev_course_change_score'] = sum(1 for r in valid_finish if r['finish_position'] <= 3) / len(valid_finish)
                else:
                    features['prev_course_change_score'] = 0
            else:
                features['prev_course_change_score'] = 0
        else:
            features['prev_course_change_score'] = 0
    else:
        features['prev_course_change_score'] = 0
    
    # === ペース・タイム系 ===
    
    valid_last3f = [r for r in race_history if r.get('last_3f') and r.get('last_3f') != '']
    if valid_last3f:
        last3f_numeric = []
        for r in valid_last3f:
            try:
                last3f_numeric.append(float(r['last_3f']))
            except:
                pass
        if last3f_numeric:
            features['avg_last_3f'] = sum(last3f_numeric) / len(last3f_numeric)
        else:
            features['avg_last_3f'] = None
    else:
        features['avg_last_3f'] = None

    features['promotion_2nd_prev_result_ignored'] = 0
    features['promotion_2nd_prev_actual_finish'] = None
    features['promotion_2nd_prev_actual_margin'] = None
    features['promotion_2nd_prev_actual_last_3f_rank'] = None
    if (
        _allow_promotion_second_result_ignoring
        and is_promotion_second
        and should_neutralize_promotion_second_previous_result(
            features['promotion_2nd_prev_finish'],
            features['promotion_2nd_prev_margin'],
        )
    ):
        previous_finish = features['promotion_2nd_prev_finish']
        previous_margin = features['promotion_2nd_prev_margin']
        previous_last_3f_rank = features['promotion_2nd_prev_last_3f_rank']
        features['promotion_2nd_prev_result_ignored'] = 1
        features['promotion_2nd_prev_actual_finish'] = previous_finish
        features['promotion_2nd_prev_actual_margin'] = previous_margin
        features['promotion_2nd_prev_actual_last_3f_rank'] = (
            previous_last_3f_rank
        )

        earlier_features = calculate_horse_features(
            horse_id,
            race_history[1:],
            target_race_date=target_race_date,
            target_race_distance=target_race_distance,
            target_race_surface=target_race_surface,
            target_race_course=target_race_course,
            target_race_class=target_race_class,
            target_gate=target_gate,
            target_field_size=target_field_size,
            _allow_promotion_second_result_ignoring=False,
        )
        for feature_name in PROMOTION_SECOND_RESULT_FEATURES_TO_RECALCULATE:
            features[feature_name] = earlier_features.get(feature_name)

        features['promotion_2nd_prev_finish'] = None
        features['promotion_2nd_prev_margin'] = None
        if not (
            isinstance(previous_last_3f_rank, (int, float))
            and previous_last_3f_rank <= 3
        ):
            features['prev_last_3f_rank'] = None
            features['promotion_2nd_prev_last_3f_rank'] = None
        features['is_win_then_poor_finish_2nd'] = 0
        features['promotion_2nd_good_target_course_record'] = (
            int(
                features['target_course_experience_count'] > 0
                and features['top3_rate_target_course'] >= 0.5
            )
            if features['top3_rate_target_course'] is not None
            else None
        )
        features['promotion_2nd_good_target_distance_record'] = (
            int(
                features['target_distance_surface_experience_count'] > 0
                and features['top3_rate_target_distance_surface'] >= 0.5
            )
            if features['top3_rate_target_distance_surface'] is not None
            else None
        )
    
    return features

def get_horse_race_history(horse_id):
    """特定の馬のレース履歴を取得"""
    conn = get_connection()
    # SQLインジェクション対策：horse_idをエスケープ
    escaped_id = horse_id.replace("'", "''")
    query = f'''
        SELECT * FROM horse_data_dtl
        WHERE horse_id = '{escaped_id}'
        ORDER BY race_date DESC
    '''
    try:
        cur = conn.execute(query)
        columns = [description[0] for description in cur.description]
        rows = cur.fetchall()
        # 辞書のリストに変換
        data = [dict(zip(columns, row)) for row in rows]
        return data
    except Exception as e:
        print(f"Error reading race history for {horse_id}: {e}")
        return []
    finally:
        conn.close()

def calculate_features_for_horses(horse_ids, target_race_date=None):
    """
    複数の馬の特徴量を一括計算
    
    Args:
        horse_ids: 馬IDのリスト
        target_race_date: 予測対象のレース日付
    
    Returns:
        特徴量の辞書のリスト
    """
    all_features = []
    
    for horse_id in horse_ids:
        race_history = get_horse_race_history(horse_id)
        features = calculate_horse_features(horse_id, race_history, target_race_date)
        all_features.append(features)
    
    return all_features

if __name__ == '__main__':
    # テスト実行
    conn = get_connection()
    cur = conn.execute('SELECT horse_id FROM horse_data_hd LIMIT 5')
    test_horses = [row[0] for row in cur.fetchall()]
    conn.close()

    print(f"テスト対象馬: {test_horses}")

    for horse_id in test_horses:
        race_history = get_horse_race_history(horse_id)
        features = calculate_horse_features(horse_id, race_history)
        print(f"\n馬ID: {horse_id}")
        print(f"特徴量数: {len(features)}")
        print(f"総レース数: {features.get('total_races', 0)}")
        print(f"最近3走平均着順: {features.get('recent_3_avg_finish')}")
        print(f"最近3走3着以内率: {features.get('recent_3_top3_rate')}")

def apply_recent_performance_balance(
    probability,
    features,
    threshold_recent=6,
    threshold_performance=0.3,
    penalty_factor=0.3,
    rescue_factor=1.35,
    bonus_factor=1.0,
):
    """Balance recent class- and margin-adjusted form with course aptitude."""
    recent_performance = features.get('recent_3_class_margin_finish')
    if recent_performance is None:
        recent_performance = features.get('recent_3_avg_finish')
    target_course_performance = features.get('top3_rate_target_course', 0)
    target_distance_performance = features.get('top3_rate_target_distance', 0)

    # Noneチェック
    if recent_performance is None:
        return probability
    if target_course_performance is None:
        target_course_performance = 0
    if target_distance_performance is None:
        target_distance_performance = 0

    # 条件1: 近走も悪ければ同距離、コース実績もない→消去
    if recent_performance > threshold_recent and target_course_performance < threshold_performance and target_distance_performance < threshold_performance:
        previous_margin = features.get('dirt_maiden_previous_margin')
        dirt_maiden_positive_signal = (
            features.get('dirt_maiden_is_second_dirt_start') == 1
            and features.get('dirt_maiden_previous_surface_is_dirt') == 1
            and features.get('dirt_maiden_previous_last3f_top3') == 1
            and isinstance(previous_margin, (int, float))
            and previous_margin <= 1.0
        )
        dirt_maiden_distance_shortening_signal = (
            features.get('dirt_maiden_is_second_start_after_distance_drop') == 1
            and features.get('dirt_maiden_previous_surface_is_dirt') == 1
            and features.get('dirt_maiden_previous_good_finish') == 1
        )
        if dirt_maiden_positive_signal or dirt_maiden_distance_shortening_signal:
            return probability
        return probability * penalty_factor

    # 条件2: 近走が悪いが得意コース、距離→消去はしない
    if recent_performance > threshold_recent and (target_course_performance >= threshold_performance or target_distance_performance >= threshold_performance):
        return probability * rescue_factor

    # 条件3: 近走がいいが不得意コース、距離→消去はしない
    if recent_performance <= threshold_recent and target_course_performance < threshold_performance and target_distance_performance < threshold_performance:
        return probability * 1.0  # 変更なし

    # 条件4: 近走もいいし得意コース、距離→加点
    if recent_performance <= threshold_recent and (target_course_performance >= threshold_performance or target_distance_performance >= threshold_performance):
        return probability * bonus_factor

    return probability
