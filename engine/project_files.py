"""Backend-independent project validation and metadata persistence."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from domain import StemResult
from errors import SeparationError

MIN_FREE_BYTES = 2 * 1024**3
MAX_INPUT_BYTES = 1024**3
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav"})


def prepare_project(
    input_path: Path,
    output_dir: Path,
    *,
    profile_id: str,
    backend_id: str,
    model_id: str,
) -> tuple[Path, Path]:
    source = input_path.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    validate_input(source)
    output.mkdir(parents=True, exist_ok=True)
    validate_disk_space(source, output)
    write_source_metadata(
        source,
        output,
        profile_id=profile_id,
        backend_id=backend_id,
        model_id=model_id,
    )
    return source, output


def validate_input(source: Path) -> None:
    if not source.is_file():
        raise SeparationError("Audio file could not be found.", str(source))
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise SeparationError("Unable to decode this audio file.", "Only MP3 and WAV are supported.")
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise SeparationError(
            "Audio file is too large.",
            "Stem Studio accepts source files up to 1 GiB.",
        )


def validate_disk_space(source: Path, output: Path) -> None:
    required = max(MIN_FREE_BYTES, source.stat().st_size * 12)
    free = shutil.disk_usage(output).free
    if free < required:
        raise SeparationError(
            "Not enough disk space.",
            f"Need approximately {required} bytes but only {free} bytes are available.",
        )


def write_source_metadata(
    source: Path,
    output: Path,
    *,
    profile_id: str,
    backend_id: str,
    model_id: str,
) -> None:
    metadata = {
        "sourcePath": str(source),
        "sourceName": source.name,
        "qualityProfile": profile_id,
        "backend": backend_id,
        "model": model_id,
        "createdAtUnix": int(time.time()),
    }
    (output / "source.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def write_result_metadata(output: Path, result: StemResult) -> None:
    metadata_path = output / "source.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    metadata["separation"] = result.metadata_payload()
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
