import glob
import os
import pickle
import re
from datetime import datetime
import lightgbm as lgb
import numpy as np
from feature_engineering import (
    NULL_AS_NAN_FEATURES,
    PROMOTION_SECOND_CONTEXT_FEATURES,
    PROMOTION_SECOND_CONTEXT_SHRINKAGE,
    apply_promotion_second_boost,
    get_promotion_second_context_values,
)


MIN_RACES_FOR_TEMPORAL_SPLIT = 20
PROMOTION_SECOND_CONTEXT_MODEL_FILE = 'promotion_second_context.pkl'


def prepare_features_for_model(features_list):
    """特徴量のリストをモデル用に前処理"""
    if not features_list:
        return None, None

    # カラム名を取得
    feature_columns = list(features_list[0].keys())

    # 不要なカラムを削除
    cols_to_drop = [
        'horse_id', 'last_jockey',
        'promotion_2nd_prev_result_ignored',
        'promotion_2nd_prev_actual_finish',
        'promotion_2nd_prev_actual_margin',
        'promotion_2nd_prev_actual_last_3f_rank',
        'is_unwon_maiden_class_challenge',
        'last_popularity',  # 人気系（削除）
        'avg_popularity',   # 人気系（削除）
        'prev_course',  # 文字列特徴量（削除）
        'prev_distance',  # 文字列特徴量（削除）
        # 馬場適性（削除）
        'top3_rate_condition_良', 'top3_rate_condition_稍', 'top3_rate_condition_重', 'top3_rate_condition_不',
        # 距離適性（古い、削除）
        'top3_rate_distance_short', 'top3_rate_distance_medium', 'top3_rate_distance_long',
        # コース適性（古い、削除）
        'top3_rate_course_東京', 'top3_rate_course_中山', 'top3_rate_course_京都', 'top3_rate_course_阪神', 'top3_rate_course_新潟',
        # 芝・ダート適性（古い、削除）
        'top3_rate_surface_芝', 'top3_rate_surface_ダート',
        # 斤量系（削除）
        'avg_carried_weight', 'weight_change',
        # 馬体系（削除）
        'avg_horse_weight', 'horse_weight_change',
        # 古いkyori系（削除）
        'is_diff_distance_from_prev', 'same_distance_experience',
        # 古いdirt系（削除）
        'has_dirt_experience'
    ]
    cols_to_drop.extend(
        f'recent_{window}_{suffix}'
        for window in (1, 3, 5)
        for suffix in (
            'avg_finish_target_surface',
            'avg_margin_target_surface',
            'avg_class_delta_target_surface',
            'class_margin_finish',
        )
    )

    # 実際に存在するカラムのみを削除
    cols_to_drop = [c for c in cols_to_drop if c in feature_columns]

    # 特徴量行列を作成
    X = []
    for features in features_list:
        row = []
        for col in feature_columns:
            if col in cols_to_drop:
                continue
            value = features.get(col)
            if value is None:
                row.append(np.nan if col in NULL_AS_NAN_FEATURES else 0.0)
            else:
                row.append(float(value))
        X.append(row)

    # カラム名を更新
    feature_columns = [c for c in feature_columns if c not in cols_to_drop]

    return np.array(X), feature_columns


def get_model_params(feature_columns, model_group):
    """Return the LightGBM parameters used for production condition models."""
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'max_depth': -1,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'verbose': -1
    }
    if model_group == 'condition':
        positive_features = {
            'is_promotion_2nd',
            'is_shortening_2nd',
            'target_surface_recent_6_good_count',
            'target_surface_recent_6_good_rate',
            'target_surface_recent_6_has_good',
        }
        params['monotone_constraints'] = [
            1 if feature in positive_features else 0
            for feature in feature_columns
        ]
    return params


