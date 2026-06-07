"""The "self-learning culprit" model — LightGBM + SHAP, validated leak-free.

HONEST SCOPE: on free price/volume data the target is "is a significant
(volatility-scaled) move imminent?" and SHAP shows *what the model keys on* —
NOT what caused the move (correlation != causation; see MODEL_ATTRIBUTION_CAVEAT).
With ~tens–hundreds of labelled samples and no internals/options, treat this as
exploratory description, not a tradable signal. Real attribution power arrives
with the paid-data phases (7–9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from intradayx.attribution.labeling import DEFAULT_MAX_HOLD, triple_barrier_labels
from intradayx.attribution.validation import purged_kfold
from intradayx.features.pipeline import FeatureSet

# Numeric, strictly-causal feature columns the model learns from.
ML_FEATURE_COLUMNS: tuple[str, ...] = (
    "rvol",
    "rvol_day",
    "atr",
    "dist_to_prior_poc",
    "gap_pct",
    "gap_atr",
    "range_atr",
    "upper_wick_frac",
    "lower_wick_frac",
    "close_position",
    "climax_up_score",
    "climax_down_score",
    "minutes_from_open",
)

MIN_SAMPLES = 50


@dataclass(frozen=True, slots=True)
class LearnResult:
    n_samples: int
    positive_rate: float  # share of "significant move imminent" labels
    cv_macro_f1: float
    cv_folds: int
    shap_top: list[tuple[str, float]]  # (feature, mean |SHAP|), descending
    data_completeness: float
    insufficient: bool = False
    reason: str = ""

    extra: dict[str, float] = field(default_factory=dict)


def build_xy(fs: FeatureSet) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build (X, y, feature_cols). Target = significant move imminent (|tb|==1)."""
    df = fs.df
    cols = [c for c in ML_FEATURE_COLUMNS if c in df.columns]
    labels = triple_barrier_labels(df)
    feat = df.select(cols).to_numpy()

    finite = np.isfinite(feat).all(axis=1)
    labelled = np.isfinite(labels)
    mask = finite & labelled
    x = feat[mask]
    y = (np.abs(labels[mask]) == 1).astype(int)
    return x, y, cols


def train_and_evaluate(fs: FeatureSet, *, n_splits: int = 5) -> LearnResult:
    x, y, cols = build_xy(fs)
    n = len(y)
    if n < MIN_SAMPLES or len(np.unique(y)) < 2:
        return LearnResult(
            n_samples=n,
            positive_rate=float(y.mean()) if n else 0.0,
            cv_macro_f1=0.0,
            cv_folds=0,
            shap_top=[],
            data_completeness=fs.data_completeness,
            insufficient=True,
            reason=f"only {n} labelled samples (need >= {MIN_SAMPLES} with both classes)",
        )

    import lightgbm as lgb
    from sklearn.metrics import f1_score

    def _model() -> lgb.LGBMClassifier:
        return lgb.LGBMClassifier(
            n_estimators=150,
            num_leaves=15,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            verbosity=-1,
        )

    f1s: list[float] = []
    for train_idx, test_idx in purged_kfold(
        n, n_splits=n_splits, label_horizon=DEFAULT_MAX_HOLD, embargo=5
    ):
        if len(np.unique(y[train_idx])) < 2 or test_idx.size == 0:
            continue
        m = _model()
        m.fit(x[train_idx], y[train_idx])
        f1s.append(float(f1_score(y[test_idx], m.predict(x[test_idx]), average="macro")))

    final = _model()
    final.fit(x, y)
    shap_top = _shap_importance(final, x, cols)

    return LearnResult(
        n_samples=n,
        positive_rate=float(y.mean()),
        cv_macro_f1=float(np.mean(f1s)) if f1s else 0.0,
        cv_folds=len(f1s),
        shap_top=shap_top,
        data_completeness=fs.data_completeness,
    )


def _shap_importance(model: object, x: np.ndarray, cols: list[str]) -> list[tuple[str, float]]:
    """Mean |SHAP| per feature using INTERVENTIONAL perturbation.

    The default `tree_path_dependent` mis-credits correlated features; the
    interventional mode handles correlation per causal rules (see AI_LANDMINES).
    """
    import shap

    rng = np.random.default_rng(0)
    sample_n = min(200, len(x))
    sample = x[rng.choice(len(x), size=sample_n, replace=False)]
    background = sample[: min(100, sample_n)]
    explainer = shap.TreeExplainer(
        model, data=background, feature_perturbation="interventional"
    )
    values = explainer.shap_values(sample)
    arr = np.abs(np.asarray(values))
    # Average every axis except the feature axis (last), handling binary/multiclass shapes.
    per_feature = arr.reshape(-1, arr.shape[-1]).mean(axis=0)
    pairs = zip(cols, per_feature.tolist(), strict=True)
    ranked = sorted(pairs, key=lambda kv: kv[1], reverse=True)
    return ranked[:8]
