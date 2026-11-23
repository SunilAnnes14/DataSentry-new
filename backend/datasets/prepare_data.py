"""Dataset loading, preprocessing and federated partitioning.

Uses the Breast Cancer Wisconsin (Diagnostic) dataset bundled with
scikit-learn (569 samples, 30 numeric features, 2 classes), so no network
download is required.

Split (all deterministic for a given seed):
    * 20 % stratified hold-out TEST set (never seen by clients or the detector)
    * 12 % of the remainder as a coordinator VALIDATION set, used by the
      security engine to measure the validation-loss impact of each update
    * the rest is partitioned across the four hospitals

Feature standardisation is fitted on the client training pool only.
Note: in a real deployment each hospital would standardise locally or use a
federated statistics protocol; fitting a shared scaler here is a simplification.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


@dataclass
class ClientPartition:
    name: str
    X: np.ndarray
    y: np.ndarray

    @property
    def num_samples(self) -> int:
        return int(len(self.y))

    def label_counts(self) -> dict[int, int]:
        return {int(c): int((self.y == c).sum()) for c in (0, 1)}


@dataclass
class FederatedDataset:
    clients: list[ClientPartition]
    X_val: np.ndarray
    y_val: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    feature_names: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)

    @property
    def X_train_all(self) -> np.ndarray:
        return np.concatenate([c.X for c in self.clients])

    @property
    def y_train_all(self) -> np.ndarray:
        return np.concatenate([c.y for c in self.clients])

    def summary(self) -> dict:
        return {
            "num_features": int(self.X_test.shape[1]),
            "classes": self.class_names,
            "test_samples": int(len(self.y_test)),
            "validation_samples": int(len(self.y_val)),
            "clients": [
                {"name": c.name, "samples": c.num_samples, "label_counts": c.label_counts()}
                for c in self.clients
            ],
        }


def partition_indices(
    y: np.ndarray,
    num_clients: int,
    seed: int,
    strategy: str = "dirichlet",
    alpha: float = 2.0,
    min_per_class: int = 5,
) -> list[np.ndarray]:
    """Split sample indices across clients.

    strategy="iid": shuffled equal split.
    strategy="dirichlet": label-skewed (non-IID) split. For each class the
    share each client receives is drawn from Dirichlet(alpha). Every client is
    guaranteed at least ``min_per_class`` samples of every class so local
    training is always possible.
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    if num_clients <= 0:
        raise ValueError("num_clients must be positive")
    if strategy == "iid":
        perm = rng.permutation(n)
        return [np.sort(p) for p in np.array_split(perm, num_clients)]
    if strategy != "dirichlet":
        raise ValueError(f"unknown partition strategy: {strategy}")

    parts: list[list[int]] = [[] for _ in range(num_clients)]
    for cls in np.unique(y):
        idx = rng.permutation(np.where(y == cls)[0])
        if len(idx) < num_clients * min_per_class:
            raise ValueError("not enough samples to satisfy min_per_class")
        # guaranteed minimum first, remaining samples by Dirichlet proportions
        for k in range(num_clients):
            parts[k].extend(idx[k * min_per_class:(k + 1) * min_per_class].tolist())
        rest = idx[num_clients * min_per_class:]
        props = rng.dirichlet(np.full(num_clients, alpha))
        cuts = (np.cumsum(props) * len(rest)).astype(int)[:-1]
        for k, chunk in enumerate(np.split(rest, cuts)):
            parts[k].extend(chunk.tolist())
    return [np.sort(np.array(p, dtype=int)) for p in parts]


def load_federated_dataset(
    client_names: list[str],
    seed: int = 42,
    strategy: str = "dirichlet",
    alpha: float = 2.0,
    test_size: float = 0.20,
    val_size: float = 0.12,
) -> FederatedDataset:
    raw = load_breast_cancer()
    X = raw.data.astype(np.float64)
    y = raw.target.astype(np.int64)

    X_pool, X_test, y_pool, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=seed
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_pool, y_pool, test_size=val_size, stratify=y_pool, random_state=seed
    )

    scaler = StandardScaler().fit(X_train)
    X_train = scaler.transform(X_train).astype(np.float32)
    X_val = scaler.transform(X_val).astype(np.float32)
    X_test = scaler.transform(X_test).astype(np.float32)

    parts = partition_indices(y_train, len(client_names), seed, strategy, alpha)
    clients = [ClientPartition(name, X_train[p], y_train[p]) for name, p in zip(client_names, parts)]
    return FederatedDataset(
        clients=clients,
        X_val=X_val,
        y_val=y_val,
        X_test=X_test,
        y_test=y_test,
        feature_names=list(raw.feature_names),
        class_names=list(raw.target_names),
    )