def split_indices_by_race_date(
    race_ids,
    race_dates,
    minimum_races=MIN_RACES_FOR_TEMPORAL_SPLIT,
):
    """Split samples chronologically while keeping every race in one partition."""
    if len(race_ids) != len(race_dates):
        raise ValueError('race_ids and race_dates must have the same number of rows')

    race_date_by_id = {}
    for race_id, race_date in zip(race_ids, race_dates):
        try:
            datetime.strptime(race_date, '%Y/%m/%d')
        except (TypeError, ValueError):
            raise ValueError(f'Race {race_id} has an invalid race date: {race_date!r}')
        previous_date = race_date_by_id.setdefault(str(race_id), race_date)
        if previous_date != race_date:
            raise ValueError(f'Race {race_id} has inconsistent race dates')

    races = sorted(race_date_by_id.items(), key=lambda item: (item[1], item[0]))
    if len(races) < minimum_races:
        raise ValueError(
            f'At least {minimum_races} distinct races are required; '
            f'found {len(races)}'
        )

    dates = sorted({race_date for _, race_date in races})
    if len(dates) < 7:
        raise ValueError(
            f'At least 7 distinct race dates are required; found {len(dates)}'
        )
    train_end = int(len(dates) * 0.70)
    validation_end = train_end + int(len(dates) * 0.15)
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:validation_end])
    test_dates = set(dates[validation_end:])
    train_races = {race_id for race_id, date in races if date in train_dates}
    validation_races = {race_id for race_id, date in races if date in validation_dates}
    test_races = {race_id for race_id, date in races if date in test_dates}

    partitions = {
        'train': train_races,
        'validation': validation_races,
        'test': test_races,
    }
    if any(not race_set for race_set in partitions.values()):
        raise ValueError('Chronological split produced an empty partition')

    indices = {
        name: np.array(
            [index for index, race_id in enumerate(race_ids) if str(race_id) in race_set],
            dtype=int,
        )
        for name, race_set in partitions.items()
    }

    if train_races & validation_races or train_races & test_races or validation_races & test_races:
        raise AssertionError('A race appears in more than one partition')

    return {
        'indices': indices,
        'race_counts': {name: len(race_set) for name, race_set in partitions.items()},
        'date_ranges': {
            'train': (dates[0], dates[train_end - 1]),
            'validation': (dates[train_end], dates[validation_end - 1]),
            'test': (dates[validation_end], dates[-1]),
        },
    }


