import lightgbm as lgb
import numpy as np
import pickle

def prepare_features_for_training(all_features):
    """
    学習用に特徴量を前処理
    
    Args:
        all_features: 特徴量の辞書のリスト
    
    Returns:
        前処理済みの特徴量（numpy array）と特徴量名のリスト
    """
    # 不要なカラムを削除
    cols_to_drop = ['horse_id', 'last_jockey']  # horse_idは識別子、last_jockeyはカテゴリ変数（今回は除外）
    
    # 特徴量名を取得（最初のサンプルから）
    if not all_features:
        return np.array([]), []
    
    feature_names = [k for k in all_features[0].keys() if k not in cols_to_drop]
    
    # numpy arrayに変換
    X = []
    for features in all_features:
        row = []
        for name in feature_names:
            value = features.get(name)
            if value is None:
                row.append(0.0)
            else:
                row.append(float(value))
        X.append(row)
    
    return np.array(X), feature_names

def train_test_split_manual(X, y, test_size=0.2, random_state=42):
    """sklearnを使わずにtrain_test_splitを実装"""
    np.random.seed(random_state)
    n_samples = len(X)
    n_test = int(n_samples * test_size)
    indices = np.random.permutation(n_samples)
    
    test_indices = indices[:n_test]
    train_indices = indices[n_test:]
    
    return X[train_indices], X[test_indices], y[train_indices], y[test_indices]

def train_lightgbm(X_train, y_train, X_test, y_test):
    """
    LightGBMでモデルを学習
    
    Args:
        X_train: 学習用特徴量（numpy array）
        y_train: 学習用目的変数（numpy array）
        X_test: 検証用特徴量（numpy array）
        y_test: 検証用目的変数（numpy array）
    
    Returns:
        学習済みモデル
    """
    # LightGBM用データセット
    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)
    
    # パラメータ設定
    params = {
        'objective': 'binary',
        'metric': ['binary_logloss', 'auc'],
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'random_state': 42
    }
    
    print("LightGBM学習を開始...")
    
    # 学習
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, test_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=100)
        ]
    )
    
    print(f"学習完了（最適ラウンド: {model.num_trees()}）")
    
    return model

def accuracy_score_manual(y_true, y_pred):
    """正解率を計算"""
    return np.mean(y_true == y_pred)

def precision_score_manual(y_true, y_pred):
    """適合率を計算"""
    tp = np.sum((y_true == 1) & (y_pred == 1))
    fp = np.sum((y_true == 0) & (y_pred == 1))
    if tp + fp == 0:
        return 0
    return tp / (tp + fp)

def recall_score_manual(y_true, y_pred):
    """再現率を計算"""
    tp = np.sum((y_true == 1) & (y_pred == 1))
    fn = np.sum((y_true == 1) & (y_pred == 0))
    if tp + fn == 0:
        return 0
    return tp / (tp + fn)

def auc_score_manual(y_true, y_pred_proba):
    """AUCを計算（簡易版）"""
    # ソート
    indices = np.argsort(y_pred_proba)[::-1]
    y_true_sorted = y_true[indices]
    
    # 正例の数
    n_pos = np.sum(y_true)
    n_neg = len(y_true) - n_pos
    
    if n_pos == 0 or n_neg == 0:
        return 0.5
    
    # AUC計算
    auc = 0
    for i in range(len(y_true_sorted)):
        if y_true_sorted[i] == 1:
            auc += np.sum(y_true_sorted[i+1:] == 0)
    
    return auc / (n_pos * n_neg)

def evaluate_model(model, X_test, y_test):
    """
    モデルの評価
    
    Args:
        model: 学習済みモデル
        X_test: 検証用特徴量（numpy array）
        y_test: 検証用目的変数（numpy array）
    """
    # 予測
    y_pred_proba = model.predict(X_test, num_iteration=model.best_iteration)
    y_pred = (y_pred_proba >= 0.5).astype(int)
    
    # 評価指標
    accuracy = accuracy_score_manual(y_test, y_pred)
    precision = precision_score_manual(y_test, y_pred)
    recall = recall_score_manual(y_test, y_pred)
    auc = auc_score_manual(y_test, y_pred_proba)
    
    print("\n=== Model Evaluation ===")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    print(f"AUC: {auc:.4f}")
    
    # 閾値0.3での評価（競馬では3着以内率30%前後なので）
    y_pred_03 = (y_pred_proba >= 0.3).astype(int)
    precision_03 = precision_score_manual(y_test, y_pred_03)
    recall_03 = recall_score_manual(y_test, y_pred_03)
    print(f"\nThreshold 0.3:")
    print(f"Precision: {precision_03:.4f}")
    print(f"Recall: {recall_03:.4f}")
    
    return {
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'auc': auc
    }

def plot_feature_importance(model, feature_names, output_path='feature_importance.txt'):
    """
    特徴量重要度をテキストで出力
    
    Args:
        model: 学習済みモデル
        feature_names: 特徴量名のリスト
        output_path: 出力ファイルパス
    """
    importance = model.feature_importance(importance_type='gain')
    
    # 特徴量と重要度をペアにしてソート
    feature_importance = list(zip(feature_names, importance))
    feature_importance.sort(key=lambda x: x[1], reverse=True)
    
    # 上位20件を表示
    top_features = feature_importance[:20]
    
    # テキストファイルとして保存
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("Feature Importance (Top 20)\n")
        f.write("=" * 50 + "\n")
        for feature, imp in top_features:
            f.write(f"{feature}: {imp:.4f}\n")
    
    print("\nFeature importance saved to feature_importance.txt")

def save_model(model, output_path='model.pkl'):
    """モデルを保存"""
    with open(output_path, 'wb') as f:
        pickle.dump(model, f)
    print(f"モデルを保存: {output_path}")

def load_model(input_path='model.pkl'):
    """モデルを読み込み"""
    with open(input_path, 'rb') as f:
        model = pickle.load(f)
    return model

def main():
    """メイン処理"""
    print("=== Model Training ===\n")
    
    # 学習データを読み込み
    try:
        with open('training_data.pkl', 'rb') as f:
            data = pickle.load(f)
        all_features = data['features']
        all_targets = data['targets']
        print(f"Training data loaded: {len(all_features)} samples")
    except FileNotFoundError:
        print("Training data not found. Please run prepare_training_data.py first")
        return
    
    # 特徴量の前処理
    X, feature_names = prepare_features_for_training(all_features)
    y = np.array(all_targets)
    
    print(f"Feature count: {len(feature_names)}")
    
    # データ分割（時系列ではなくランダム分割）
    X_train, X_test, y_train, y_test = train_test_split_manual(
        X, y, test_size=0.2, random_state=42
    )
    
    print(f"Training samples: {len(X_train)}")
    print(f"Test samples: {len(X_test)}")
    
    # モデル学習
    model = train_lightgbm(X_train, y_train, X_test, y_test)
    
    # モデル評価
    metrics = evaluate_model(model, X_test, y_test)
    
    # 特徴量重要度の可視化
    plot_feature_importance(model, feature_names)
    
    # モデル保存
    save_model(model)
    
    print("\n=== Training Complete ===")

if __name__ == '__main__':
    main()
