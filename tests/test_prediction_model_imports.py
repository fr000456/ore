import subprocess
import sys
import unittest


class PredictionModelImportTests(unittest.TestCase):
    def test_importing_prediction_modules_does_not_break_sklearn_pandas(self):
        script = """
import dirt_maiden_model
import backtest_race
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

model = make_pipeline(
    StandardScaler(),
    LogisticRegression(),
)
model.fit(np.asarray([[0.0], [1.0], [2.0], [3.0]]), [0, 0, 1, 1])
model.predict_proba(np.asarray([[1.5]]))
"""
        result = subprocess.run(
            [sys.executable, '-c', script],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
