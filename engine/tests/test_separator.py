from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from errors import SeparationError
from project_files import validate_input, write_source_metadata


class SeparatorUtilitiesTest(unittest.TestCase):
    def test_rejects_unsupported_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "track.aiff"
            source.write_bytes(b"audio")
            with self.assertRaises(SeparationError) as raised:
                validate_input(source)
            self.assertEqual(raised.exception.user_message, "Unable to decode this audio file.")

    def test_writes_source_metadata_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.wav"
            output = root / "project"
            source.write_bytes(b"unchanged")
            output.mkdir()
            write_source_metadata(
                source,
                output,
                profile_id="standard",
                backend_id="demucs",
                model_id="htdemucs",
            )
            metadata = json.loads((output / "source.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sourceName"], "song.wav")
            self.assertEqual(metadata["qualityProfile"], "standard")
            self.assertEqual(metadata["backend"], "demucs")
            self.assertEqual(metadata["model"], "htdemucs")
            self.assertEqual(source.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
