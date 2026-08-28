import unittest

from fretboard import BassFretboardSolver, FretPosition
from transcription_domain import NoteEvent


def note(identifier: str, start: float, pitch: int) -> NoteEvent:
    return NoteEvent(
        identifier,
        start,
        start + 0.4,
        pitch,
        100,
        quantized_start_beat=start * 2,
        quantized_duration_beats=0.75,
    )


class BassFretboardSolverTests(unittest.TestCase):
    def test_standard_eadg_positions_for_midi_40(self) -> None:
        solver = BassFretboardSolver()
        self.assertEqual(
            solver.positions_for_pitch(40),
            (FretPosition(0, 12), FretPosition(1, 7), FretPosition(2, 2)),
        )

    def test_supports_drop_d_and_rejects_impossible_notes(self) -> None:
        solver = BassFretboardSolver((26, 33, 38, 43))
        self.assertIn(FretPosition(0, 0), solver.positions_for_pitch(26))
        self.assertEqual(solver.positions_for_pitch(25), ())

    def test_five_string_tuning_places_low_b_on_the_fifth_string(self) -> None:
        solver = BassFretboardSolver((23, 28, 33, 38, 43))
        self.assertEqual(solver.positions_for_pitch(23), (FretPosition(0, 0),))
        tab = solver.solve([note("low-b", 0, 23)])
        self.assertEqual((tab[0].string_index, tab[0].fret), (0, 0))

    def test_dynamic_programming_prefers_a_playable_sequence(self) -> None:
        solver = BassFretboardSolver()
        events = [note("a", 0, 40), note("b", 0.5, 42), note("c", 1.0, 43)]
        tab = solver.solve(events)
        self.assertEqual([item.note_event_id for item in tab], ["a", "b", "c"])
        self.assertLessEqual(max(item.fret for item in tab) - min(item.fret for item in tab), 3)

    def test_polyphonic_fallback_uses_distinct_strings_when_possible(self) -> None:
        solver = BassFretboardSolver()
        tab = solver.solve([note("root", 0, 40), note("fifth", 0.01, 47)])
        self.assertEqual(len(tab), 2)
        self.assertEqual(len({item.string_index for item in tab}), 2)


if __name__ == "__main__":
    unittest.main()
