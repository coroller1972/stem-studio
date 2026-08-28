from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs_roformer_separator import BS_ROFORMER_MUSDB18HQ, BSRoFormerSeparator
from domain import ProgressUpdate, StemSeparator


class FakeWaveform:
    shape = (2, 88_200)


class FakeAudioIO:
    def load(self, source: Path, sample_rate: int, channels: int) -> FakeWaveform:
        return FakeWaveform()

    def save_wav(self, audio: Any, path: Path, sample_rate: int) -> None:
        path.write_bytes(b"prepared wav")


class RecordingProgress:
    def __init__(self) -> None:
        self.events: list[ProgressUpdate] = []

    def report(self, progress: float, message: str) -> None:
        self.events.append(ProgressUpdate(progress, message))


class FakeSession:
    def __init__(self, device: str, fail: bool = False) -> None:
        self.device = device
        self.fail = fail
        self.closed = False

    def load(self) -> "FakeSession":
        return self

    def infer(self, input_folder: Path, *, store_dir: Path, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("unsupported accelerator operation")
        outputs = []
        for name in ("vocals", "drums", "bass", "other"):
            path = store_dir / f"source_{name}.wav"
            path.write_bytes(name.encode())
            outputs.append(SimpleNamespace(output_id=name, output_path=str(path)))
        outputs.append(SimpleNamespace(output_id="instrumental", output_path="ignored.wav"))
        return SimpleNamespace(outputs=tuple(outputs))

    def close(self) -> None:
        self.closed = True


class BSRoFormerSeparatorTest(unittest.TestCase):
    def test_implements_contract_and_collects_four_standard_stems(self) -> None:
        session_arguments: list[dict[str, Any]] = []

        def session_factory(**kwargs: Any) -> FakeSession:
            session_arguments.append(kwargs)
            return FakeSession(kwargs["device"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.mp3"
            source.write_bytes(b"audio")
            output = root / "project"
            progress = RecordingProgress()
            separator = BSRoFormerSeparator(
                audio_io=FakeAudioIO(),
                device_selector=lambda: "cpu",
                session_factory=session_factory,
            )

            self.assertIsInstance(separator, StemSeparator)
            result = separator.separate(source, output, progress)

            self.assertEqual(result.backend_id, "bs_roformer")
            self.assertEqual(result.model_id, BS_ROFORMER_MUSDB18HQ)
            self.assertEqual(result.duration_seconds, 2.0)
            self.assertEqual(session_arguments[0]["backend"], "torch")
            self.assertEqual(set(result.stems), {"vocals", "drums", "bass", "other"})
            self.assertTrue(all(path.is_file() for path in result.stems.values()))
            metadata = json.loads((output / "source.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["qualityProfile"], "high")
            self.assertEqual(metadata["separation"]["backendId"], "bs_roformer")
            self.assertEqual(progress.events[-1], ProgressUpdate(0.98, "Finalizing project"))

    def test_mps_failure_recreates_session_on_cpu(self) -> None:
        devices: list[str] = []

        def session_factory(**kwargs: Any) -> FakeSession:
            device = kwargs["device"]
            devices.append(device)
            return FakeSession(device, fail=device == "mps")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.wav"
            source.write_bytes(b"audio")
            separator = BSRoFormerSeparator(
                audio_io=FakeAudioIO(),
                device_selector=lambda: "mps",
                session_factory=session_factory,
            )

            result = separator.separate(source, root / "project", RecordingProgress())

            self.assertEqual(devices, ["mps", "cpu"])
            self.assertEqual(result.device, "cpu")
            self.assertEqual(result.warnings, ("MPS inference failed; CPU fallback was used.",))


if __name__ == "__main__":
    unittest.main()
