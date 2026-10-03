"""All-or-nothing persistence of one track's JSON, MIDI and MusicXML files."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable

from transcription_domain import TranscriptionTrack

FileWriter = Callable[[Path], Path]


def write_transcription_outputs(
    output: Path,
    track: TranscriptionTrack,
    payload: dict[str, object],
    write_midi: FileWriter,
    write_musicxml: FileWriter,
) -> tuple[Path, Path, Path]:
    """Render every file beside its destination, then swap them in together.

    An exporter failure leaves the previous trio untouched, so the JSON never
    describes a timing that the MIDI or MusicXML files do not contain.
    """
    token = uuid.uuid4().hex
    final_paths = (
        output / f"{track}.json",
        output / f"{track}.mid",
        output / f"{track}.musicxml",
    )
    staged_paths = tuple(path.with_name(f".{path.name}.{token}.tmp") for path in final_paths)
    json_staged, midi_staged, xml_staged = staged_paths
    try:
        json_staged.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        write_midi(midi_staged)
        write_musicxml(xml_staged)
        for staged, final in zip(staged_paths, final_paths):
            staged.replace(final)
    finally:
        for staged in staged_paths:
            staged.unlink(missing_ok=True)
    return final_paths
