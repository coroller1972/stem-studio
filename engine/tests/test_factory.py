from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs_roformer_separator import BSRoFormerSeparator
from demucs_separator import DemucsSeparator
from domain import StemSeparator
from errors import SeparationError
from factory import SeparatorFactory, create_separator
from registry import HIGH_PROFILE, STANDARD_PROFILE, SeparationProfile


class SeparatorFactoryTest(unittest.TestCase):
    def test_standard_profile_creates_demucs_separator(self) -> None:
        separator = create_separator(STANDARD_PROFILE)
        self.assertIsInstance(separator, DemucsSeparator)
        self.assertIsInstance(separator, StemSeparator)
        self.assertEqual(separator.model_id, "htdemucs")
        self.assertEqual(separator.profile_id, "standard")

    def test_unregistered_backend_has_user_facing_error(self) -> None:
        profile = SeparationProfile(
            id="experimental",
            label="Experimental",
            description="Test profile.",
            backend_id="missing",
            model_id="model",
        )
        with self.assertRaises(SeparationError) as raised:
            create_separator(profile)
        self.assertEqual(raised.exception.user_message, "Separation backend is unavailable.")

    def test_high_profile_creates_bs_roformer_separator(self) -> None:
        separator = create_separator(HIGH_PROFILE)
        self.assertIsInstance(separator, BSRoFormerSeparator)
        self.assertIsInstance(separator, StemSeparator)
        self.assertIn("musdb18hq", separator.model_id)

    def test_duplicate_backend_ids_are_rejected(self) -> None:
        builder = lambda profile, audio_io: create_separator(STANDARD_PROFILE)
        with self.assertRaises(ValueError):
            SeparatorFactory([("demucs", builder), ("demucs", builder)])


if __name__ == "__main__":
    unittest.main()
