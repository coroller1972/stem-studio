from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class JsonEventStreamTest(unittest.TestCase):
    def test_events_stay_on_protocol_stream_during_library_stdout_redirect(self) -> None:
        event_stream = io.StringIO()
        library_logs = io.StringIO()

        with patch.object(main, "_EVENT_STREAM", event_stream):
            with redirect_stdout(library_logs):
                print("model log")
                main.emit({"type": "progress", "progress": 0.25, "message": "Separating"})

        self.assertEqual(library_logs.getvalue(), "model log\n")
        self.assertEqual(
            json.loads(event_stream.getvalue()),
            {"type": "progress", "progress": 0.25, "message": "Separating"},
        )

    def test_bass_cli_exposes_both_ab_engines(self) -> None:
        parser = main.build_parser()
        basic = parser.parse_args(
            ["transcribe-bass", "bass.wav", "--output", "out"]
        )
        experimental = parser.parse_args(
            [
                "transcribe-bass",
                "bass.wav",
                "--output",
                "out",
                "--bass-engine",
                "torchcrepe",
            ]
        )

        self.assertEqual(basic.bass_engine, "basic-pitch")
        self.assertEqual(experimental.bass_engine, "torchcrepe")

    def test_requantize_cli_requires_manual_timing(self) -> None:
        args = main.build_parser().parse_args(
            [
                "requantize-bass",
                "bass.json",
                "--output",
                "out",
                "--bpm",
                "150.08",
                "--first-measure-seconds",
                "1.25",
            ]
        )

        self.assertEqual(args.bpm, 150.08)
        self.assertEqual(args.first_measure_seconds, 1.25)


if __name__ == "__main__":
    unittest.main()