def train_promotion_second_context_model(training_files=None):
    """Train a pooled, time-split model for promotion-second context."""
    # sklearnは予測時ではなくこの学習処理でのみ必要なため遅延importする
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if training_files is None:
        training_files = sorted(glob.glob('training_data_*_condition.pkl'))

    samples = []
    for filename in training_files:
        if not filename.endswith('_condition.pkl'):
            continue
        with open(filename, 'rb') as f:
            data = pickle.load(f)
        if not (
            len(data['features'])
            == len(data['targets'])
            == len(data['race_ids'])
            == len(data['race_dates'])
        ):
            raise ValueError(f'{filename} has inconsistent training data lengths')

        for features, target, race_id, race_date in zip(
            data['features'],
            data['targets'],
            data['race_ids'],
            data['race_dates'],
        ):
            if features.get('is_promotion_2nd') == 1:
                samples.append({
                    'features': features,
                    'target': int(target),
                    'race_id': str(race_id),
                    'race_date': race_date,
                })

    if not samples:
        raise ValueError('No promotion-second samples found in condition data')

    split = split_indices_by_race_date(
        [sample['race_id'] for sample in samples],
        [sample['race_date'] for sample in samples],
    )
    train_indices = split['indices']['train']
    test_indices = split['indices']['test']
    X = np.asarray([
        [
            np.nan if value is None else float(value)
            for value in get_promotion_second_context_values(sample['features'])
        ]
        for sample in samples
    ])
    y = np.asarray([sample['target'] for sample in samples], dtype=int)
    X_train, y_train = X[train_indices], y[train_indices]
    X_test, y_test = X[test_indices], y[test_indices]

    model = make_pipeline(
        SimpleImputer(strategy='median', add_indicator=True),
        StandardScaler(),
        LogisticRegression(C=0.01, max_iter=2000),
    )
    model.fit(X_train, y_train)
    test_predictions = model.predict_proba(X_test)[:, 1]
    baseline_rate = float(np.mean(y_train))
    baseline_predictions = np.full(len(y_test), baseline_rate)
    baseline_odds = baseline_rate / (1.0 - baseline_rate)
    context_odds = test_predictions / (1.0 - test_predictions)
    context_odds_ratio = np.clip(
        context_odds / baseline_odds,
        1.0,
        2.0,
    )
    shrunk_odds = baseline_odds * (
        context_odds_ratio ** PROMOTION_SECOND_CONTEXT_SHRINKAGE
    )
    shrunk_predictions = shrunk_odds / (1.0 + shrunk_odds)

    evaluation = {
        'train_samples': len(train_indices),
        'test_samples': len(test_indices),
        'test_top3_rate': float(np.mean(y_test)),
        'baseline_rate': baseline_rate,
        'baseline_brier_score': brier_score_loss(y_test, baseline_predictions),
        'context_brier_score': brier_score_loss(y_test, test_predictions),
        'shrunk_context_brier_score': brier_score_loss(
            y_test,
            shrunk_predictions,
        ),
        'baseline_log_loss': log_loss(y_test, baseline_predictions, labels=[0, 1]),
        'context_log_loss': log_loss(y_test, test_predictions, labels=[0, 1]),
        'shrunk_context_log_loss': log_loss(
            y_test,
            shrunk_predictions,
            labels=[0, 1],
        ),
        'context_shrinkage': PROMOTION_SECOND_CONTEXT_SHRINKAGE,
        'context_roc_auc': (
            roc_auc_score(y_test, test_predictions)
            if len(np.unique(y_test)) > 1
            else None
        ),
        'date_ranges': split['date_ranges'],
    }

    # Refit on all available history for production predictions.
    model.fit(X, y)
    artifact = {
        'model': model,
        'feature_columns': list(PROMOTION_SECOND_CONTEXT_FEATURES),
        'base_rate': float(np.mean(y)),
        'evaluation': evaluation,
    }
    with open(PROMOTION_SECOND_CONTEXT_MODEL_FILE, 'wb') as f:
        pickle.dump(artifact, f)

    print(
        'Promotion-second context model: '
        f"train={evaluation['train_samples']}, "
        f"test={evaluation['test_samples']}, "
        f"baseline Brier={evaluation['baseline_brier_score']:.4f}, "
        f"context Brier={evaluation['context_brier_score']:.4f}, "
        f"shrunk Brier={evaluation['shrunk_context_brier_score']:.4f}, "
        f"baseline LogLoss={evaluation['baseline_log_loss']:.4f}, "
        f"context LogLoss={evaluation['context_log_loss']:.4f}, "
        f"shrunk LogLoss={evaluation['shrunk_context_log_loss']:.4f}, "
        f"saved={PROMOTION_SECOND_CONTEXT_MODEL_FILE}"
    )
    return artifact


