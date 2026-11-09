"""Runtime helpers shared by local separation backends."""

from __future__ import annotations

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, TypeVar

from domain import ProgressReporter

ResultT = TypeVar("ResultT")


def run_with_heartbeat(
    operation: Callable[[], ResultT],
    progress_reporter: ProgressReporter,
    start: float,
    end: float,
    *,
    thread_name: str,
    message: str = "Separating audio",
    time_constant_seconds: float = 75.0,
) -> ResultT:
    """Runs a step without progress callbacks while reporting an estimated advance.

    The estimate reaches 95% of the [start, end] range after three time
    constants; callers that can predict the step's length pass a third of it.
    """
    time_constant = max(1.0, time_constant_seconds)
    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name) as executor:
        future = executor.submit(operation)
        while True:
            try:
                return future.result(timeout=1.5)
            except FutureTimeout:
                elapsed = time.monotonic() - started_at
                fraction = 1 - math.exp(-elapsed / time_constant)
                current_progress = min(end, start + (end - start) * fraction)
                progress_reporter.report(round(current_progress, 3), message)


DEVICE_OVERRIDE_VARIABLE = "STEM_STUDIO_TORCH_DEVICE"


def device_override() -> str | None:
    """"cpu", "cuda" or "mps" from STEM_STUDIO_TORCH_DEVICE, to compare devices without a rebuild."""
    value = os.environ.get(DEVICE_OVERRIDE_VARIABLE, "").strip().lower()
    return value if value in ("cpu", "cuda", "mps") else None


def preferred_torch_device() -> str:
    override = device_override()
    if override:
        return override
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def release_accelerator_memory(device: str) -> None:
    """Return cached allocator memory to the GPU driver after a large inference."""
    try:
        import torch

        if device == "cuda":
            torch.cuda.empty_cache()
        elif device == "mps":
            torch.mps.empty_cache()
    except Exception:
        pass
