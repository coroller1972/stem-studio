from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from transcription_domain import TranscriptionProgressReporter
from transcription_requantizer import requantize_transcription


class TranscriptionRequantizerTests(unittest.TestCase):
    def test_rebuilds_bass_grid_and_exports_from_source_events(self) -> None:
        payload = {
            "schemaVersion": 3,
            "track": "bass",
            "events": [],
            "sourceEvents": [
                {
                    "id": "n1",
                    "detectedStartSeconds": 1.41,
                    "detectedEndSeconds": 1.61,
                    "midiPitch": 40,
                    "velocity": 100,
                    "confidence": 0.9,
                    "pitchBends": [],
                },
                {
                    "id": "n2",
                    "detectedStartSeconds": 1.81,
                    "detectedEndSeconds": 2.01,
                    "midiPitch": 43,
                    "velocity": 95,
                    "confidence": 0.85,
                    "pitchBends": [],
                },
            ],
            "tab": [],
            "tempoMap": {
                "bpm": 152,
                "beats": [],
                "timeSignature": {"numerator": 4, "denominator": 4},
            },
            "tuning": [28, 33, 38, 43],
            "warnings": ["Metric tempo is ambiguous; plausible alternative(s): 76.0 BPM."],
            "modelId": "spotify-basic-pitch-test",
        }
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bass.json"
            source.write_text(json.dumps(payload), encoding="utf-8")

            result = requantize_transcription(
                source,
                root,
                "bass",
                150.08,
                1.25,
                TranscriptionProgressReporter(updates.append),
            )

            self.assertAlmostEqual(result.transcription.tempo_map.bpm, 150.08)
            self.assertAlmostEqual(result.transcription.tempo_map.beats[0].time_seconds, 1.25)
            self.assertEqual(len(result.transcription.source_events), 2)
            self.assertEqual(len(result.transcription.events), 2)
            self.assertTrue(result.midi_file.is_file())
            self.assertTrue(result.music_xml_file.is_file())
            saved = json.loads(result.events_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["schemaVersion"], 3)
            self.assertEqual(len(saved["sourceEvents"]), 2)
            self.assertNotIn("Metric tempo is ambiguous", " ".join(saved["warnings"]))
            self.assertEqual(updates[-1].stage, "completed")

    def test_old_drum_payload_falls_back_to_quantized_events(self) -> None:
        payload = {
            "schemaVersion": 1,
            "track": "drums",
            "events": [
                {
                    "id": "kick",
                    "detectedTimeSeconds": 0.52,
                    "quantizedBeat": 1,
                    "instrument": "kick",
                    "velocity": 110,
                    "confidence": None,
                }
            ],
            "tempoMap": {
                "bpm": 120,
                "beats": [],
                "timeSignature": {"numerator": 4, "denominator": 4},
            },
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "drums.json"
            source.write_text(json.dumps(payload), encoding="utf-8")

            result = requantize_transcription(
                source,
                root,
                "drums",
                100,
                0.1,
                TranscriptionProgressReporter(lambda _update: None),
            )

            self.assertEqual(result.transcription.events[0].quantized_beat, 0.75)
            self.assertEqual(result.transcription.to_payload()["schemaVersion"], 2)


if __name__ == "__main__":
    unittest.main()
