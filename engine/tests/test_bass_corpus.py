from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from run_bass_corpus import _baseline_payload, _parse_prediction_overrides, compare_with_baseline, load_manifest


class BassCorpusTests(unittest.TestCase):
    def test_manifest_paths_are_relative_to_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps({
                "schemaVersion": 1,
                "cases": [{
                    "id": "case",
                    "audioPath": "audio/bass.wav",
                    "referenceMidiPath": "reference.mid",
                    "referenceBpm": 150.08,
                    "predictions": {"basic-pitch": "results/bass.json"},
                }],
            }), encoding="utf-8")

            [case] = load_manifest(manifest)

            self.assertEqual(case.audio_path, (root / "audio/bass.wav").resolve())
            self.assertEqual(case.reference_midi_path, (root / "reference.mid").resolve())
            self.assertEqual(
                case.predictions["basic-pitch"],
                (root / "results/bass.json").resolve(),
            )

    def test_baseline_comparison_flags_only_material_regressions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline.json"
            previous = _report(note_f1=0.70, onset_error=0.03)
            baseline_path.write_text(json.dumps(previous), encoding="utf-8")

            acceptable = _report(note_f1=0.685, onset_error=0.039)
            regressed = _report(note_f1=0.67, onset_error=0.03)

            self.assertEqual(compare_with_baseline(acceptable, baseline_path), [])
            failures = compare_with_baseline(regressed, baseline_path)
            self.assertTrue(any("noteF1" in failure for failure in failures))

    def test_prediction_override_and_baseline_are_portable(self) -> None:
        override = _parse_prediction_overrides(["case/basic-pitch=results/bass.json"])
        payload = {
            "schemaVersion": 1,
            "manifest": "/private/corpus.json",
            "results": [{
                "caseId": "case",
                "engineId": "basic-pitch",
                "predictionPath": "/private/bass.json",
                "referencePath": "/private/reference.mid",
                "metrics": {},
            }],
        }

        self.assertTrue(override[("case", "basic-pitch")].is_absolute())
        baseline = _baseline_payload(payload)
        self.assertNotIn("manifest", baseline)
        self.assertNotIn("predictionPath", baseline["results"][0])


def _report(*, note_f1: float, onset_error: float) -> dict[str, object]:
    metrics = {
        "noteF1": note_f1,
        "onsetF1": 0.8,
        "pitchAccuracyOnMatchedOnsets": 0.8,
        "shortNoteRecall": 0.7,
        "repeatedNoteRecall": 0.7,
        "lowBRecall": 0.5,
        "octaveErrorRate": 0.05,
        "medianOnsetErrorSeconds": onset_error,
        "medianDurationErrorSeconds": 0.1,
    }
    return {
        "results": [{"caseId": "case", "engineId": "basic-pitch", "metrics": metrics}]
    }


if __name__ == "__main__":
    unittest.main()
