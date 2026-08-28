from __future__ import annotations

import unittest

from musical_timeline import DIVISIONS_PER_QUARTER, measure_windows, notation_atoms, spell_duration
from transcription_domain import NoteEvent


class MusicalTimelineTests(unittest.TestCase):
    def test_pickup_is_an_implicit_measure_without_leading_silence(self) -> None:
        windows = measure_windows(-0.5, 5.0, 4.0)

        self.assertEqual((windows[0].number, windows[0].start_beat, windows[0].end_beat), (0, -0.5, 0.0))
        self.assertTrue(windows[0].implicit)
        self.assertEqual((windows[1].number, windows[1].start_beat), (1, 0.0))

    def test_note_crossing_barline_is_split_and_tied(self) -> None:
        event = NoteEvent("crossing", 0, 1, 40, 100).quantized(3.5, 1.5)

        windows, atoms = notation_atoms((event,), 4.0)

        self.assertEqual([window.number for window in windows], [1, 2])
        self.assertEqual([atom.duration.ticks for atom in atoms], [12, 24])
        self.assertEqual([(atom.tie_stop, atom.tie_start) for atom in atoms], [(False, True), (True, False)])

    def test_dotted_and_triplet_durations_have_exact_spelling(self) -> None:
        dotted = spell_duration(1.5)
        triplet = spell_duration(1 / 3)

        self.assertEqual((dotted[0].note_type, dotted[0].dots), ("quarter", 1))
        self.assertEqual(dotted[0].ticks, round(1.5 * DIVISIONS_PER_QUARTER))
        self.assertEqual((triplet[0].note_type, triplet[0].actual_notes), ("eighth", 3))

    def test_overlapping_bass_spans_are_trimmed_at_next_onset(self) -> None:
        first = NoteEvent("first", 0, 2, 40, 100).quantized(0, 3)
        second = NoteEvent("second", 1, 2, 43, 100).quantized(2, 1)

        _windows, atoms = notation_atoms((first, second), 4)

        first_ticks = sum(atom.duration.ticks for atom in atoms if atom.event.id == "first")
        self.assertEqual(first_ticks, 2 * DIVISIONS_PER_QUARTER)


if __name__ == "__main__":
    unittest.main()
