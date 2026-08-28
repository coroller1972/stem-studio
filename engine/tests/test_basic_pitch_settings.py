import unittest

from basic_pitch_transcriber import (
    BASIC_PITCH_MODEL_ID,
    BasicPitchBassSettings,
    _midi_frequency,
)


class BasicPitchBassSettingsTests(unittest.TestCase):
    def test_balanced_profile_covers_low_b_of_a_five_string_bass(self) -> None:
        settings = BasicPitchBassSettings()
        self.assertEqual(settings.minimum_midi_pitch, 23)
        self.assertEqual(settings.maximum_midi_pitch, 67)
        self.assertGreaterEqual(settings.minimum_note_length_ms, 128)
        self.assertLess(settings.minimum_onset_note_length_ms, 100)
        self.assertFalse(settings.melodia_trick)

    def test_model_id_marks_the_monophonic_decoder(self) -> None:
        self.assertIn("monophonic", BASIC_PITCH_MODEL_ID)

    def test_midi_frequency_conversion(self) -> None:
        self.assertAlmostEqual(_midi_frequency(69), 440.0)
        self.assertAlmostEqual(_midi_frequency(23), 30.8677, places=3)


if __name__ == "__main__":
    unittest.main()
