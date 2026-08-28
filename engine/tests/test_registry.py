from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from registry import (
    DEFAULT_PROFILE_ID,
    HIGH_PROFILE,
    ProfileRegistry,
    STANDARD_PROFILE,
    UnknownProfileError,
    get_profile,
)


class ProfileRegistryTest(unittest.TestCase):
    def test_standard_profile_maps_to_current_demucs_model(self) -> None:
        profile = get_profile(DEFAULT_PROFILE_ID)
        self.assertEqual(profile.id, "standard")
        self.assertEqual(profile.backend_id, "demucs")
        self.assertEqual(profile.model_id, "htdemucs")

    def test_unknown_profile_has_an_explicit_error(self) -> None:
        with self.assertRaises(UnknownProfileError):
            get_profile("ultra")

    def test_high_profile_maps_to_four_stem_bs_roformer(self) -> None:
        profile = get_profile("high")
        self.assertEqual(profile, HIGH_PROFILE)
        self.assertEqual(profile.backend_id, "bs_roformer")
        self.assertIn("musdb18hq", profile.model_id)

    def test_duplicate_profile_ids_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProfileRegistry([STANDARD_PROFILE, STANDARD_PROFILE])


if __name__ == "__main__":
    unittest.main()
