#!/usr/bin/env python3
"""JSON-lines CLI entry point for the Stem Studio separation engine."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from domain import CallbackProgressReporter
from errors import SeparationError, TranscriptionError
from factory import create_separator
from registry import DEFAULT_PROFILE_ID, PROFILE_REGISTRY, get_profile
from transcription_domain import TranscriptionProgressReporter
from transcription_pipeline import TranscriptionEngine
from transcription_requantizer import requantize_transcription

_EVENT_STREAM = sys.stdout


def emit(event: dict[str, Any]) -> None:
    # BS-RoFormer temporarily redirects the process-wide sys.stdout from a worker
    # thread. Keep protocol events pinned to the original stream so Tauri receives
    # heartbeat updates immediately while dependency logs continue to stderr.
    print(json.dumps(event, ensure_ascii=False), file=_EVENT_STREAM, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stem-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    separate = subparsers.add_parser("separate", help="Separate an MP3 or WAV into four stems")
    separate.add_argument("input", type=Path)
    separate.add_argument("--output", type=Path, required=True)
    separate.add_argument(
        "--quality",
        choices=PROFILE_REGISTRY.ids(),
        default=DEFAULT_PROFILE_ID,
        help="Stable quality profile (default: standard)",
    )
    for command, help_text in (
        ("transcribe-bass", "Transcribe an isolated bass WAV"),
        ("transcribe-drums", "Transcribe an isolated drum WAV"),
    ):
        transcribe = subparsers.add_parser(command, help=help_text)
        transcribe.add_argument("input", type=Path)
        transcribe.add_argument("--output", type=Path, required=True)
        transcribe.add_argument("--beat-source", type=Path)
        if command == "transcribe-bass":
            transcribe.add_argument(
                "--bass-tuning",
                choices=("eadg", "beadg"),
                default="eadg",
                help="Bass tuning used for tablature (default: eadg)",
            )
            transcribe.add_argument(
                "--bass-engine",
                choices=("basic-pitch", "torchcrepe"),
                default="basic-pitch",
                help="Bass note detector used for the A/B prototype (default: basic-pitch)",
            )
    for command, help_text in (
        ("requantize-bass", "Rebuild bass timing and exports from saved events"),
        ("requantize-drums", "Rebuild drum timing and exports from saved events"),
    ):
        requantize = subparsers.add_parser(command, help=help_text)
        requantize.add_argument("input", type=Path, help="Existing bass.json or drums.json")
        requantize.add_argument("--output", type=Path, required=True)
        requantize.add_argument("--bpm", type=float, required=True)
        requantize.add_argument("--first-measure-seconds", type=float, required=True)
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in ("requantize-bass", "requantize-drums"):
            track = "bass" if args.command == "requantize-bass" else "drums"
            reporter = TranscriptionProgressReporter(
                lambda update: emit(
                    {
                        "type": "transcription_progress",
                        "track": update.track,
                        "stage": update.stage,
                        "progress": update.progress,
                        "message": update.message,
                    }
                )
            )
            result = requantize_transcription(
                args.input,
                args.output,
                track,
                args.bpm,
                args.first_measure_seconds,
                reporter,
            )
            emit(
                {
                    "type": "transcription_completed",
                    "track": track,
                    "result": result.result_payload(),
                }
            )
            return 0

        if args.command in ("transcribe-bass", "transcribe-drums"):
            reporter = TranscriptionProgressReporter(
                lambda update: emit(
                    {
                        "type": "transcription_progress",
                        "track": update.track,
                        "stage": update.stage,
                        "progress": update.progress,
                        "message": update.message,
                    }
                )
            )
            models_dir = _models_dir_from_environment()
            if args.command == "transcribe-bass":
                engine = TranscriptionEngine(
                    bass_transcriber=_create_bass_transcriber(args.bass_engine, models_dir),
                    models_dir=models_dir,
                )
                tuning = (23, 28, 33, 38, 43) if args.bass_tuning == "beadg" else (28, 33, 38, 43)
                result = engine.transcribe_bass(
                    args.input,
                    args.output,
                    reporter,
                    beat_source=args.beat_source,
                    tuning=tuning,
                )
                track = "bass"
            else:
                engine = TranscriptionEngine(models_dir=models_dir)
                result = engine.transcribe_drums(
                    args.input, args.output, reporter, beat_source=args.beat_source
                )
                track = "drums"
            emit(
                {
                    "type": "transcription_completed",
                    "track": track,
                    "result": result.result_payload(),
                }
            )
            return 0

        progress = CallbackProgressReporter(
            lambda update: emit(
                {
                    "type": "progress",
                    "progress": update.progress,
                    "message": update.message,
                }
            )
        )
        profile = get_profile(args.quality)
        separator = create_separator(profile)
        result = separator.separate(args.input, args.output, progress)
        emit({"type": "completed", "stems": result.stems_payload()})
        return 0
    except TranscriptionError as error:
        emit({"type": "transcription_error", "message": error.user_message, "detail": str(error)})
        return 1
    except SeparationError as error:
        emit({"type": "error", "message": error.user_message, "detail": str(error)})
        return 1
    except KeyboardInterrupt:
        event_type = "transcription_error" if _is_transcription_command(args.command) else "error"
        emit({"type": event_type, "message": "Operation was cancelled."})
        return 130
    except Exception as error:  # A raw traceback is logged to stderr, never sent to the UI.
        traceback.print_exc(file=sys.stderr)
        event_type = "transcription_error" if _is_transcription_command(args.command) else "error"
        message = "Transcription failed." if _is_transcription_command(args.command) else "Stem separation failed."
        emit({"type": event_type, "message": message, "detail": str(error)})
        return 1


def _models_dir_from_environment() -> Path | None:
    import os

    value = os.environ.get("STEM_STUDIO_MODELS_DIR")
    return Path(value) if value else None


def _is_transcription_command(command: str) -> bool:
    return command.startswith("transcribe-") or command.startswith("requantize-")


def _create_bass_transcriber(engine_id: str, models_dir: Path | None):
    if engine_id == "basic-pitch":
        from basic_pitch_transcriber import BasicPitchBassTranscriber

        return BasicPitchBassTranscriber(models_dir)
    if engine_id == "torchcrepe":
        from torchcrepe_transcriber import TorchCrepeBassTranscriber

        return TorchCrepeBassTranscriber(models_dir)
    raise ValueError(f"Unknown bass transcription engine: {engine_id}")


if __name__ == "__main__":
    raise SystemExit(run())
