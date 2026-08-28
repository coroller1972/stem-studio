from __future__ import annotations

import unittest

import numpy as np

from basic_pitch_monophonic import (
    BASIC_PITCH_MIDI_OFFSET,
    MonophonicDecoderSettings,
    decode_monophonic_bass,
)


class BasicPitchMonophonicDecoderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = MonophonicDecoderSettings(
            minimum_note_length_ms=80,
            minimum_onset_note_length_ms=50,
        )

    def test_rejects_a_weak_simultaneous_lower_octave(self) -> None:
        notes, onsets, times = self._outputs(20)
        self._activate(notes, 40, 0.82)
        self._activate(notes, 28, 0.12)
        onsets[0, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.9

        events = decode_monophonic_bass(notes, onsets, times, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_fundamental_prior_rejects_a_stronger_octave_harmonic(self) -> None:
        notes, onsets, times = self._outputs(20)
        self._activate(notes, 40, 0.70)
        self._activate(notes, 52, 0.85)
        onsets[0, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.8
        onsets[0, 52 - BASIC_PITCH_MIDI_OFFSET] = 0.8

        events = decode_monophonic_bass(
            notes,
            onsets,
            times,
            self.settings,
            fundamental_midi=[40.0] * 20,
            fundamental_confidence=[0.9] * 20,
        )

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_does_not_pull_a_valid_upper_fundamental_down(self) -> None:
        notes, onsets, times = self._outputs(20)
        self._activate(notes, 40, 0.84)
        self._activate(notes, 28, 0.03)
        onsets[0, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.9

        events = decode_monophonic_bass(
            notes,
            onsets,
            times,
            self.settings,
            fundamental_midi=[40.0] * 20,
            fundamental_confidence=[0.9] * 20,
        )

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_splits_fast_repeated_notes_on_confirmed_attacks(self) -> None:
        notes, onsets, times = self._outputs(18)
        self._activate(notes, 40, 0.82)
        pitch_bin = 40 - BASIC_PITCH_MIDI_OFFSET
        onsets[0, pitch_bin] = 0.9
        onsets[8, pitch_bin] = 0.95

        events = decode_monophonic_bass(notes, onsets, times, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40, 40])
        self.assertAlmostEqual(events[0].detected_end_seconds, 0.08)
        self.assertAlmostEqual(events[1].detected_start_seconds, 0.08)

    def test_filters_a_short_fragment_without_an_attack(self) -> None:
        notes, onsets, times = self._outputs(20)
        pitch_bin = 40 - BASIC_PITCH_MIDI_OFFSET
        notes[6:12, pitch_bin] = 0.85

        events = decode_monophonic_bass(notes, onsets, times, self.settings)

        self.assertEqual(events, ())

    def test_keeps_a_short_fragment_with_an_attack(self) -> None:
        notes, onsets, times = self._outputs(20)
        pitch_bin = 40 - BASIC_PITCH_MIDI_OFFSET
        notes[6:12, pitch_bin] = 0.85
        onsets[6, pitch_bin] = 0.95

        events = decode_monophonic_bass(notes, onsets, times, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_transition_model_ignores_a_single_frame_pitch_parasite(self) -> None:
        notes, onsets, times = self._outputs(24)
        self._activate(notes, 40, 0.82)
        notes[11, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.18
        notes[11, 43 - BASIC_PITCH_MIDI_OFFSET] = 0.95
        onsets[0, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.9

        events = decode_monophonic_bass(notes, onsets, times, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_preserves_basic_pitch_contour_as_semitone_bends(self) -> None:
        notes, onsets, times = self._outputs(20)
        self._activate(notes, 40, 0.82)
        onsets[0, 40 - BASIC_PITCH_MIDI_OFFSET] = 0.9
        contours = np.zeros((20, 88 * 3), dtype=np.float64)
        contour_center = (40 - BASIC_PITCH_MIDI_OFFSET) * 3
        contours[:, contour_center + 3] = 0.95

        [event] = decode_monophonic_bass(
            notes,
            onsets,
            times,
            self.settings,
            contour_probabilities=contours,
        )

        self.assertTrue(event.pitch_bends)
        self.assertTrue(all(point.semitones == 1.0 for point in event.pitch_bends))

    @staticmethod
    def _outputs(frame_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        notes = np.full((frame_count, 88), 0.01, dtype=np.float64)
        onsets = np.zeros_like(notes)
        times = np.arange(frame_count, dtype=np.float64) * 0.01
        return notes, onsets, times

    @staticmethod
    def _activate(notes: np.ndarray, midi_pitch: int, probability: float) -> None:
        notes[:, midi_pitch - BASIC_PITCH_MIDI_OFFSET] = probability


if __name__ == "__main__":
    unittest.main()
