import unittest

from gm_drums import general_midi_note, normalize_adtof_instrument, normalize_drum_instrument


class DrumMappingTests(unittest.TestCase):
    def test_maps_adtof_five_classes(self) -> None:
        self.assertEqual(normalize_adtof_instrument(35), "kick")
        self.assertEqual(normalize_adtof_instrument(38), "snare")
        self.assertEqual(normalize_adtof_instrument(42), "closed_hihat")
        self.assertEqual(normalize_adtof_instrument(47), "mid_tom")
        self.assertEqual(normalize_adtof_instrument(49), "crash")

    def test_maps_normalized_classes_to_general_midi(self) -> None:
        self.assertEqual(general_midi_note("kick"), 36)
        self.assertEqual(general_midi_note("snare"), 38)
        self.assertEqual(general_midi_note("closed_hihat"), 42)
        self.assertEqual(general_midi_note("open_hihat"), 46)
        self.assertEqual(general_midi_note("crash"), 49)
        self.assertEqual(general_midi_note("ride"), 51)

    def test_maps_drumscript_classes(self) -> None:
        self.assertEqual(normalize_drum_instrument("hi_hat_closed"), "closed_hihat")
        self.assertEqual(normalize_drum_instrument("hi_hat_open"), "open_hihat")
        self.assertEqual(normalize_drum_instrument("low_tom"), "low_tom")
        self.assertEqual(normalize_drum_instrument("unknown"), "other")


if __name__ == "__main__":
    unittest.main()
