from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain import ProgressReporter, ProgressUpdate, StemResult, StemSeparator


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.events: list[ProgressUpdate] = []

    def report(self, progress: float, message: str) -> None:
        self.events.append(ProgressUpdate(progress, message))


class FakeSeparator:
    backend_id = "fake"
    model_id = "test-model"

    def separate(
        self,
        input_path: Path,
        output_dir: Path,
        progress: ProgressReporter,
    ) -> StemResult:
        progress.report(1.0, "Done")
        stems = {
            name: output_dir / f"{name}.wav"
            for name in ("vocals", "drums", "bass", "other")
        }
        return StemResult(
            stems=stems,
            sample_rate=44_100,
            channels=2,
            duration_seconds=12.5,
            backend_id=self.backend_id,
            model_id=self.model_id,
            device="cpu",
        )


class DomainContractsTest(unittest.TestCase):
    def test_progress_is_normalized(self) -> None:
        self.assertEqual(ProgressUpdate(-0.2, "Starting").progress, 0.0)
        self.assertEqual(ProgressUpdate(1.2, "Done").progress, 1.0)

    def test_stem_result_requires_the_standard_four_stems(self) -> None:
        with self.assertRaises(ValueError):
            StemResult(
                stems={"vocals": Path("vocals.wav")},  # type: ignore[arg-type]
                sample_rate=44_100,
                channels=2,
                duration_seconds=1.0,
                backend_id="fake",
                model_id="fake-model",
                device="cpu",
            )

    def test_separator_protocol_and_stable_payload(self) -> None:
        separator = FakeSeparator()
        self.assertIsInstance(separator, StemSeparator)
        reporter = RecordingProgressReporter()

        result = separator.separate(Path("source.mp3"), Path("project"), reporter)

        self.assertEqual(
            result.stems_payload(),
            {
                "vocals": "project/vocals.wav",
                "drums": "project/drums.wav",
                "bass": "project/bass.wav",
                "other": "project/other.wav",
            },
        )
        self.assertEqual(reporter.events, [ProgressUpdate(1.0, "Done")])


if __name__ == "__main__":
    unittest.main()
