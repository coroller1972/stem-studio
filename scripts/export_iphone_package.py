#!/usr/bin/env python3
"""Pack a Stem Studio session or project into one file for the iPhone player.

The result, "<song>.stems.zip", holds the four stems as AAC and a player.json
manifest with the song name, the saved mix and start marker, and the beat grid
the player's metronome follows. Entries are stored uncompressed so the phone
can read each stem in place without inflating the archive.

Tempo comes, in order, from --bpm, from the most recently updated bass or drums
transcription (which includes any tempo corrected in Stem Studio), or from the
engine's beat tracker run on the four stems.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

STEMS = ("vocals", "drums", "bass", "other")
REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
PACKAGE_FORMAT = "stem-studio-player"
PACKAGE_VERSION = 1

BEAT_TRACKER_SCRIPT = """
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from beat_tracker import LibrosaBeatTracker, stable_beat_source
source = Path(sys.argv[2])
with tempfile.TemporaryDirectory() as work, stable_beat_source(source / "vocals.wav", None, Path(work)) as mix:
    print(json.dumps(LibrosaBeatTracker().track(mix).to_payload()))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="a .stemstudio session or a folder with vocals/drums/bass/other.wav")
    parser.add_argument("output", type=Path, help="folder that receives <song>.stems.zip")
    parser.add_argument("--name", help="song name (default: the session's source name, else the folder name)")
    parser.add_argument("--bpm", type=float, help="use a steady tempo instead of the detected one")
    parser.add_argument("--downbeat", type=float, default=0.0, help="with --bpm: time in seconds of a bar's first beat")
    parser.add_argument("--beats-per-bar", type=int, help="beats per bar (default: from the transcription, else 4)")
    parser.add_argument("--no-tempo", action="store_true", help="leave the metronome out")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    missing = [stem for stem in STEMS if not (source / f"{stem}.wav").is_file()]
    if missing:
        parser.error(f"{source} has no {', '.join(f'{stem}.wav' for stem in missing)}")
    if args.bpm is not None and not 20 <= args.bpm <= 400:
        parser.error("--bpm must be between 20 and 400")
    if args.beats_per_bar is not None and not 1 <= args.beats_per_bar <= 16:
        parser.error("--beats-per-bar must be between 1 and 16")

    session = read_json(source / "session.json") or {}
    song = song_name(args.name, session, source)
    manifest: dict[str, object] = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "sourceName": song,
        "stems": {stem: f"{stem}.m4a" for stem in STEMS},
    }
    state = session.get("state")
    if isinstance(state, dict):
        manifest["state"] = {key: state[key] for key in ("startMarkerSeconds", "masterVolume", "tracks") if key in state}
    if not args.no_tempo:
        tempo = choose_tempo(source, args)
        if tempo:
            manifest["tempo"] = tempo
            print(f"Tempo: {tempo['bpm']:.1f} BPM, {tempo['beatsPerBar']} beats per bar ({tempo['source']})")
        else:
            print("No tempo found: the package has no metronome.", file=sys.stderr)

    output_dir = args.output.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    package = output_dir / f"{song}.stems.zip"
    with tempfile.TemporaryDirectory(prefix="stem-player-") as work:
        work_dir = Path(work)
        for stem in STEMS:
            # High-quality VBR AAC keeps each stem at a few megabytes and, unlike
            # a fixed bit rate, accepts any sample rate.
            subprocess.run(
                ["/usr/bin/afconvert", "-f", "m4af", "-d", "aac", "-s", "3", "-u", "vbrq", "110", "-q", "127",
                 str(source / f"{stem}.wav"), str(work_dir / f"{stem}.m4a")],
                check=True,
            )
        partial = package.with_name(f".{package.name}.partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("player.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
            for stem in STEMS:
                archive.write(work_dir / f"{stem}.m4a", f"{stem}.m4a")
        partial.replace(package)
    print(f"Wrote {package} ({package.stat().st_size / 1024 ** 2:.1f} MB)")
    return 0


def song_name(requested: str | None, session: dict, source: Path) -> str:
    name = requested or ""
    if not name and isinstance(session.get("sourceName"), str):
        name = Path(session["sourceName"]).stem
    name = name or source.name.removesuffix(".stemstudio")
    return name.replace("/", "-").strip() or "Session"


def choose_tempo(source: Path, args: argparse.Namespace) -> dict | None:
    if args.bpm is not None:
        period = 60.0 / args.bpm
        first = args.downbeat % period
        index_offset = -round((args.downbeat - first) / period)
        count = int((wav_duration(source / "vocals.wav") - first) / period) + 1
        beats = [{"beatIndex": index_offset + index, "timeSeconds": round(first + index * period, 4)} for index in range(count)]
        return tempo_payload(args.bpm, args.beats_per_bar or 4, beats, "manual")

    transcriptions = sorted(
        (path for path in (source / "transcription" / f"{track}.json" for track in ("bass", "drums")) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in transcriptions:
        tempo_map = (read_json(path) or {}).get("tempoMap")
        if valid_tempo_map(tempo_map):
            beats_per_bar = args.beats_per_bar or int(tempo_map.get("timeSignature", {}).get("numerator", 4))
            return tempo_payload(tempo_map["bpm"], beats_per_bar, tempo_map["beats"], f"{path.stem} transcription")

    python = engine_python()
    if python is None:
        return None
    print("Detecting the tempo with the engine's beat tracker…")
    result = subprocess.run(
        [str(python), "-I", "-c", BEAT_TRACKER_SCRIPT, str(ENGINE_DIR), str(source)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Beat tracking failed.", file=sys.stderr)
        return None
    tempo_map = json.loads(result.stdout.strip().splitlines()[-1])
    if not valid_tempo_map(tempo_map):
        return None
    return tempo_payload(tempo_map["bpm"], args.beats_per_bar or 4, tempo_map["beats"], "beat tracker")


def tempo_payload(bpm: float, beats_per_bar: int, beats: list[dict], origin: str) -> dict:
    return {
        "bpm": round(float(bpm), 3),
        "beatsPerBar": beats_per_bar,
        "beats": [{"beatIndex": int(beat["beatIndex"]), "timeSeconds": round(float(beat["timeSeconds"]), 4)} for beat in beats],
        "source": origin,
    }


def valid_tempo_map(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("bpm"), (int, float))
        and 20 <= value["bpm"] <= 400
        and isinstance(value.get("beats"), list)
        and len(value["beats"]) >= 2
    )


def engine_python() -> Path | None:
    candidates = [os.environ.get("STEM_STUDIO_PYTHON"), ENGINE_DIR / ".venv311/bin/python", ENGINE_DIR / ".venv/bin/python"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def wav_duration(path: Path) -> float:
    """Read the duration from the RIFF header; the stdlib wave module rejects float WAVs."""
    with path.open("rb") as handle:
        riff, _, wave = struct.unpack("<4sI4s", handle.read(12))
        if riff != b"RIFF" or wave != b"WAVE":
            raise ValueError(f"{path} is not a WAV file")
        byte_rate = None
        while header := handle.read(8):
            chunk, size = struct.unpack("<4sI", header)
            if chunk == b"fmt ":
                byte_rate = struct.unpack("<HHII", handle.read(12))[3]
                handle.seek(size - 12 + size % 2, os.SEEK_CUR)
            elif chunk == b"data":
                if not byte_rate:
                    break
                return size / byte_rate
            else:
                handle.seek(size + size % 2, os.SEEK_CUR)
    raise ValueError(f"{path} has no readable audio data")


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


if __name__ == "__main__":
    sys.exit(main())
