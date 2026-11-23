"""Simulated federated participants.

Each ``FederatedClient`` owns its private data partition. Raw data never
leaves the object: the coordinator only receives the model update (delta),
the local sample count and local training statistics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import torch
from torch import nn

from core.attack_simulator import AttackConfig, flip_labels, manipulate_update
from datasets.prepare_data import ClientPartition
from models.neural_network import create_model, flatten, get_params, set_params, unflatten


@dataclass
class LocalTrainingConfig:
    epochs: int = 2
    batch_size: int = 16
    learning_rate: float = 1e-3


@dataclass
class ClientUpdate:
    client: str
    delta: np.ndarray
    num_samples: int
    epoch_losses: list[float]
    local_accuracy: float
    is_malicious: bool = False          # ground truth, used ONLY for evaluation reporting
    attack_details: dict = field(default_factory=dict)


ProgressFn = Callable[[str, int, int], None]  # (client, epoch_done, total_epochs)


class FederatedClient:
    def __init__(self, partition: ClientPartition, client_index: int):
        self.partition = partition
        self.index = client_index

    @property
    def name(self) -> str:
        return self.partition.name

    @property
    def num_samples(self) -> int:
        return self.partition.num_samples

    def local_train(
        self,
        global_vector: np.ndarray,
        template,
        cfg: LocalTrainingConfig,
        seed: int,
        attack: Optional[AttackConfig] = None,
        progress: Optional[ProgressFn] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> ClientUpdate:
        torch.manual_seed(seed)
        model = create_model(seed)
        set_params(model, unflatten(global_vector, template))

        X = self.partition.X
        y = self.partition.y
        malicious = attack is not None and attack.applies_to(self.name)
        details: dict = {}
        if malicious and attack.flips_labels:
            y, flipped = flip_labels(y, attack.flip_rate, seed)
            details["labels_flipped"] = int(len(flipped))

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.long)
        opt = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)
        loss_fn = nn.CrossEntropyLoss()
        gen = torch.Generator().manual_seed(seed)

        epoch_losses: list[float] = []
        model.train()
        for epoch in range(cfg.epochs):
            if should_stop and should_stop():
                raise InterruptedError("training stopped")
            perm = torch.randperm(len(y_t), generator=gen)
            total, count = 0.0, 0
            for start in range(0, len(perm), cfg.batch_size):
                b = perm[start:start + cfg.batch_size]
                opt.zero_grad()
                loss = loss_fn(model(X_t[b]), y_t[b])
                loss.backward()
                opt.step()
                total += float(loss.item()) * len(b)
                count += len(b)
            epoch_losses.append(total / max(count, 1))
            if progress:
                progress(self.name, epoch + 1, cfg.epochs)

        model.eval()
        with torch.no_grad():
            # local accuracy against the labels the client actually trained on
            local_acc = float((model(X_t).argmax(1) == y_t).float().mean().item())

        delta = flatten(get_params(model)) - np.asarray(global_vector, dtype=np.float32)
        if malicious:
            delta = manipulate_update(delta, attack)
            details.update({"attack_type": attack.attack_type, "strength": attack.strength,
                            "flip_rate": attack.flip_rate})
        return ClientUpdate(
            client=self.name,
            delta=delta.astype(np.float32),
            num_samples=self.num_samples,
            epoch_losses=epoch_losses,
            local_accuracy=local_acc,
            is_malicious=malicious,
            attack_details=details,
        )