def train_model_by_condition(course, distance, surface, model_group):
    """特定のレース条件のモデルを学習"""
    # sklearnは予測時ではなくこの学習処理でのみ必要なため遅延importする
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    filename = f"training_data_{course}_{surface}_{distance}m_{model_group}.pkl"

    if not os.path.exists(filename):
        print(f"  Skipped: {filename} not found")
        return None

    # 学習データを読み込み
    with open(filename, 'rb') as f:
        data = pickle.load(f)

    all_features = data['features']
    all_targets = data['targets']
    race_ids = data.get('race_ids')
    race_dates = data.get('race_dates')

    if len(all_features) < 10:
        print(f"  Skipped: No data in {filename}")
        return None
    if race_ids is None or race_dates is None:
        print(f"  Skipped: {filename} has no race metadata; regenerate training data")
        return None
    if not (len(all_features) == len(all_targets) == len(race_ids) == len(race_dates)):
        raise ValueError(f'{filename} has inconsistent sample and race metadata lengths')
    if len(np.unique(all_targets)) < 2:
        print(f"  Skipped: {filename} contains only one target class")
        return None

    print(f"  Training {len(all_features)} samples...")

    # 特徴量を前処理
    X, feature_columns = prepare_features_for_model(all_features)
    y = np.array(all_targets)

    try:
        split = split_indices_by_race_date(race_ids, race_dates)
    except ValueError as error:
        print(f"  Skipped: {error}")
        return None

    train_indices = split['indices']['train']
    validation_indices = split['indices']['validation']
    test_indices = split['indices']['test']
    X_train, y_train = X[train_indices], y[train_indices]
    X_validation, y_validation = X[validation_indices], y[validation_indices]
    X_test, y_test = X[test_indices], y[test_indices]

    if len(np.unique(y_train)) < 2:
        print("  Skipped: Training period contains only one target class")
        return None

    # LightGBMモデル学習
    params = get_model_params(feature_columns, model_group)

    train_data = lgb.Dataset(X_train, label=y_train)
    validation_data = lgb.Dataset(X_validation, label=y_validation, reference=train_data)

    validation_model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[validation_data],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)]
    )

    best_iteration = validation_model.best_iteration or 1000

    # Keep the latest period untouched until the final evaluation.
    y_pred_raw = validation_model.predict(X_test, num_iteration=best_iteration)
    if model_group == 'condition' and 'is_promotion_2nd' in feature_columns:
        promotion_index = feature_columns.index('is_promotion_2nd')
        y_pred = np.array([
            apply_promotion_second_boost(probability, is_promotion_second)
            for probability, is_promotion_second
            in zip(y_pred_raw, X_test[:, promotion_index])
        ])
    else:
        y_pred = y_pred_raw
    test_log_loss = log_loss(y_test, y_pred, labels=[0, 1])
    test_brier = brier_score_loss(y_test, y_pred)
    test_auc = roc_auc_score(y_test, y_pred) if len(np.unique(y_test)) > 1 else None
    raw_test_log_loss = log_loss(y_test, y_pred_raw, labels=[0, 1])
    raw_test_brier = brier_score_loss(y_test, y_pred_raw)
    promotion_second_test_samples = (
        int(np.sum(X_test[:, promotion_index] == 1))
        if model_group == 'condition' and 'is_promotion_2nd' in feature_columns
        else 0
    )
    train_prevalence = float(np.mean(y_train))
    baseline_brier = brier_score_loss(y_test, np.full(len(y_test), train_prevalence))
    brier_skill = 1 - test_brier / baseline_brier if baseline_brier else None

    split_summary = {
        'race_counts': split['race_counts'],
        'date_ranges': split['date_ranges'],
        'sample_counts': {
            'train': len(train_indices),
            'validation': len(validation_indices),
            'test': len(test_indices),
        },
        'best_iteration': best_iteration,
        'test_log_loss': test_log_loss,
        'test_brier_score': test_brier,
        'test_brier_skill': brier_skill,
        'test_raw_log_loss': raw_test_log_loss,
        'test_raw_brier_score': raw_test_brier,
        'promotion_second_test_samples': promotion_second_test_samples,
        'test_roc_auc': test_auc,
        'test_actual_top3_rate': float(np.mean(y_test)),
        'test_mean_predicted_probability': float(np.mean(y_pred)),
    }
    metrics_message = (
        f"  Chronological races: train={split['race_counts']['train']}, "
        f"validation={split['race_counts']['validation']}, "
        f"test={split['race_counts']['test']}; "
        f"test LogLoss={test_log_loss:.4f}, Brier={test_brier:.4f}"
    )
    if brier_skill is not None:
        metrics_message += f", Brier skill={brier_skill:.4f}"
    print(metrics_message)
    if test_auc is not None:
        print(f"  Test ROC AUC: {test_auc:.4f}")
    else:
        print("  Test ROC AUC: unavailable (test period has only one target class)")

    # 特徴量重要度
    importance = validation_model.feature_importance(importance_type='gain')
    feature_importance = dict(zip(feature_columns, importance))

    # Use the validation-selected iteration count for the production model trained
    # on all available historical samples; test metrics remain from the held-out fit.
    production_data = lgb.Dataset(X, label=y)
    model = lgb.train(params, production_data, num_boost_round=best_iteration)

    # モデルを保存
    model_filename = f"model_{course}_{surface}_{distance}m_{model_group}.pkl"
    with open(model_filename, 'wb') as f:
        pickle.dump({
            'model': model,
            'feature_columns': feature_columns,
            'feature_importance': feature_importance,
            'evaluation': split_summary
        }, f)

    print(f"  Saved: {model_filename}")

    return {
        'course': course,
        'distance': distance,
        'surface': surface,
        'model_group': model_group,
        'evaluation': split_summary,
        'feature_importance': feature_importance,
        'test_targets': y_test,
        'test_predictions': y_pred,
        'test_predictions_raw': y_pred_raw,
    }

