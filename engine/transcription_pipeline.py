"""Orchestration from isolated stems to stable JSON, MIDI and MusicXML files."""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable, TypeVar

from basic_pitch_transcriber import BasicPitchBassTranscriber
from bass_event_normalizer import normalize_bass_events
from beat_tracker import LibrosaBeatTracker, stable_beat_source
from drumscript_transcriber import DrumScriptTranscriber
from fretboard import BassFretboardSolver
from midi_export import export_bass_midi, export_drums_midi
from musicxml_export import export_bass_musicxml, export_drums_musicxml
from quantization import quantize_drums, quantize_notes
from transcription_domain import (
    BassTranscriber,
    BassTranscription,
    BeatTracker,
    DrumTranscriber,
    DrumTranscription,
    TranscriptionFiles,
    TranscriptionProgressReporter,
    TranscriptionStage,
    TranscriptionTrack,
    TempoMap,
)

ResultT = TypeVar("ResultT")


class TranscriptionEngine:
    def __init__(
        self,
        *,
        bass_transcriber: BassTranscriber | None = None,
        drum_transcriber: DrumTranscriber | None = None,
        beat_tracker: BeatTracker | None = None,
        models_dir: Path | None = None,
    ) -> None:
        self.bass_transcriber = bass_transcriber or BasicPitchBassTranscriber(models_dir)
        self.drum_transcriber = drum_transcriber or DrumScriptTranscriber()
        self.beat_tracker = beat_tracker or LibrosaBeatTracker()

    def transcribe_bass(
        self,
        audio_path: Path,
        output_dir: Path,
        progress: TranscriptionProgressReporter,
        *,
        beat_source: Path | None = None,
        tuning: tuple[int, ...] = (28, 33, 38, 43),
        subdivision: int = 4,
    ) -> TranscriptionFiles:
        output = _prepare(audio_path, output_dir)
        progress.report("bass", "loading_model", 0.03, "Loading bass transcription model")
        events = _run_stage(
            lambda: tuple(self.bass_transcriber.transcribe(audio_path)),
            "bass",
            "inference",
            progress,
            0.06,
            0.55,
            "Transcribing bass notes",
        )
        minimum_pitch = min(tuning)
        maximum_pitch = max(tuning) + 24
        playable_events = tuple(
            event for event in events if minimum_pitch <= event.midi_pitch <= maximum_pitch
        )
        normalized_events = normalize_bass_events(playable_events)
        progress.report("bass", "beat_tracking", 0.58, "Detecting tempo and beats")
        with stable_beat_source(audio_path, beat_source, output) as stable_source:
            tempo_map = _run_stage(
                lambda: self.beat_tracker.track(stable_source),
                "bass",
                "beat_tracking",
                progress,
                0.58,
                0.72,
                "Detecting tempo and beats",
            )
        progress.report("bass", "quantization", 0.74, "Quantizing bass notes")
        quantized = quantize_notes(normalized_events, tempo_map, subdivision)
        progress.report("bass", "fretboard", 0.8, "Finding playable bass positions")
        tab = BassFretboardSolver(tuning=tuning).solve(quantized)
        discarded_count = len(events) - len(playable_events)
        warnings = (
            (f"{discarded_count} detected note(s) fell outside the configured bass range.",)
            if discarded_count
            else ()
        )
        normalized_count = len(playable_events) - len(normalized_events)
        if normalized_count:
            warnings += (
                f"{normalized_count} overlapping bass candidate(s) were removed by monophonic normalization.",
            )
        warnings += _tempo_ambiguity_warnings(tempo_map)
        if len(tab) != len(quantized):
            warnings += ("Some notes could not be placed on the configured fretboard.",)
        transcription = BassTranscription(
            quantized,
            tab,
            tempo_map,
            tuning,
            warnings,
            self.bass_transcriber.model_id,
            normalized_events,
        )
        progress.report("bass", "export", 0.86, "Writing MIDI and MusicXML")
        json_path = _write_json(output / "bass.json", transcription.to_payload())
        midi_path = export_bass_midi(quantized, tempo_map, output / "bass.mid")
        xml_path = export_bass_musicxml(
            quantized,
            tab,
            tempo_map,
            output / "bass.musicxml",
            tuning=tuning,
        )
        progress.report("bass", "completed", 1, "Bass transcription completed")
        return TranscriptionFiles(json_path, midi_path, xml_path, transcription)

    def transcribe_drums(
        self,
        audio_path: Path,
        output_dir: Path,
        progress: TranscriptionProgressReporter,
        *,
        beat_source: Path | None = None,
        subdivision: int = 4,
    ) -> TranscriptionFiles:
        output = _prepare(audio_path, output_dir)
        progress.report("drums", "loading_model", 0.03, "Loading drum transcription model")
        events = _run_stage(
            lambda: tuple(self.drum_transcriber.transcribe(audio_path)),
            "drums",
            "inference",
            progress,
            0.06,
            0.58,
            "Transcribing drum hits",
        )
        progress.report("drums", "beat_tracking", 0.61, "Detecting tempo and beats")
        with stable_beat_source(audio_path, beat_source, output) as stable_source:
            tempo_map = _run_stage(
                lambda: self.beat_tracker.track(stable_source),
                "drums",
                "beat_tracking",
                progress,
                0.61,
                0.76,
                "Detecting tempo and beats",
            )
        progress.report("drums", "quantization", 0.79, "Quantizing drum hits")
        quantized = quantize_drums(events, tempo_map, subdivision)
        transcription = DrumTranscription(
            quantized,
            tempo_map,
            (
                "Automatic drum classification may need manual review for dense cymbal and tom passages.",
                *_tempo_ambiguity_warnings(tempo_map),
            ),
            events,
        )
        progress.report("drums", "export", 0.86, "Writing MIDI and MusicXML")
        json_path = _write_json(output / "drums.json", transcription.to_payload())
        midi_path = export_drums_midi(quantized, tempo_map, output / "drums.mid")
        xml_path = export_drums_musicxml(quantized, tempo_map, output / "drums.musicxml")
        progress.report("drums", "completed", 1, "Drum transcription completed")
        return TranscriptionFiles(json_path, midi_path, xml_path, transcription)


def _prepare(audio_path: Path, output_dir: Path) -> Path:
    source = audio_path.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".wav":
        from errors import TranscriptionError

        raise TranscriptionError("The selected stem could not be found.", str(source))
    output = output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    return output


def _tempo_ambiguity_warnings(tempo_map: TempoMap) -> tuple[str, ...]:
    candidates = tempo_map.tempo_candidates
    alternatives = [candidate for candidate in candidates if abs(candidate - tempo_map.bpm) > 0.01]
    if not alternatives:
        return ()
    values = ", ".join(f"{candidate:.1f}" for candidate in alternatives)
    return (f"Metric tempo is ambiguous; plausible alternative(s): {values} BPM.",)


def _run_stage(
    operation: Callable[[], ResultT],
    track: TranscriptionTrack,
    stage: TranscriptionStage,
    reporter: TranscriptionProgressReporter,
    start: float,
    end: float,
    message: str,
) -> ResultT:
    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"transcribe-{track}") as executor:
        future = executor.submit(operation)
        while True:
            try:
                return future.result(timeout=1.5)
            except FutureTimeout:
                elapsed = time.monotonic() - started_at
                fraction = 1 - math.exp(-elapsed / 50)
                reporter.report(track, stage, min(end, start + (end - start) * fraction), message)


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
