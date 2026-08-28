from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demucs_separator import DemucsSeparator
from domain import ProgressUpdate, StemSeparator


class FakeStem:
    shape = (2, 44_100)


class FakeAudioIO:
    def __init__(self) -> None:
        self.saved: list[tuple[Path, int]] = []

    def load(self, source: Path, sample_rate: int, channels: int) -> Any:
        raise AssertionError("The injected inference runner handles loading in this test.")

    def save_wav(self, audio: Any, path: Path, sample_rate: int) -> None:
        path.write_bytes(b"fake wav")
        self.saved.append((path, sample_rate))


class RecordingProgress:
    def __init__(self) -> None:
        self.events: list[ProgressUpdate] = []

    def report(self, progress: float, message: str) -> None:
        self.events.append(ProgressUpdate(progress, message))


def fake_stems() -> dict[str, FakeStem]:
    return {name: FakeStem() for name in ("vocals", "drums", "bass", "other")}


class DemucsSeparatorTest(unittest.TestCase):
    def test_implements_contract_and_returns_standard_result(self) -> None:
        calls: list[tuple[Path, str, str]] = []

        def infer(source: Path, device: str, model_id: str, audio_io: Any):
            calls.append((source, device, model_id))
            return fake_stems(), 44_100

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.mp3"
            source.write_bytes(b"audio")
            output = root / "project"
            audio_io = FakeAudioIO()
            progress = RecordingProgress()
            separator = DemucsSeparator(
                model_id="htdemucs",
                profile_id="standard",
                audio_io=audio_io,
                device_selector=lambda: "cpu",
                inference_runner=infer,
            )

            self.assertIsInstance(separator, StemSeparator)
            result = separator.separate(source, output, progress)

            self.assertEqual(calls, [(source.resolve(), "cpu", "htdemucs")])
            self.assertEqual(result.backend_id, "demucs")
            self.assertEqual(result.duration_seconds, 1.0)
            self.assertEqual(len(audio_io.saved), 4)
            self.assertEqual(progress.events[-1], ProgressUpdate(0.98, "Finalizing project"))
            metadata = json.loads((output / "source.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["separation"]["backendId"], "demucs")

    def test_mps_failure_retries_on_cpu_and_records_warning(self) -> None:
        devices: list[str] = []

        def infer(source: Path, device: str, model_id: str, audio_io: Any):
            devices.append(device)
            if device == "mps":
                raise RuntimeError("unsupported MPS operation")
            return fake_stems(), 44_100

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.wav"
            source.write_bytes(b"audio")
            separator = DemucsSeparator(
                audio_io=FakeAudioIO(),
                device_selector=lambda: "mps",
                inference_runner=infer,
            )

            result = separator.separate(source, root / "project", RecordingProgress())

            self.assertEqual(devices, ["mps", "cpu"])
            self.assertEqual(result.device, "cpu")
            self.assertEqual(result.warnings, ("MPS inference failed; CPU fallback was used.",))


if __name__ == "__main__":
    unittest.main()
