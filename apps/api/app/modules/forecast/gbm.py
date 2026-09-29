"""A small, deterministic gradient-boosted regression-tree model in pure Python.

Squared-error boosting with depth-limited trees. Features are pre-binned into at most
``max_bins`` quantile thresholds (histogram splits); there is no row or feature sampling,
so the same data and parameters always produce the same trees. Serialisable to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

Node = dict[str, Any]  # {"leaf": v} or {"f": i, "t": threshold, "l": Node, "r": Node}


@dataclass(frozen=True)
class GBMParams:
    n_estimators: int = 60
    learning_rate: float = 0.12
    max_depth: int = 3
    min_samples_leaf: int = 40
    max_bins: int = 16


def _thresholds(values: list[float], max_bins: int) -> list[float]:
    uniq = sorted(set(values))
    if len(uniq) <= 1:
        return []
    if len(uniq) <= max_bins:
        return [(a + b) / 2 for a, b in pairwise(uniq)]
    ordered = sorted(values)
    n = len(ordered)
    cuts = {ordered[min(n - 1, (n * k) // max_bins)] for k in range(1, max_bins)}
    return sorted(cuts)


def _bin(value: float, thresholds: list[float]) -> int:
    lo, hi = 0, len(thresholds)
    while lo < hi:  # first threshold >= value  → bin index (value <= t goes left)
        mid = (lo + hi) // 2
        if value <= thresholds[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


@dataclass
class GradientBoostedTrees:
    params: GBMParams = field(default_factory=GBMParams)
    base: float = 0.0
    trees: list[Node] = field(default_factory=list)
    feature_names: tuple[str, ...] = ()

    # ------------------------------------------------------------------ training

    def fit(self, X: list[list[float]], y: list[float], feature_names: tuple[str, ...]) -> None:
        if not X or len(X) != len(y):
            raise ValueError("X and y must be non-empty and the same length")
        p = self.params
        self.feature_names = feature_names
        n_feat = len(X[0])
        thresholds = [_thresholds([row[j] for row in X], p.max_bins) for j in range(n_feat)]
        binned = [[_bin(row[j], thresholds[j]) for j in range(n_feat)] for row in X]
        self.base = sum(y) / len(y)
        pred = [self.base] * len(y)
        self.trees = []
        for _ in range(p.n_estimators):
            residual = [yi - pi for yi, pi in zip(y, pred, strict=True)]
            tree = self._build(list(range(len(y))), residual, binned, thresholds, depth=0)
            self.trees.append(tree)
            for i, row in enumerate(X):
                pred[i] += p.learning_rate * _eval(tree, row)

    def _build(
        self,
        idx: list[int],
        g: list[float],
        binned: list[list[int]],
        thresholds: list[list[float]],
        depth: int,
    ) -> Node:
        p = self.params
        total = sum(g[i] for i in idx)
        n = len(idx)
        if depth >= p.max_depth or n < 2 * p.min_samples_leaf:
            return {"leaf": total / n}
        best: tuple[float, int, int] | None = None  # (gain, feature, bin)
        parent_score = total * total / n
        for j, th in enumerate(thresholds):
            if not th:
                continue
            sums = [0.0] * (len(th) + 1)
            counts = [0] * (len(th) + 1)
            for i in idx:
                b = binned[i][j]
                sums[b] += g[i]
                counts[b] += 1
            left_sum, left_n = 0.0, 0
            for b in range(len(th)):
                left_sum += sums[b]
                left_n += counts[b]
                right_n = n - left_n
                if left_n < p.min_samples_leaf or right_n < p.min_samples_leaf:
                    continue
                right_sum = total - left_sum
                gain = left_sum * left_sum / left_n + right_sum * right_sum / right_n - parent_score
                if best is None or gain > best[0] + 1e-12:
                    best = (gain, j, b)
        if best is None or best[0] <= 1e-12:
            return {"leaf": total / n}
        _, j, b = best
        left = [i for i in idx if binned[i][j] <= b]
        right = [i for i in idx if binned[i][j] > b]
        return {
            "f": j,
            "t": thresholds[j][b],
            "l": self._build(left, g, binned, thresholds, depth + 1),
            "r": self._build(right, g, binned, thresholds, depth + 1),
        }

    # ------------------------------------------------------------------ inference

    def predict_one(self, row: list[float]) -> float:
        return self.base + self.params.learning_rate * sum(_eval(t, row) for t in self.trees)

    def predict(self, X: list[list[float]]) -> list[float]:
        return [self.predict_one(r) for r in X]

    def to_dict(self) -> dict[str, Any]:
        p = self.params
        return {
            "params": {
                "n_estimators": p.n_estimators,
                "learning_rate": p.learning_rate,
                "max_depth": p.max_depth,
                "min_samples_leaf": p.min_samples_leaf,
                "max_bins": p.max_bins,
            },
            "base": self.base,
            "features": list(self.feature_names),
            "trees": self.trees,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GradientBoostedTrees:
        return cls(
            params=GBMParams(**data["params"]),
            base=float(data["base"]),
            trees=list(data["trees"]),
            feature_names=tuple(data["features"]),
        )


def _eval(node: Node, row: list[float]) -> float:
    while "leaf" not in node:
        node = node["l"] if row[node["f"]] <= node["t"] else node["r"]
    return float(node["leaf"])
