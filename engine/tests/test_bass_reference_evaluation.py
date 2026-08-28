from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bass_reference_evaluation import evaluate_bass_reference, load_reference_midi


class BassReferenceEvaluationTests(unittest.TestCase):
    def test_aligns_excerpt_and_reports_pitch_onset_octave_and_fast_note_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.mid"
            prediction = root / "bass.json"
            _write_reference_midi(reference)
            prediction.write_text(json.dumps({
                "track": "bass",
                "sourceEvents": [
                    _event("p1", 10.01, 10.12, 40),
                    _event("p2", 10.26, 10.37, 40),
                    _event("octave", 10.51, 10.72, 35),
                    _event("extra", 10.75, 10.9, 50),
                    _event("p4", 11.02, 11.25, 45),
                ],
                "events": [],
            }), encoding="utf-8")

            report = evaluate_bass_reference(
                prediction,
                reference,
                reference_bpm=120,
                onset_tolerance_seconds=0.08,
            )

            self.assertAlmostEqual(report.alignment.offset_seconds, 10.01, places=2)
            self.assertEqual(report.metrics.reference_note_count, 4)
            self.assertEqual(report.metrics.prediction_note_count, 5)
            self.assertEqual(report.metrics.exact_pitch_matches, 3)
            self.assertEqual(report.metrics.onset_matches, 4)
            self.assertAlmostEqual(report.metrics.note_recall, 0.75)
            self.assertAlmostEqual(report.metrics.onset_recall, 1.0)
            self.assertAlmostEqual(report.metrics.pitch_accuracy_on_matched_onsets, 0.75)
            self.assertEqual(report.metrics.octave_errors, 1)
            self.assertEqual(report.metrics.octave_errors_up, 1)
            self.assertEqual(report.metrics.octave_errors_down, 0)
            self.assertEqual(report.metrics.repeated_note_count, 2)
            self.assertAlmostEqual(report.metrics.repeated_note_recall, 1.0)
            self.assertEqual(report.metrics.low_b_count, 1)
            self.assertEqual(report.metrics.low_b_recall, 0.0)

    def test_midi_tempo_override_controls_reference_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.mid"
            _write_reference_midi(path)

            at_120 = load_reference_midi(path, bpm_override=120)
            at_60 = load_reference_midi(path, bpm_override=60)

            self.assertAlmostEqual(at_120[1].detected_start_seconds, 0.25)
            self.assertAlmostEqual(at_60[1].detected_start_seconds, 0.5)


def _event(event_id: str, start: float, end: float, pitch: int) -> dict[str, object]:
    return {
        "id": event_id,
        "detectedStartSeconds": start,
        "detectedEndSeconds": end,
        "midiPitch": pitch,
        "velocity": 100,
        "confidence": 0.9,
        "pitchBends": [],
    }


def _write_reference_midi(path: Path) -> None:
    import mido

    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    tempo = mido.MidiTrack()
    tempo.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(152), time=0))
    notes = mido.MidiTrack()
    absolute = [
        (0, mido.Message("note_on", note=40, velocity=100)),
        (96, mido.Message("note_off", note=40, velocity=0)),
        (240, mido.Message("note_on", note=40, velocity=100)),
        (336, mido.Message("note_off", note=40, velocity=0)),
        (480, mido.Message("note_on", note=23, velocity=100)),
        (672, mido.Message("note_off", note=23, velocity=0)),
        (960, mido.Message("note_on", note=45, velocity=100)),
        (1152, mido.Message("note_off", note=45, velocity=0)),
    ]
    previous = 0
    for tick, message in absolute:
        message.time = tick - previous
        notes.append(message)
        previous = tick
    midi.tracks.extend((tempo, notes))
    midi.save(path)


if __name__ == "__main__":
    unittest.main()
