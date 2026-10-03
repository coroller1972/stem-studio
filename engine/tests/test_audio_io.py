import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_io import FfmpegAudioIO, resolve_ffmpeg_executable


class ResolveFfmpegExecutableTests(unittest.TestCase):
    def test_prefers_explicit_packaged_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ffmpeg"
            executable.write_bytes(b"test")
            executable.chmod(0o755)

            with (
                patch.dict(os.environ, {"STEM_STUDIO_FFMPEG": str(executable)}, clear=False),
                patch("audio_io.shutil.which", return_value="/fallback/ffmpeg"),
            ):
                self.assertEqual(resolve_ffmpeg_executable(), str(executable))

    def test_falls_back_to_path_when_configured_file_is_missing(self) -> None:
        with (
            patch.dict(os.environ, {"STEM_STUDIO_FFMPEG": "/missing/ffmpeg"}, clear=False),
            patch("audio_io.shutil.which", return_value="/fallback/ffmpeg"),
        ):
            self.assertEqual(resolve_ffmpeg_executable(), "/fallback/ffmpeg")


class SaveWavTests(unittest.TestCase):
    def test_float_output_keeps_the_original_level_above_full_scale(self) -> None:
        import numpy
        import torch

        audio = torch.tensor([[1.5, 0.5, -0.25], [0.0, -1.2, 0.75]])
        with (
            patch("audio_io.resolve_ffmpeg_executable", return_value="/usr/bin/ffmpeg"),
            patch("audio_io.subprocess.run") as run,
        ):
            FfmpegAudioIO().save_wav(audio, Path("drums.wav"), 44_100)

        written = numpy.frombuffer(run.call_args.kwargs["input"], dtype="<f4").reshape(-1, 2)
        numpy.testing.assert_allclose(written.T, audio.numpy())

    def test_pcm16_fallback_clips_without_rescaling_the_stem(self) -> None:
        import torch

        audio = torch.tensor([[1.5, 0.5, -0.25]])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drums.wav"
            with patch("audio_io.resolve_ffmpeg_executable", return_value=None):
                FfmpegAudioIO().save_wav(audio, path, 44_100)

            import wave

            with wave.open(str(path), "rb") as wav_file:
                frames = wav_file.readframes(3)
        samples = [int.from_bytes(frames[index : index + 2], "little", signed=True) for index in range(0, 6, 2)]
        self.assertEqual(samples, [32767, 16383, -8191])


if __name__ == "__main__":
    unittest.main()
