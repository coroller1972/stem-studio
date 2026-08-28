import unittest

from quantization import fixed_tempo_map, quantize_beat, quantize_drums, quantize_notes, time_to_beat
from transcription_domain import DrumEvent, NoteEvent, TempoBeat, TempoMap


class QuantizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempo = TempoMap(
            bpm=120,
            beats=tuple(TempoBeat(index, index * 0.5) for index in range(9)),
        )

    def test_converts_seconds_to_beats_and_supported_grids(self) -> None:
        self.assertAlmostEqual(time_to_beat(1.25, self.tempo), 2.5)
        self.assertEqual(quantize_beat(1.28, 1), 1.0)
        self.assertEqual(quantize_beat(1.28, 2), 1.5)
        self.assertEqual(quantize_beat(1.28, 4), 1.25)

    def test_fixed_tempo_map_uses_first_measure_as_beat_zero(self) -> None:
        tempo = fixed_tempo_map(150, 1.2, 8.0)

        self.assertAlmostEqual(tempo.beats[0].time_seconds, 1.2)
        self.assertAlmostEqual(tempo.beats[1].time_seconds, 1.6)
        self.assertAlmostEqual(time_to_beat(2.0, tempo), 2.0)

    def test_quantization_preserves_pickup_events_before_first_measure(self) -> None:
        tempo = fixed_tempo_map(120, 0.5, 4.0)
        [note] = quantize_notes([NoteEvent("pickup", 0.25, 0.45, 40, 90)], tempo, 4)
        [drum] = quantize_drums([DrumEvent("pickup-hit", 0.25, "kick", 100)], tempo, 4)

        self.assertEqual(note.quantized_start_beat, -0.5)
        self.assertEqual(drum.quantized_beat, -0.5)

    def test_quantization_preserves_detected_note_timing(self) -> None:
        original = NoteEvent("n1", 0.63, 1.11, 40, 90, 0.8)
        [event] = quantize_notes([original], self.tempo, 4)
        self.assertEqual(event.detected_start_seconds, 0.63)
        self.assertEqual(event.detected_end_seconds, 1.11)
        self.assertEqual(event.quantized_start_beat, 1.25)
        self.assertEqual(event.quantized_duration_beats, 1.0)

    def test_quantizes_drums_without_overwriting_timestamp(self) -> None:
        original = DrumEvent("d1", 0.61, "kick", 100, 0.9)
        [event] = quantize_drums([original], self.tempo, 4)
        self.assertEqual(event.detected_time_seconds, 0.61)
        self.assertEqual(event.quantized_beat, 1.25)

    def test_keeps_strongest_bass_candidate_on_grid_cell(self) -> None:
        events = [
            NoteEvent("quiet-octave", 0.61, 0.8, 52, 80, 0.35),
            NoteEvent("root", 0.63, 0.9, 40, 100, 0.9),
            NoteEvent("later", 0.76, 1.0, 43, 90, 0.8),
        ]

        quantized = quantize_notes(events, self.tempo, 4)

        self.assertEqual([event.id for event in quantized], ["root", "later"])

    def test_deduplicates_same_pitch_on_grid_cell(self) -> None:
        events = [
            NoteEvent("weak", 0.61, 0.8, 40, 70, 0.4),
            NoteEvent("strong", 0.63, 0.9, 40, 100, 0.9),
        ]

        [event] = quantize_notes(events, self.tempo, 4)

        self.assertEqual(event.id, "strong")

    def test_keeps_strongest_duplicate_instrument_on_grid_cell(self) -> None:
        events = [
            DrumEvent("quiet", 0.61, "kick", 65),
            DrumEvent("strong", 0.63, "kick", 112),
            DrumEvent("snare", 0.62, "snare", 90),
        ]
        quantized = quantize_drums(events, self.tempo, 4)
        self.assertEqual([event.id for event in quantized], ["snare", "strong"])


if __name__ == "__main__":
    unittest.main()
