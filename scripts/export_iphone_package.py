#!/usr/bin/env python3
"""Pack a Stem Studio session or project into one file for the iPhone player.

Command-line twin of Stem Studio's "Export for iPhone" button: both call
engine/player_package.py. The package, "<song>.stems.zip", holds the four
stems as AAC and player.json with the session's mix and start marker and the
beat grid of the metronome.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"


def engine_python() -> Path | None:
    candidates = [os.environ.get("STEM_STUDIO_PYTHON"), ENGINE_DIR / ".venv311/bin/python", ENGINE_DIR / ".venv/bin/python"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


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

    # Tempo detection needs the engine's dependencies (librosa): run under its Python.
    python = engine_python()
    if python and Path(sys.executable).resolve() != python.resolve() and "STEM_PLAYER_REEXEC" not in os.environ:
        os.environ["STEM_PLAYER_REEXEC"] = "1"
        os.execv(str(python), [str(python), "-I", str(Path(__file__).resolve()), *sys.argv[1:]])

    sys.path.insert(0, str(ENGINE_DIR))
    from player_package import ManualTempo, PlayerExportError, export_player_package

    source = args.source.expanduser().resolve()
    session = read_session(source / "session.json")
    name = args.name or Path(str(session.get("sourceName") or "")).stem or source.name.removesuffix(".stemstudio")
    name = name.replace("/", "-").strip() or "Session"
    output_dir = args.output.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        package = export_player_package(
            source,
            output_dir / f"{name}.stems.zip",
            source_name=name,
            mix=session.get("state") if isinstance(session.get("state"), dict) else None,
            manual_tempo=ManualTempo(args.bpm, args.downbeat) if args.bpm is not None else None,
            beats_per_bar=args.beats_per_bar,
            include_tempo=not args.no_tempo,
            progress=lambda _progress, message: print(f"{message}…", flush=True),
        )
    except PlayerExportError as error:
        print(error.user_message, file=sys.stderr)
        return 1
    tempo = f"{package.tempo_bpm:.1f} BPM from the {package.tempo_source}" if package.tempo_bpm else "no metronome"
    print(f"Wrote {package.path} ({package.path.stat().st_size / 1024 ** 2:.1f} MB, {tempo})")
    return 0


def read_session(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
