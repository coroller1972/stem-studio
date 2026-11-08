from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import player_package
from player_package import ManualTempo, PlayerExportError, aac_command, export_player_package

MIX = {
    "currentTimeSeconds": 42.0,
    "startMarkerSeconds": 12.5,
    "masterVolume": 0.45,
    "tracks": {"drums": {"volume": 0.4, "muted": True, "solo": False}},
}


def write_wav(path: Path, seconds: float, sample_rate: int = 8_000) -> None:
    """A float32 mono WAV header with a data chunk of the right size (silence)."""
    data_size = int(seconds * sample_rate) * 4
    header = struct.pack("<4sI4s", b"RIFF", 36 + data_size, b"WAVE")
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 3, 1, sample_rate, sample_rate * 4, 4, 32)
    path.write_bytes(header + fmt + struct.pack("<4sI", b"data", data_size) + bytes(data_size))


def fake_converter(source: Path, destination: Path) -> None:
    destination.write_bytes(f"aac:{source.stem}".encode())


class AacCommandTest(unittest.TestCase):
    def test_uses_afconvert_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_afconvert = Path(directory) / "afconvert"
            fake_afconvert.write_text("")
            with patch.object(player_package, "AFCONVERT", fake_afconvert):
                command = aac_command(Path("bass.wav"), Path("bass.m4a"))
        self.assertEqual(command[0], str(fake_afconvert))
        self.assertEqual(command[-2:], ["bass.wav", "bass.m4a"])

    def test_falls_back_to_ffmpeg_native_aac(self) -> None:
        with patch.object(player_package, "AFCONVERT", Path("/nonexistent/afconvert")), \
                patch("audio_io.resolve_ffmpeg_executable", return_value="/usr/bin/ffmpeg"):
            command = aac_command(Path("bass.wav"), Path("bass.m4a"))
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        self.assertIn("aac", command)
        self.assertEqual(command[-1], "bass.m4a")

    def test_reports_a_missing_encoder(self) -> None:
        with patch.object(player_package, "AFCONVERT", Path("/nonexistent/afconvert")), \
                patch("audio_io.resolve_ffmpeg_executable", return_value=None):
            with self.assertRaises(PlayerExportError):
                aac_command(Path("bass.wav"), Path("bass.m4a"))


class PlayerPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        for stem in ("vocals", "drums", "bass", "other"):
            write_wav(self.project / f"{stem}.wav", 4.0)
        self.destination = self.root / "Song.stems.zip"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def export(self, **options):
        options.setdefault("converter", fake_converter)
        options.setdefault("tempo_tracker", lambda _project: self.fail("the beat tracker should not run"))
        return export_player_package(self.project, self.destination, source_name="Song", **options)

    def manifest(self) -> dict:
        with zipfile.ZipFile(self.destination) as archive:
            return json.loads(archive.read("player.json"))

    def test_writes_stored_stems_and_the_mix_without_the_playhead(self) -> None:
        progress: list[float] = []
        package = self.export(mix=MIX, include_tempo=False, progress=lambda value, _message: progress.append(value))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(
                archive.namelist(), ["player.json", "vocals.m4a", "drums.m4a", "bass.m4a", "other.m4a"]
            )
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
            self.assertEqual(archive.read("bass.m4a"), b"aac:bass")
        manifest = self.manifest()
        self.assertEqual(manifest["format"], "stem-studio-player")
        self.assertEqual(manifest["sourceName"], "Song")
        self.assertEqual(manifest["state"], {key: MIX[key] for key in ("startMarkerSeconds", "masterVolume", "tracks")})
        self.assertNotIn("tempo", manifest)
        self.assertEqual((package.tempo_bpm, package.tempo_source), (None, None))
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.0)

    def test_prefers_the_most_recent_transcription_tempo(self) -> None:
        transcription = self.project / "transcription"
        transcription.mkdir()
        beats = [{"beatIndex": index, "timeSeconds": 0.5 + index * 0.4} for index in range(8)]
        for track, bpm, age in (("bass", 150.0, 100), ("drums", 152.0, 0)):
            path = transcription / f"{track}.json"
            path.write_text(json.dumps({"tempoMap": {"bpm": bpm, "beats": beats, "timeSignature": {"numerator": 3}}}))
            os.utime(path, (1_000_000 - age, 1_000_000 - age))
        package = self.export()
        tempo = self.manifest()["tempo"]
        self.assertEqual((tempo["bpm"], tempo["beatsPerBar"], tempo["source"]), (152.0, 3, "drums transcription"))
        self.assertEqual(tempo["beats"][1], {"beatIndex": 1, "timeSeconds": 0.9})
        self.assertEqual(package.tempo_source, "drums transcription")

    def test_detects_the_tempo_when_nothing_was_transcribed(self) -> None:
        beats = [{"beatIndex": index, "timeSeconds": index * 0.5} for index in range(8)]
        package = self.export(tempo_tracker=lambda project: {"bpm": 120.0, "beats": beats})
        self.assertEqual(package.tempo_source, "beat tracker")
        self.assertEqual(self.manifest()["tempo"]["beatsPerBar"], 4)

    def test_a_failed_detection_leaves_the_metronome_out(self) -> None:
        def broken_tracker(_project: Path):
            raise RuntimeError("librosa missing")

        package = self.export(tempo_tracker=broken_tracker)
        self.assertIsNone(package.tempo_bpm)
        self.assertNotIn("tempo", self.manifest())

    def test_builds_a_steady_grid_from_a_manual_tempo(self) -> None:
        self.export(manual_tempo=ManualTempo(120.0, downbeat_seconds=1.25))
        tempo = self.manifest()["tempo"]
        self.assertEqual(tempo["source"], "manual tempo")
        self.assertEqual(tempo["beats"][:3], [
            {"beatIndex": -2, "timeSeconds": 0.25},
            {"beatIndex": -1, "timeSeconds": 0.75},
            {"beatIndex": 0, "timeSeconds": 1.25},
        ])
        self.assertEqual(len(tempo["beats"]), 8)

    def test_rejects_bad_requests_and_leaves_no_partial_file(self) -> None:
        (self.project / "other.wav").unlink()
        with self.assertRaisesRegex(PlayerExportError, "other stem"):
            self.export(include_tempo=False)
        write_wav(self.project / "other.wav", 4.0)
        with self.assertRaisesRegex(PlayerExportError, ".zip"):
            export_player_package(self.project, self.root / "song.m4a", source_name="Song", converter=fake_converter)

        def failing_converter(source: Path, destination: Path) -> None:
            if source.stem == "bass":
                raise PlayerExportError("Unable to convert bass.wav to AAC.")
            fake_converter(source, destination)

        with self.assertRaisesRegex(PlayerExportError, "bass.wav"):
            self.export(include_tempo=False, converter=failing_converter)
        self.assertEqual(list(self.root.glob("*.zip*")) + list(self.root.glob(".*.partial")), [])


class ExportCliTest(unittest.TestCase):
    def test_reports_completion_and_errors_as_export_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for stem in ("vocals", "drums", "bass", "other"):
                write_wav(root / f"{stem}.wav", 1.0)
            events = io.StringIO()
            with patch.object(main, "_EVENT_STREAM", events), patch("player_package.convert_to_aac", fake_converter):
                code = main.run([
                    "export-player", str(root), "--output", str(root / "Song.stems.zip"),
                    "--name", "Song", "--mix", json.dumps(MIX), "--no-tempo",
                ])
                failed = main.run(["export-player", str(root / "missing"), "--output", str(root / "x.zip"), "--name", "x"])
            lines = [json.loads(line) for line in events.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(lines[-2]["type"], "export_completed")
        self.assertEqual(lines[-2]["result"]["tempoBpm"], None)
        self.assertTrue(any(line["type"] == "export_progress" for line in lines))
        self.assertEqual(failed, 1)
        self.assertEqual(lines[-1]["type"], "export_error")


if __name__ == "__main__":
    unittest.main()
