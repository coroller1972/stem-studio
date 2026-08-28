import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_io import resolve_ffmpeg_executable


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


if __name__ == "__main__":
    unittest.main()
