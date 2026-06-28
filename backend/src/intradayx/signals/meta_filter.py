"""Learned meta-filter — a second-pass model that scores whether a signal wins.

It is trained on historical signal outcomes (target-first vs. stop-first) and
uses the signal's own features plus the deterministic quality score.  Because
outcomes are forward-looking, the model must be retrained only on completed
trades and evaluated with time-series cross-validation to avoid lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from intradayx.domain.signals import Signal
from intradayx.signals.accuracy import LabeledSignal, SignalOutcome, label_outcomes
from intradayx.signals.snapshot import SIGNAL_SNAPSHOT_FEATURES, TREND_REGIME_SNAPSHOT_FEATURES


@dataclass(frozen=True, slots=True)
class FitResult:
    cv_accuracy: float
    cv_precision: float
    cv_recall: float
    cv_roc_auc: float
    n_samples: int
    pos_rate: float
    feature_importance: list[tuple[str, float]] = field(default_factory=list)
    insufficient: bool = False
    reason: str = ""


# Features the meta-filter can learn from.  All are known at signal emission time.
_NUMERIC_FEATURES = tuple(
    dict.fromkeys(
        (
            "confidence",
            "quality_score",
            "entry",
            "stop",
            "target1",
            "target_dist",
            "stop_dist",
            "rr",
            "c_climax",
            "c_volume",
            "c_value_area",
            "c_poc",
            "c_vwap",
            "c_momentum",
            "c_breakout",
            "confluence",
            *SIGNAL_SNAPSHOT_FEATURES,
            *TREND_REGIME_SNAPSHOT_FEATURES,
        )
    )
)
_CATEGORICAL_FEATURES = ("kind", "side", "tod_bucket")


def _signal_to_row(s: Signal) -> dict[str, Any]:
    """Flatten a Signal into a meta-filter feature row."""
    target1 = s.targets[0] if s.targets else s.entry
    stop_dist = abs(s.entry - s.stop)
    target_dist = abs(target1 - s.entry)
    rr = target_dist / stop_dist if stop_dist > 1e-9 else 0.0
    snap = s.feature_snapshot or {}
    row: dict[str, Any] = {
        "confidence": s.confidence,
        "quality_score": s.quality_score,
        "entry": s.entry,
        "stop": s.stop,
        "target1": target1,
        "target_dist": target_dist,
        "stop_dist": stop_dist,
        "rr": rr,
        "kind": s.kind.value,
        "side": s.side.value,
        "tod_bucket": s.time_of_day_bucket,
        "confluence": snap.get("confluence", 0.0),
        "c_climax": snap.get("c_climax", 0.0),
        "c_volume": snap.get("c_volume", 0.0),
        "c_value_area": snap.get("c_value_area", 0.0),
        "c_poc": snap.get("c_poc", 0.0),
        "c_vwap": snap.get("c_vwap", 0.0),
        "c_momentum": snap.get("c_momentum", 0.0),
        "c_breakout": snap.get("c_breakout", 0.0),
    }
    for feature in (*SIGNAL_SNAPSHOT_FEATURES, *TREND_REGIME_SNAPSHOT_FEATURES):
        row[feature] = snap.get(feature, 0.0)
    return row


class MetaFilter:
    """Trainable signal-quality model.

    Fitted on :class:`LabeledSignal` objects.  Once fitted, ``predict`` returns
    a 0-1 probability that a fresh signal's outcome will be ``TARGET``.
    """

    def __init__(self, min_samples: int = 50, pos_class_weight: float = 1.0) -> None:
        self.min_samples = min_samples
        self.pos_class_weight = pos_class_weight
        self._model: Any = None
        self._column_transformer: Any = None
        self._feature_names: list[str] = []

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    def fit(self, labeled: list[LabeledSignal]) -> FitResult:
        """Train on historical labeled signals."""
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder

        if len(labeled) < self.min_samples:
            return FitResult(
                cv_accuracy=0.0,
                cv_precision=0.0,
                cv_recall=0.0,
                cv_roc_auc=0.0,
                n_samples=len(labeled),
                pos_rate=0.0,
                insufficient=True,
                reason=f"need >= {self.min_samples} labeled signals (got {len(labeled)})",
            )

        rows = [_signal_to_row(x.signal) for x in labeled]
        y = np.array([1 if x.outcome is SignalOutcome.TARGET else 0 for x in labeled])
        if len(np.unique(y)) < 2:
            return FitResult(
                cv_accuracy=0.0,
                cv_precision=0.0,
                cv_recall=0.0,
                cv_roc_auc=0.0,
                n_samples=len(labeled),
                pos_rate=float(y.mean()),
                insufficient=True,
                reason="only one outcome class present",
            )

        import pandas as pd

        X = pd.DataFrame(rows)
        numeric = [c for c in _NUMERIC_FEATURES if c in X.columns]
        categorical = [c for c in _CATEGORICAL_FEATURES if c in X.columns]

        preprocessor = ColumnTransformer(
            [
                ("num", SimpleImputer(strategy="median"), numeric),
                ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
            ]
        )

        clf = HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.05,
            max_depth=4,
            class_weight="balanced" if self.pos_class_weight <= 0 else None,
            random_state=0,
        )

        pipe = Pipeline([("prep", preprocessor), ("clf", clf)])

        # Time-series CV: train on past, test on future.  No shuffle, no leakage.
        tscv = TimeSeriesSplit(n_splits=5)
        accs, precs, recs, aucs = [], [], [], []
        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
                continue
            pipe.fit(X_train, y_train)
            y_pred = pipe.predict(X_test)
            y_prob = pipe.predict_proba(X_test)[:, 1]
            accs.append(float(accuracy_score(y_test, y_pred)))
            precs.append(float(precision_score(y_test, y_pred, zero_division=0)))
            recs.append(float(recall_score(y_test, y_pred, zero_division=0)))
            aucs.append(float(roc_auc_score(y_test, y_prob)))

        if not accs:
            return FitResult(
                cv_accuracy=0.0,
                cv_precision=0.0,
                cv_recall=0.0,
                cv_roc_auc=0.0,
                n_samples=len(labeled),
                pos_rate=float(y.mean()),
                insufficient=True,
                reason="time-series CV produced no valid folds",
            )

        # Final fit on all data.
        pipe.fit(X, y)
        self._model = pipe
        self._feature_names = list(X.columns)

        # Feature importance via permutation on a small hold-out.
        importance = self._permutation_importance(X, y)
        return FitResult(
            cv_accuracy=float(np.mean(accs)),
            cv_precision=float(np.mean(precs)),
            cv_recall=float(np.mean(recs)),
            cv_roc_auc=float(np.mean(aucs)),
            n_samples=len(labeled),
            pos_rate=float(y.mean()),
            feature_importance=importance,
        )

    def _permutation_importance(
        self, X: Any, y: np.ndarray, n_repeats: int = 4
    ) -> list[tuple[str, float]]:
        """Fast permutation importance on the final model (causal, in-sample)."""
        from sklearn.metrics import log_loss

        if self._model is None:
            return []
        base_pred = self._model.predict_proba(X)
        base_loss = log_loss(y, base_pred)
        scores: dict[str, float] = {}
        rng = np.random.default_rng(0)
        for col in self._feature_names:
            losses = []
            for _ in range(n_repeats):
                X_perm = X.copy()
                X_perm[col] = rng.permutation(X_perm[col].values)
                perm_pred = self._model.predict_proba(X_perm)
                losses.append(log_loss(y, perm_pred))
            scores[col] = float(np.mean(losses) - base_loss)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked

    def predict(self, signals: list[Signal]) -> list[float]:
        """Return a 0-1 meta score for each signal."""
        if not self.is_fitted or not signals:
            return [None] * len(signals)  # type: ignore[return-value]
        import pandas as pd

        rows = [_signal_to_row(s) for s in signals]
        X = pd.DataFrame(rows)
        probs = self._model.predict_proba(X)[:, 1]
        return [float(p) for p in probs]

    def save(self, path: str | Any) -> None:
        """Persist a fitted filter with joblib."""
        import joblib

        joblib.dump(self, path)

    @classmethod
    def load(cls, path: str | Any) -> MetaFilter | None:
        """Load a joblib-serialized MetaFilter, or None if the file is missing."""
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return None
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required to load a meta-filter") from exc
        obj = joblib.load(p)
        if isinstance(obj, cls):
            return obj
        return None


def train_meta_filter(
    signals: list[Signal],
    bars: Any,
    *,
    max_hold_bars: int = 24,
    min_samples: int = 50,
) -> tuple[MetaFilter, FitResult]:
    """Convenience: label historical signals and fit a MetaFilter."""
    labeled = label_outcomes(signals, bars, max_hold_bars=max_hold_bars)
    mf = MetaFilter(min_samples=min_samples)
    result = mf.fit(labeled)
    return mf, result


def train_meta_filter_multi(
    samples: list[tuple[list[Signal], Any]],
    *,
    max_hold_bars: int = 24,
    min_samples: int = 50,
) -> tuple[MetaFilter, FitResult]:
    """Pool labeled signals across symbols and fit ONE MetaFilter.

    Each ``(signals, bars)`` pair is labeled against its own bars (outcomes are
    per-symbol — target-first vs stop-first), then the labeled sets are unioned.
    One symbol rarely clears ``min_samples``; a universe does, which is what
    gives the learned layer the statistical power to validate (and to judge
    whether a feature like the VIX regime actually earns its place).
    """
    labeled: list[LabeledSignal] = []
    for signals, bars in samples:
        labeled.extend(label_outcomes(signals, bars, max_hold_bars=max_hold_bars))
    mf = MetaFilter(min_samples=min_samples)
    result = mf.fit(labeled)
    return mf, result
