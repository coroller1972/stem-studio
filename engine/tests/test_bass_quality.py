import unittest

from bass_quality import measure_bass_quality
from transcription_domain import NoteEvent


class BassQualityTests(unittest.TestCase):
    def test_counts_monophony_and_grid_violations(self) -> None:
        events = (
            NoteEvent("root", 0.0, 0.5, 40, 100).quantized(0.0, 1.0),
            NoteEvent("octave", 0.1, 0.4, 52, 80).quantized(0.0, 0.5),
            NoteEvent("duplicate", 0.5, 0.7, 40, 70).quantized(0.0, 0.5),
        )

        metrics = measure_bass_quality(events)

        self.assertEqual(metrics.note_count, 3)
        self.assertEqual(metrics.overlapping_pairs, 1)
        self.assertEqual(metrics.octave_overlap_pairs, 1)
        self.assertEqual(metrics.multi_pitch_grid_cells, 1)
        self.assertEqual(metrics.same_pitch_grid_duplicates, 1)


if __name__ == "__main__":
    unittest.main()
