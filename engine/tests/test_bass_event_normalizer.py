import unittest

from bass_event_normalizer import normalize_bass_events
from bass_quality import measure_bass_quality
from transcription_domain import NoteEvent


class BassEventNormalizerTests(unittest.TestCase):
    def test_rejects_a_weak_simultaneous_octave_candidate(self) -> None:
        events = (
            self._note("weak-e1", 0.0, 0.4, 28, 0.04),
            self._note("strong-e2", 0.0, 0.4, 40, 0.91),
        )

        normalized = normalize_bass_events(events)

        self.assertEqual([event.id for event in normalized], ["strong-e2"])

    def test_uses_pitch_continuity_to_break_close_confidence_scores(self) -> None:
        events = (
            self._note("previous", 0.0, 0.3, 40, 0.8),
            self._note("near", 0.3, 0.6, 43, 0.76),
            self._note("octave", 0.3, 0.6, 52, 0.80),
        )

        normalized = normalize_bass_events(events)

        self.assertEqual([event.id for event in normalized], ["previous", "near"])

    def test_trims_an_old_release_at_a_new_attack(self) -> None:
        events = (
            self._note("first", 0.0, 0.5, 40, 0.8),
            self._note("second", 0.3, 0.7, 43, 0.8),
        )

        normalized = normalize_bass_events(events)

        self.assertEqual([event.id for event in normalized], ["first", "second"])
        self.assertEqual(normalized[0].detected_end_seconds, 0.3)
        self.assertEqual(measure_bass_quality(normalized).overlapping_pairs, 0)

    def test_preserves_zero_gap_repeated_attacks(self) -> None:
        events = (
            self._note("first", 0.0, 0.1, 36, 0.8),
            self._note("second", 0.1, 0.2, 36, 0.8),
            self._note("third", 0.2, 0.3, 36, 0.8),
        )

        normalized = normalize_bass_events(events)

        self.assertEqual([event.id for event in normalized], ["first", "second", "third"])

    @staticmethod
    def _note(
        event_id: str,
        start: float,
        end: float,
        pitch: int,
        confidence: float,
    ) -> NoteEvent:
        return NoteEvent(event_id, start, end, pitch, round(confidence * 127), confidence)


if __name__ == "__main__":
    unittest.main()
