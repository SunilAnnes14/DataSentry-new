"""Shared neural network and parameter (de)serialisation helpers.

Canonical serialisation format "DSv1" (used for all SHA-256 hashes that are
written to the blockchain, so anyone can reproduce them):

    b"DSv1"
    for each parameter in model.state_dict() order
      (fc1.weight, fc1.bias, fc2.weight, fc2.bias, fc3.weight, fc3.bias):
        uint32 LE  len(name_utf8)
        bytes      name_utf8
        uint32 LE  ndim
        uint32 LE  dim_i  (ndim times)
        float32 LE values in C (row-major) order

The hash of a *client update* is computed over the update delta
(local_params - global_params) in this format; the hash of a *global model*
is computed over the global parameters themselves.
"""
from __future__ import annotations

import hashlib
import struct
from collections import OrderedDict

import numpy as np
import torch
from torch import nn

INPUT_DIM = 30
NUM_CLASSES = 2


class DiagnosisNet(nn.Module):
    """30 -> 64 -> 32 -> 2 multilayer perceptron with ReLU activations."""

    def __init__(self, input_dim: int = INPUT_DIM, num_classes: int = NUM_CLASSES):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, num_classes)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        return self.fc3(x)


ParamDict = "OrderedDict[str, np.ndarray]"


def create_model(seed: int) -> DiagnosisNet:
    torch.manual_seed(seed)
    return DiagnosisNet()


def get_params(model: nn.Module) -> "OrderedDict[str, np.ndarray]":
    return OrderedDict((k, v.detach().cpu().numpy().astype(np.float32).copy()) for k, v in model.state_dict().items())


def set_params(model: nn.Module, params: "OrderedDict[str, np.ndarray]") -> None:
    state = OrderedDict((k, torch.tensor(np.asarray(v, dtype=np.float32))) for k, v in params.items())
    model.load_state_dict(state, strict=True)


def flatten(params: "OrderedDict[str, np.ndarray]") -> np.ndarray:
    return np.concatenate([np.asarray(v, dtype=np.float32).ravel() for v in params.values()])


def unflatten(vector: np.ndarray, template: "OrderedDict[str, np.ndarray]") -> "OrderedDict[str, np.ndarray]":
    vector = np.asarray(vector, dtype=np.float32)
    expected = sum(v.size for v in template.values())
    if vector.size != expected:
        raise ValueError(f"vector has {vector.size} values, expected {expected}")
    out: OrderedDict[str, np.ndarray] = OrderedDict()
    offset = 0
    for k, v in template.items():
        out[k] = vector[offset:offset + v.size].reshape(v.shape).copy()
        offset += v.size
    return out


def serialize_params(params: "OrderedDict[str, np.ndarray]") -> bytes:
    """Canonical DSv1 byte serialisation (see module docstring)."""
    chunks = [b"DSv1"]
    for name, arr in params.items():
        arr = np.ascontiguousarray(np.asarray(arr, dtype="<f4"))
        name_b = name.encode("utf-8")
        chunks.append(struct.pack("<I", len(name_b)))
        chunks.append(name_b)
        chunks.append(struct.pack("<I", arr.ndim))
        chunks.append(struct.pack(f"<{arr.ndim}I", *arr.shape))
        chunks.append(arr.tobytes(order="C"))
    return b"".join(chunks)


def hash_params(params: "OrderedDict[str, np.ndarray]") -> str:
    """SHA-256 hex digest (0x-prefixed, 32 bytes) of the canonical serialisation."""
    return "0x" + hashlib.sha256(serialize_params(params)).hexdigest()


def num_parameters(params: "OrderedDict[str, np.ndarray]") -> int:
    return int(sum(v.size for v in params.values()))
