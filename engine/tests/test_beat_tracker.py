import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from beat_tracker import LibrosaBeatTracker, infer_downbeat_offset, metric_tempo_candidates, stable_beat_source


class StableBeatSourceTests(unittest.TestCase):
    def test_infers_the_strongest_four_four_downbeat_phase(self) -> None:
        strengths = [0.2, 0.3, 1.0, 0.25, 0.2, 0.25, 0.9, 0.2, 0.2, 0.2, 1.1, 0.3]
        self.assertEqual(infer_downbeat_offset(strengths, 4), 2)

    def test_keeps_first_phase_when_metric_evidence_is_ambiguous(self) -> None:
        self.assertEqual(infer_downbeat_offset([1.0] * 12, 4), 0)

    def test_exposes_plausible_half_and_double_time_interpretations(self) -> None:
        self.assertEqual(metric_tempo_candidates(152), (76.0, 152))
        self.assertEqual(metric_tempo_candidates(99), (99, 198))

    def test_reconstructs_all_stems_and_removes_temporary_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            output = project / "transcription"
            project.mkdir()
            output.mkdir()
            for index, name in enumerate(("vocals", "drums", "bass", "other"), start=1):
                audio = np.full((512, 2), index * 0.01, dtype=np.float32)
                sf.write(project / f"{name}.wav", audio, 44_100, subtype="FLOAT")

            temporary_mix = output / ".beat-mix.wav"
            with stable_beat_source(project / "drums.wav", None, output) as source:
                self.assertEqual(source, temporary_mix)
                mixed, sample_rate = sf.read(source, dtype="float32", always_2d=True)
                self.assertEqual(sample_rate, 44_100)
                np.testing.assert_allclose(mixed, 0.1, atol=1e-6)

            self.assertFalse(temporary_mix.exists())

    def test_falls_back_to_requested_source_without_all_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            drums = root / "drums.wav"
            requested = root / "original.wav"
            drums.touch()
            requested.touch()
            with stable_beat_source(drums, requested, root) as source:
                self.assertEqual(source, requested)


if __name__ == "__main__":
    unittest.main()


class LibrosaBeatTrackerTests(unittest.TestCase):
    def test_tracks_the_beat_on_the_percussive_part_of_the_mix(self) -> None:
        import librosa

        sample_rate = 22_050
        seconds = 20
        audio = np.zeros(sample_rate * seconds, dtype=np.float32)
        burst = int(0.03 * sample_rate)
        noise = np.random.default_rng(0).standard_normal(burst) * np.exp(-np.arange(burst) / (0.005 * sample_rate))
        for beat in np.arange(0, seconds - 0.1, 60 / 150):  # a drum hit every beat at 150 BPM
            start = int(beat * sample_rate)
            audio[start:start + burst] += 0.5 * noise
        real_percussive = librosa.effects.percussive
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(librosa.effects, "percussive", side_effect=real_percussive) as percussive:
            path = Path(temporary) / "mix.wav"
            sf.write(path, audio, sample_rate)
            tempo_map = LibrosaBeatTracker().track(path)

        percussive.assert_called_once()
        self.assertAlmostEqual(tempo_map.bpm, 150, delta=3)
        times = [beat.time_seconds for beat in tempo_map.beats]
        self.assertAlmostEqual(60 / float(np.median(np.diff(times))), 150, delta=3)

