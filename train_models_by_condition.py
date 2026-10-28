import os
import pickle
import re
import lightgbm as lgb
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from feature_engineering import NULL_AS_NAN_FEATURES

def prepare_features_for_model(features_list):
    """特徴量のリストをモデル用に前処理"""
    if not features_list:
        return None, None

    # カラム名を取得
    feature_columns = list(features_list[0].keys())

    # 不要なカラムを削除
    cols_to_drop = [
        'horse_id', 'last_jockey',
        'last_popularity',  # 人気系（削除）
        'avg_popularity',   # 人気系（削除）
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

def train_model_by_condition(course, distance, surface, model_group):
    """特定のレース条件のモデルを学習"""
    filename = f"training_data_{course}_{surface}_{distance}m_{model_group}.pkl"

    if not os.path.exists(filename):
        print(f"  Skipped: {filename} not found")
        return None

    # 学習データを読み込み
    with open(filename, 'rb') as f:
        data = pickle.load(f)

    all_features = data['features']
    all_targets = data['targets']

    if len(all_features) < 10 or len(np.unique(all_targets)) < 2:
        print(f"  Skipped: No data in {filename}")
        return None

    print(f"  Training {len(all_features)} samples...")

    # 特徴量を前処理
    X, feature_columns = prepare_features_for_model(all_features)
    y = np.array(all_targets)

    # データ分割
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # LightGBMモデル学習
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

    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[test_data],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)]
    )

    # 評価
    y_pred = model.predict(X_test, num_iteration=model.best_iteration)
    y_pred_binary = (y_pred >= 0.5).astype(int)

    accuracy = accuracy_score(y_test, y_pred_binary)
    precision = precision_score(y_test, y_pred_binary, zero_division=0)
    recall = recall_score(y_test, y_pred_binary, zero_division=0)
    auc = roc_auc_score(y_test, y_pred) if len(np.unique(y_test)) > 1 else 0

    print(f"  Accuracy: {accuracy:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}, AUC: {auc:.4f}")

    # 特徴量重要度
    importance = model.feature_importance(importance_type='gain')
    feature_importance = dict(zip(feature_columns, importance))

    # モデルを保存
    model_filename = f"model_{course}_{surface}_{distance}m_{model_group}.pkl"
    with open(model_filename, 'wb') as f:
        pickle.dump({
            'model': model,
            'feature_columns': feature_columns,
            'feature_importance': feature_importance
        }, f)

    print(f"  Saved: {model_filename}")

    return {
        'course': course,
        'distance': distance,
        'surface': surface,
        'model_group': model_group,
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'auc': auc,
        'feature_importance': feature_importance
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

    # 特徴量重要度を集計して出力
    print("\n=== 特徴量重要度集計 ===")

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
