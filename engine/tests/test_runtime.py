from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs_roformer_separator import bs_roformer_device
from runtime import device_override, preferred_torch_device, run_with_heartbeat


class DeviceSelectionTest(unittest.TestCase):
    def test_high_quality_leaves_only_the_apple_gpu_for_the_cpu(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STEM_STUDIO_TORCH_DEVICE", None)
            with patch("bs_roformer_separator.preferred_torch_device", return_value="mps"):
                self.assertEqual(bs_roformer_device(), "cpu")
            with patch("bs_roformer_separator.preferred_torch_device", return_value="cuda"):
                self.assertEqual(bs_roformer_device(), "cuda")
            with patch("bs_roformer_separator.preferred_torch_device", return_value="cpu"):
                self.assertEqual(bs_roformer_device(), "cpu")
        with patch.dict(os.environ, {"STEM_STUDIO_TORCH_DEVICE": " MPS "}):
            self.assertEqual(bs_roformer_device(), "mps")

    def test_the_override_also_steers_the_standard_profile_and_ignores_typos(self) -> None:
        with patch.dict(os.environ, {"STEM_STUDIO_TORCH_DEVICE": "cpu"}):
            self.assertEqual(preferred_torch_device(), "cpu")
        with patch.dict(os.environ, {"STEM_STUDIO_TORCH_DEVICE": "gpu"}):
            self.assertIsNone(device_override())


class HeartbeatTest(unittest.TestCase):
    def test_estimated_progress_follows_the_given_time_constant(self) -> None:
        reports: list[float] = []

        class Recorder:
            def report(self, progress: float, message: str) -> None:
                reports.append(progress)

        clock = iter([0.0, 30.0, 300.0])
        with patch("runtime.time.monotonic", lambda: next(clock)):
            calls = {"count": 0}

            def slow_result(self, timeout=None):
                calls["count"] += 1
                if calls["count"] < 3:
                    from concurrent.futures import TimeoutError as FutureTimeout

                    raise FutureTimeout()
                return "done"

            with patch("concurrent.futures.Future.result", slow_result):
                result = run_with_heartbeat(
                    lambda: time.sleep(0), Recorder(), 0.1, 0.8, thread_name="test", time_constant_seconds=100
                )
        self.assertEqual(result, "done")
        # 30 s into a 100 s time constant: 26% of the range; 300 s: 95%.
        self.assertEqual(reports, [round(0.1 + 0.7 * (1 - 2.718281828 ** -0.3), 3), round(0.1 + 0.7 * (1 - 2.718281828 ** -3), 3)])


if __name__ == "__main__":
    unittest.main()
