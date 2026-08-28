from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torchcrepe_transcriber import (
    CREPE_STABLE_MINIMUM_FREQUENCY_HZ,
    PitchTrack,
    TorchCrepeBassTranscriber,
    TorchCrepeBassSettings,
    _midi_frequency,
    _recover_onset_gaps,
    segment_pitch_track,
)


class TorchCrepeSegmentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = TorchCrepeBassSettings(
            minimum_note_length_ms=80,
            maximum_unvoiced_gap_ms=20,
        )

    def test_onset_profile_keeps_sixteenth_notes_at_152_bpm(self) -> None:
        sixteenth_note_ms = 60_000 / 152 / 4

        self.assertLess(
            TorchCrepeBassSettings().minimum_onset_note_length_ms,
            sixteenth_note_ms,
        )

    def test_silence_and_low_periodicity_are_rejected(self) -> None:
        track = self._track([40] * 30, periodicity=0.9, loudness=-80)
        self.assertEqual(segment_pitch_track(track, self.settings), ())

        track = self._track([40] * 30, periodicity=0.2, loudness=-20)
        self.assertEqual(segment_pitch_track(track, self.settings), ())

    def test_single_frame_confidence_hole_does_not_fragment_a_note(self) -> None:
        periodicity = [0.9] * 30
        periodicity[14] = 0.1
        events = segment_pitch_track(self._track([40] * 30, periodicity=periodicity), self.settings)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].midi_pitch, 40)
        self.assertAlmostEqual(events[0].detected_end_seconds, 0.3)

    def test_stable_pitch_jump_creates_two_notes(self) -> None:
        events = segment_pitch_track(self._track([40] * 20 + [43] * 20), self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40, 43])
        self.assertAlmostEqual(events[0].detected_end_seconds, 0.2, places=2)
        self.assertAlmostEqual(events[1].detected_start_seconds, 0.2, places=2)

    def test_short_pitch_parasite_is_filtered(self) -> None:
        midi = [40] * 20 + [52] * 4 + [40] * 20
        events = segment_pitch_track(self._track(midi), self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40])
        self.assertAlmostEqual(events[0].detected_end_seconds, 0.44)

    def test_confirmed_onsets_split_fast_repeated_notes_at_the_same_pitch(self) -> None:
        onsets = [0.0] * 30
        for frame in (0, 6, 12, 18, 24):
            onsets[frame] = 1.0

        events = segment_pitch_track(
            self._track([40] * 30, onset_strengths=onsets),
            self.settings,
        )

        self.assertEqual([event.midi_pitch for event in events], [40] * 5)
        self.assertEqual(
            [round(event.detected_end_seconds - event.detected_start_seconds, 2) for event in events],
            [0.06] * 5,
        )

    def test_short_unconfirmed_pitch_change_remains_filtered(self) -> None:
        events = segment_pitch_track(
            self._track([40] * 12 + [43] * 4 + [40] * 12),
            self.settings,
        )

        self.assertNotIn(43, [event.midi_pitch for event in events])

    def test_low_b_is_preserved_when_reported_by_model(self) -> None:
        events = segment_pitch_track(self._track([23] * 25), self.settings)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].midi_pitch, 23)

    def test_spectral_fallback_recovers_repeated_notes_during_crepe_dropout(self) -> None:
        onsets = [0.0] * 30
        for frame in (0, 6, 12, 18, 24):
            onsets[frame] = 1.0
        track = self._track(
            [24] * 30,
            periodicity=0.05,
            onset_strengths=onsets,
            spectral_midi=[36] * 30,
        )

        events = segment_pitch_track(track, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [36] * 5)

    def test_spectral_fallback_recovers_open_low_b(self) -> None:
        onsets = [0.0] * 25
        onsets[0] = 1.0
        track = self._track(
            [24] * 25,
            periodicity=0.05,
            onset_strengths=onsets,
            spectral_midi=[23] * 25,
        )

        events = segment_pitch_track(track, self.settings)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].midi_pitch, 23)

    def test_valid_crepe_pitch_is_not_lowered_by_spectral_fallback(self) -> None:
        track = self._track(
            [40] * 25,
            periodicity=0.9,
            spectral_midi=[28] * 25,
        )

        events = segment_pitch_track(track, self.settings)

        self.assertEqual([event.midi_pitch for event in events], [40])

    def test_fallback_fills_dropouts_without_overwriting_reliable_crepe_frames(self) -> None:
        midi = [40.0] * 25
        periodicity = [0.05] * 25
        for index in range(10, 15):
            periodicity[index] = 0.9
        onsets = [0.0] * 25
        onsets[0] = 1.0

        _recover_onset_gaps(
            midi,
            periodicity,
            [-20.0] * 25,
            onsets,
            [28.0] * 25,
            0.01,
            self.settings,
        )

        self.assertEqual(midi[2], 28.0)
        self.assertEqual(midi[12], 40.0)
        self.assertEqual(periodicity[12], 0.9)

    def test_prediction_range_avoids_the_unstable_lowest_crepe_bin(self) -> None:
        torchcrepe = Mock()
        torchcrepe.decode.viterbi = object()
        audio = Mock()
        audio.to.return_value = object()
        transcriber = TorchCrepeBassTranscriber(settings=self.settings)

        transcriber._predict_on_device(torchcrepe, audio, "cpu")

        fmin = torchcrepe.predict.call_args.args[3]
        self.assertEqual(fmin, CREPE_STABLE_MINIMUM_FREQUENCY_HZ)

    def _track(
        self,
        midi: list[int],
        *,
        periodicity: float | list[float] = 0.9,
        loudness: float = -20,
        onset_strengths: list[float] | None = None,
        spectral_midi: list[int] | None = None,
    ) -> PitchTrack:
        confidence = (
            [periodicity] * len(midi) if isinstance(periodicity, float) else periodicity
        )
        return PitchTrack(
            frequencies_hz=[_midi_frequency(value) for value in midi],
            periodicities=confidence,
            loudness_db=[loudness] * len(midi),
            hop_seconds=0.01,
            audio_duration_seconds=len(midi) * 0.01,
            onset_strengths=onset_strengths or (),
            spectral_frequencies_hz=[
                _midi_frequency(value) for value in (spectral_midi or [])
            ],
        )

if __name__ == "__main__":
    unittest.main()
