"""Runtime helpers shared by local separation backends."""

from __future__ import annotations

import math
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
) -> ResultT:
    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name) as executor:
        future = executor.submit(operation)
        while True:
            try:
                return future.result(timeout=1.5)
            except FutureTimeout:
                elapsed = time.monotonic() - started_at
                fraction = 1 - math.exp(-elapsed / 75)
                current_progress = min(end, start + (end - start) * fraction)
                progress_reporter.report(round(current_progress, 3), message)


def preferred_torch_device() -> str:
    try:
        import torch

        return "mps" if torch.backends.mps.is_available() else "cpu"
    except Exception:
        return "cpu"
