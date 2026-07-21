from __future__ import annotations


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def normalize(value: float, scale: float) -> float:
    if scale <= 0:
        raise ValueError("normalization scale must be positive")
    return clamp(value / scale)