if __name__ == '__main__':
    print("モデル学習を開始します（レース条件ごと）...")

    # 学習データファイルを取得
    training_files = [
        f for f in os.listdir('.')
        if f.startswith('training_data_')
        and f.endswith(('_condition.pkl', '_other.pkl'))
    ]

    print(f"Found {len(training_files)} training data files")

    all_results = []

    for filename in training_files:
        # ファイル名からレース条件を抽出
        # 例: training_data_東京_芝_1200m.pkl
        match = re.fullmatch(
            r'training_data_(.+)_(芝|ダート)_(\d+)m_(condition|other)\.pkl',
            filename,
        )
        if match:
            course, surface, distance, model_group = match.groups()

            print(
                f"\n[{len(all_results)+1}/{len(training_files)}] "
                f"{course} {surface} {distance}m ({model_group}):"
            )

            result = train_model_by_condition(course, distance, surface, model_group)
            if result:
                all_results.append(result)
                evaluation = result['evaluation']
                print(
                    f"  Test actual/predicted top-3 rate: "
                    f"{evaluation['test_actual_top3_rate']:.4f}/"
                    f"{evaluation['test_mean_predicted_probability']:.4f}"
                )

    if all_results:
        test_targets = np.concatenate([result['test_targets'] for result in all_results])
        test_predictions = np.concatenate(
            [result['test_predictions'] for result in all_results]
        )
        print(
            "\n=== 全モデルの時系列テスト集計（サンプル加重） ===\n"
            f"Test samples: {len(test_targets)}\n"
            f"Actual top-3 rate: {np.mean(test_targets):.4f}\n"
            f"Mean predicted probability: {np.mean(test_predictions):.4f}\n"
            f"LogLoss: {log_loss(test_targets, test_predictions, labels=[0, 1]):.4f}\n"
            f"Brier score: {brier_score_loss(test_targets, test_predictions):.4f}"
        )

    train_promotion_second_context_model(training_files)

    # 特徴量重要度を集計して出力
    print("\n=== 特徴量重要度集計 ===")

    # 各モデルの重要度を個別に保存
    os.makedirs('feature_importance', exist_ok=True)
    for result in all_results:
        model_name = f"{result['course']}_{result['surface']}_{result['distance']}m_{result['model_group']}"
        importance = result['feature_importance']
        sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

        with open(f'feature_importance/{model_name}.txt', 'w', encoding='utf-8') as f:
            f.write(f"=== {model_name} 特徴量重要度 ===\n\n")
            for feature, importance_value in sorted_importance:
                f.write(f"{feature}: {importance_value:.4f}\n")

    # 全レース条件で特徴量重要度を集計
    aggregated_importance = {}
    for result in all_results:
        for feature, importance in result['feature_importance'].items():
            if feature not in aggregated_importance:
                aggregated_importance[feature] = []
            aggregated_importance[feature].append(importance)

    # 平均重要度を計算
    avg_importance = {}
    for feature, importances in aggregated_importance.items():
        avg_importance[feature] = np.mean(importances)

    # ソートして出力
    sorted_importance = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)

    print("\n=== 全レース条件の平均特徴量重要度（Top 20）===")
    for feature, importance in sorted_importance[:20]:
        print(f"{feature}: {importance:.4f}")

    # 特徴量重要度をファイルに保存
    with open('feature_importance_by_condition.txt', 'w', encoding='utf-8') as f:
        f.write("=== 全レース条件の平均特徴量重要度（Top 20）===\n\n")
        for feature, importance in sorted_importance[:20]:
            f.write(f"{feature}: {importance:.4f}\n")

    print("\n=== モデル学習完了 ===")
    print(f"Total models trained: {len(all_results)}")
    print("Feature importance saved to: feature_importance_by_condition.txt")
    print("Individual model importance saved to: feature_importance/ directory")
