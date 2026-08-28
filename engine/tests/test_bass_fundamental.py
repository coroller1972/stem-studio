from __future__ import annotations

import math
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from bass_fundamental import PyinFundamentalSettings, estimate_pyin_fundamental


class PyinFundamentalTests(unittest.TestCase):
    @patch("librosa.times_like")
    @patch("librosa.pyin")
    @patch("librosa.load")
    def test_aligns_only_confident_voiced_fundamentals(
        self,
        load,
        pyin,
        times_like,
    ) -> None:
        load.return_value = (np.zeros(100), 22_050)
        pyin.return_value = (
            np.array([math.nan, 30.8677, 55.0]),
            np.array([False, True, True]),
            np.array([0.1, 0.9, 0.8]),
        )
        times_like.return_value = np.array([0.0, 0.01, 0.02])

        track = estimate_pyin_fundamental(
            Path("bass.wav"),
            [0.0, 0.011, 0.02],
            23,
            67,
            PyinFundamentalSettings(minimum_voiced_probability=0.35),
        )

        self.assertTrue(math.isnan(track.midi[0]))
        self.assertAlmostEqual(track.midi[1], 23.0, places=3)
        self.assertAlmostEqual(track.midi[2], 33.0, places=3)
        self.assertEqual(track.confidence, (0.0, 0.9, 0.8))


if __name__ == "__main__":
    unittest.main()
