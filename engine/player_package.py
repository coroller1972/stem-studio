"""Pack a stem project into one file for the iPhone stem player.

The package, "<song>.stems.zip", holds the four stems as AAC and a player.json
manifest with the song name, the mix and start marker, and the beat grid the
player's metronome follows. Entries are stored uncompressed so the phone can
read each stem in place without inflating the archive.

Tempo comes, in order, from a manual tempo, from the most recently updated
bass or drums transcription (which includes any tempo corrected in Stem
Studio), or from the beat tracker run on the four stems. The tracker's result
is cached in the project as tempo.json, which Stem Studio's metronome shares.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

STEMS = ("vocals", "drums", "bass", "other")
PACKAGE_FORMAT = "stem-studio-player"
PACKAGE_VERSION = 1
MIX_KEYS = ("startMarkerSeconds", "masterVolume", "tracks")
TEMPO_CACHE_NAME = "tempo.json"
# Bump when the beat tracker changes, so cached tempos are detected again.
TEMPO_CACHE_VERSION = 2

Progress = Callable[[float, str], None]
Converter = Callable[[Path, Path], None]


class PlayerExportError(RuntimeError):
    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message


class TempoTracker(Protocol):
    def __call__(self, project_dir: Path) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ManualTempo:
    bpm: float
    downbeat_seconds: float = 0.0


@dataclass(frozen=True)
class PlayerPackage:
    path: Path
    tempo_bpm: float | None
    tempo_source: str | None

    def to_payload(self) -> dict[str, object]:
        return {"path": str(self.path), "tempoBpm": self.tempo_bpm, "tempoSource": self.tempo_source}


def export_player_package(
    project_dir: Path,
    destination: Path,
    *,
    source_name: str,
    mix: Mapping[str, object] | None = None,
    manual_tempo: ManualTempo | None = None,
    beats_per_bar: int | None = None,
    include_tempo: bool = True,
    progress: Progress = lambda _progress, _message: None,
    converter: Converter | None = None,
    tempo_tracker: TempoTracker | None = None,
) -> PlayerPackage:
    project = project_dir.expanduser().resolve()
    missing = [stem for stem in STEMS if not (project / f"{stem}.wav").is_file()]
    if missing:
        raise PlayerExportError(f"The {', '.join(missing)} stem could not be found.")
    if manual_tempo is not None and not 20 <= manual_tempo.bpm <= 400:
        raise PlayerExportError("Tempo must be between 20 and 400 BPM.")
    if beats_per_bar is not None and not 1 <= beats_per_bar <= 16:
        raise PlayerExportError("Beats per bar must be between 1 and 16.")
    target = destination.expanduser()
    if target.suffix.lower() != ".zip":
        raise PlayerExportError("The iPhone package must be saved as a .zip file.")
    if not target.parent.is_dir():
        raise PlayerExportError("The selected export folder could not be found.")

    manifest: dict[str, object] = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "sourceName": source_name.strip() or "Session",
        "stems": {stem: f"{stem}.m4a" for stem in STEMS},
    }
    if mix:
        manifest["state"] = {key: mix[key] for key in MIX_KEYS if key in mix}
    tempo = None
    if include_tempo:
        progress(0.05, "Finding the song's tempo")
        tempo = choose_tempo(project, manual_tempo, beats_per_bar, tempo_tracker or track_tempo, progress)
        if tempo:
            manifest["tempo"] = tempo

    convert = converter or convert_to_aac
    partial = target.with_name(f".{target.name}.partial")
    try:
        with tempfile.TemporaryDirectory(prefix="stem-player-") as work:
            work_dir = Path(work)
            for index, stem in enumerate(STEMS):
                progress(0.4 + 0.12 * index, f"Converting the {stem} stem")
                convert(project / f"{stem}.wav", work_dir / f"{stem}.m4a")
            progress(0.9, "Writing the package")
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("player.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
                for stem in STEMS:
                    archive.write(work_dir / f"{stem}.m4a", f"{stem}.m4a")
        partial.replace(target)
    except OSError as error:
        raise PlayerExportError("Unable to write the iPhone package.", str(error)) from error
    finally:
        partial.unlink(missing_ok=True)
    progress(1.0, "iPhone package ready")
    return PlayerPackage(
        path=target,
        tempo_bpm=float(tempo["bpm"]) if tempo else None,
        tempo_source=str(tempo["source"]) if tempo else None,
    )


def choose_tempo(
    project: Path,
    manual: ManualTempo | None,
    beats_per_bar: int | None,
    tracker: TempoTracker,
    progress: Progress,
) -> dict[str, object] | None:
    if manual is not None:
        period = 60.0 / manual.bpm
        first = manual.downbeat_seconds % period
        index_offset = -round((manual.downbeat_seconds - first) / period)
        count = int((wav_duration(project / "vocals.wav") - first) / period) + 1
        beats = [{"beatIndex": index_offset + index, "timeSeconds": first + index * period} for index in range(count)]
        return tempo_payload(manual.bpm, beats_per_bar or 4, beats, "manual tempo")

    transcriptions = sorted(
        (path for path in (project / "transcription" / f"{track}.json" for track in ("bass", "drums")) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in transcriptions:
        tempo_map = (read_json(path) or {}).get("tempoMap")
        if valid_tempo_map(tempo_map):
            signature = tempo_map.get("timeSignature")
            numerator = signature.get("numerator") if isinstance(signature, dict) else None
            bar = beats_per_bar or (numerator if isinstance(numerator, int) and 1 <= numerator <= 16 else 4)
            return tempo_payload(tempo_map["bpm"], bar, tempo_map["beats"], f"{path.stem} transcription")

    progress(0.1, "Detecting the tempo")
    try:
        tempo = detected_tempo(project, tracker)
    except Exception:  # The package stays useful without a metronome.
        return None
    if tempo is None:
        return None
    return {**tempo, "beatsPerBar": beats_per_bar or tempo["beatsPerBar"]}


def detected_tempo(project: Path, tracker: TempoTracker | None = None) -> dict[str, object] | None:
    """The beat tracker's tempo for the project's four stems, or None when it finds none.

    The result, a miss included, is kept in tempo.json next to the stems, so
    the desktop metronome and later exports reuse it instead of re-running the
    tracker. A failure raises and caches nothing.
    """
    fingerprint = stems_fingerprint(project)
    cached = read_tempo_cache(project / TEMPO_CACHE_NAME, fingerprint)
    if cached is not None:
        return cached["tempo"]  # type: ignore[return-value]
    tempo_map = (tracker or track_tempo)(project)
    tempo = (
        tempo_payload(tempo_map["bpm"], 4, tempo_map["beats"], "beat tracker")  # type: ignore[index]
        if valid_tempo_map(tempo_map)
        else None
    )
    write_tempo_cache(project / TEMPO_CACHE_NAME, {"version": TEMPO_CACHE_VERSION, "stems": fingerprint, "tempo": tempo})
    return tempo


def stems_fingerprint(project: Path) -> dict[str, int]:
    """Stem sizes: enough to tell another separation apart, and unchanged by copying a session."""
    sizes: dict[str, int] = {}
    for stem in STEMS:
        path = project / f"{stem}.wav"
        if not path.is_file():
            raise PlayerExportError(f"The {stem} stem could not be found.")
        sizes[stem] = path.stat().st_size
    return sizes


def read_tempo_cache(path: Path, fingerprint: Mapping[str, int]) -> Mapping[str, object] | None:
    cache = read_json(path)
    if not isinstance(cache, Mapping) or cache.get("version") != TEMPO_CACHE_VERSION or cache.get("stems") != fingerprint:
        return None
    tempo = cache.get("tempo")
    if tempo is not None and not (valid_tempo_map(tempo) and isinstance(tempo, Mapping) and isinstance(tempo.get("beatsPerBar"), int)):
        return None
    return cache


def write_tempo_cache(path: Path, cache: Mapping[str, object]) -> None:
    partial = path.with_name(f".{path.name}.partial")
    try:
        partial.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(partial, path)
    except OSError:  # A read-only project simply detects the tempo again next time.
        partial.unlink(missing_ok=True)


def track_tempo(project: Path) -> Mapping[str, object]:
    from beat_tracker import LibrosaBeatTracker, stable_beat_source

    with tempfile.TemporaryDirectory(prefix="stem-player-beats-") as work:
        with stable_beat_source(project / "vocals.wav", None, Path(work)) as mix:
            return LibrosaBeatTracker().track(mix).to_payload()


AFCONVERT = Path("/usr/bin/afconvert")


def aac_command(source: Path, destination: Path) -> list[str]:
    if AFCONVERT.is_file():
        # High-quality VBR AAC keeps each stem at a few megabytes and, unlike a
        # fixed bit rate, accepts any sample rate. afconvert ships with macOS.
        return [str(AFCONVERT), "-f", "m4af", "-d", "aac", "-s", "3", "-u", "vbrq", "110", "-q", "127",
                str(source), str(destination)]

    from audio_io import resolve_ffmpeg_executable

    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        raise PlayerExportError("Unable to convert stems to AAC.", "ffmpeg executable not found")
    # Elsewhere (Linux), FFmpeg's native AAC encoder is LGPL-compatible. 192 kb/s
    # stereo is close to afconvert's VBR quality 110 and works at any sample rate.
    return [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-vn", "-map_metadata", "-1", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-f", "mp4", str(destination)]


def convert_to_aac(source: Path, destination: Path) -> None:
    result = subprocess.run(aac_command(source, destination), capture_output=True, text=True)
    if result.returncode != 0:
        raise PlayerExportError(f"Unable to convert {source.name} to AAC.", result.stderr.strip() or None)


def tempo_payload(bpm: object, beats_per_bar: int, beats: list, origin: str) -> dict[str, object]:
    return {
        "bpm": round(float(bpm), 3),  # type: ignore[arg-type]
        "beatsPerBar": int(beats_per_bar),
        "beats": [{"beatIndex": int(beat["beatIndex"]), "timeSeconds": round(float(beat["timeSeconds"]), 4)} for beat in beats],
        "source": origin,
    }


def valid_tempo_map(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    bpm, beats = value.get("bpm"), value.get("beats")
    return (
        isinstance(bpm, (int, float))
        and 20 <= bpm <= 400
        and isinstance(beats, list)
        and len(beats) >= 2
        and all(isinstance(beat, Mapping) and "beatIndex" in beat and "timeSeconds" in beat for beat in beats)
    )


def wav_duration(path: Path) -> float:
    """Read the duration from the RIFF header; the stdlib wave module rejects float WAVs."""
    with path.open("rb") as handle:
        riff, _, wave = struct.unpack("<4sI4s", handle.read(12))
        if riff != b"RIFF" or wave != b"WAVE":
            raise PlayerExportError(f"{path.name} is not a WAV file.")
        byte_rate = None
        while header := handle.read(8):
            chunk, size = struct.unpack("<4sI", header)
            if chunk == b"fmt ":
                byte_rate = struct.unpack("<HHII", handle.read(12))[3]
                handle.seek(size - 12 + size % 2, os.SEEK_CUR)
            elif chunk == b"data":
                if byte_rate:
                    return size / byte_rate
                break
            else:
                handle.seek(size + size % 2, os.SEEK_CUR)
    raise PlayerExportError(f"{path.name} has no readable audio data.")


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None
