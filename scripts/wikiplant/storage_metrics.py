from __future__ import annotations

from dataclasses import dataclass, field
import math
from statistics import median
from typing import Iterable

from .errors import ValidationError


@dataclass
class ProviderMetrics:
    """Content-free storage telemetry for one operation.

    Callers supply measured durations and byte counts at the provider boundary.
    Paths, queries, repository names, IDs, and payloads are deliberately absent
    so a sanitized benchmark cannot become a second copy of private wiki data.
    """

    provider: str
    operation_id: str
    calls: dict[str, int] = field(default_factory=dict)
    phase_latency_ms: dict[str, float] = field(default_factory=dict)
    bytes_read: int = 0
    bytes_written: int = 0
    conflicts: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        if self.provider not in {"google-drive", "github"}:
            raise ValidationError("metrics require a supported storage provider")
        if not self.operation_id or len(self.operation_id) > 256:
            raise ValidationError("metrics require a bounded operation ID")

    def record_call(
        self,
        action: str,
        *,
        duration_ms: float,
        bytes_read: int = 0,
        bytes_written: int = 0,
        conflict: bool = False,
        retry: bool = False,
    ) -> None:
        if not action or len(action) > 80 or any(ch.isspace() for ch in action):
            raise ValidationError("metric action must be a bounded identifier")
        if not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValidationError("metric duration must be finite and nonnegative")
        if type(bytes_read) is not int or bytes_read < 0 or type(bytes_written) is not int or bytes_written < 0:
            raise ValidationError("metric byte counts must be nonnegative integers")
        if type(conflict) is not bool or type(retry) is not bool:
            raise ValidationError("metric conflict/retry flags must be booleans")
        self.calls[action] = self.calls.get(action, 0) + 1
        self.phase_latency_ms[action] = self.phase_latency_ms.get(action, 0.0) + duration_ms
        self.bytes_read += bytes_read
        self.bytes_written += bytes_written
        self.conflicts += int(conflict)
        self.retries += int(retry)

    @property
    def total_latency_ms(self) -> float:
        return sum(self.phase_latency_ms.values())

    def sanitized(self) -> dict:
        return {
            "provider": self.provider,
            "calls": dict(sorted(self.calls.items())),
            "phase_latency_ms": {key: round(value, 3) for key, value in sorted(self.phase_latency_ms.items())},
            "total_latency_ms": round(self.total_latency_ms, 3),
            "bytes_read": self.bytes_read,
            "bytes_written": self.bytes_written,
            "conflicts": self.conflicts,
            "retries": self.retries,
        }


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValidationError("benchmark requires samples")
    if not 0 < percentile <= 1:
        raise ValidationError("percentile must be in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def summarize_benchmark(provider: str, workload: str, samples: Iterable[ProviderMetrics]) -> dict:
    values = list(samples)
    if not workload or len(workload) > 120:
        raise ValidationError("benchmark workload name is required")
    if not values or any(sample.provider != provider for sample in values):
        raise ValidationError("benchmark samples must belong to one provider")
    latencies = [sample.total_latency_ms for sample in values]
    return {
        "provider": provider,
        "workload": workload,
        "sample_count": len(values),
        "median_latency_ms": round(median(latencies), 3),
        "p95_latency_ms": round(_nearest_rank(latencies, 0.95), 3),
        "total_calls": sum(sum(sample.calls.values()) for sample in values),
        "total_bytes_read": sum(sample.bytes_read for sample in values),
        "total_bytes_written": sum(sample.bytes_written for sample in values),
        "conflicts": sum(sample.conflicts for sample in values),
        "retries": sum(sample.retries for sample in values),
    }
