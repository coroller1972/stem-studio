"""Model-independent musical transcription contracts and serializable values."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, Sequence, runtime_checkable

DrumInstrument = Literal[
    "kick",
    "snare",
    "closed_hihat",
    "open_hihat",
    "ride",
    "crash",
    "high_tom",
    "mid_tom",
    "low_tom",
    "other",
]
TranscriptionTrack = Literal["bass", "drums"]
TranscriptionStage = Literal[
    "loading_model",
    "inference",
    "beat_tracking",
    "quantization",
    "fretboard",
    "export",
    "completed",
]


@dataclass(frozen=True)
class PitchBendPoint:
    time_offset_seconds: float
    semitones: float

    def __post_init__(self) -> None:
        if self.time_offset_seconds < 0:
            raise ValueError("Pitch-bend offsets cannot be negative.")
        if not -12 <= self.semitones <= 12:
            raise ValueError("Pitch bends must remain within one octave.")

    def to_payload(self) -> dict[str, float]:
        return {
            "timeOffsetSeconds": self.time_offset_seconds,
            "semitones": self.semitones,
        }


@dataclass(frozen=True)
class TempoBeat:
    beat_index: int
    time_seconds: float

    def to_payload(self) -> dict[str, int | float]:
        return {"beatIndex": self.beat_index, "timeSeconds": self.time_seconds}


@dataclass(frozen=True)
class TimeSignature:
    numerator: int = 4
    denominator: int = 4

    def __post_init__(self) -> None:
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("Time signature values must be positive.")

    def to_payload(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}


@dataclass(frozen=True)
class TempoMap:
    bpm: float
    beats: tuple[TempoBeat, ...]
    time_signature: TimeSignature = field(default_factory=TimeSignature)
    tempo_candidates: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not 20 <= self.bpm <= 400:
            raise ValueError("Tempo must be between 20 and 400 BPM.")
        if any(beat.time_seconds < 0 for beat in self.beats):
            raise ValueError("Beat timestamps cannot be negative.")
        if any(right.time_seconds <= left.time_seconds for left, right in zip(self.beats, self.beats[1:])):
            raise ValueError("Beat timestamps must be strictly increasing.")
        if any(not 20 <= candidate <= 400 for candidate in self.tempo_candidates):
            raise ValueError("Tempo candidates must be between 20 and 400 BPM.")

    def to_payload(self) -> dict[str, object]:
        return {
            "bpm": self.bpm,
            "beats": [beat.to_payload() for beat in self.beats],
            "timeSignature": self.time_signature.to_payload(),
            "tempoCandidates": list(self.tempo_candidates),
        }


@dataclass(frozen=True)
class NoteEvent:
    id: str
    detected_start_seconds: float
    detected_end_seconds: float
    midi_pitch: int
    velocity: int
    confidence: float | None = None
    quantized_start_beat: float | None = None
    quantized_duration_beats: float | None = None
    pitch_bends: tuple[PitchBendPoint, ...] = ()

    def __post_init__(self) -> None:
        if self.detected_start_seconds < 0 or self.detected_end_seconds <= self.detected_start_seconds:
            raise ValueError("A note must have a positive duration and non-negative start.")
        if not 0 <= self.midi_pitch <= 127 or not 1 <= self.velocity <= 127:
            raise ValueError("MIDI pitch and velocity are outside their valid ranges.")
        duration = self.detected_end_seconds - self.detected_start_seconds
        if any(point.time_offset_seconds > duration for point in self.pitch_bends):
            raise ValueError("Pitch-bend points must fall within their note.")

    def quantized(self, start_beat: float, duration_beats: float) -> "NoteEvent":
        return replace(self, quantized_start_beat=start_beat, quantized_duration_beats=duration_beats)

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "detectedStartSeconds": self.detected_start_seconds,
            "detectedEndSeconds": self.detected_end_seconds,
            "quantizedStartBeat": self.quantized_start_beat,
            "quantizedDurationBeats": self.quantized_duration_beats,
            "midiPitch": self.midi_pitch,
            "velocity": self.velocity,
            "confidence": self.confidence,
            "pitchBends": [point.to_payload() for point in self.pitch_bends],
        }


@dataclass(frozen=True)
class DrumEvent:
    id: str
    detected_time_seconds: float
    instrument: DrumInstrument
    velocity: int
    confidence: float | None = None
    quantized_beat: float | None = None

    def __post_init__(self) -> None:
        if self.detected_time_seconds < 0:
            raise ValueError("A drum event timestamp cannot be negative.")
        if not 1 <= self.velocity <= 127:
            raise ValueError("MIDI velocity is outside its valid range.")

    def quantized(self, beat: float) -> "DrumEvent":
        return replace(self, quantized_beat=beat)

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "detectedTimeSeconds": self.detected_time_seconds,
            "quantizedBeat": self.quantized_beat,
            "instrument": self.instrument,
            "velocity": self.velocity,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TabNote:
    note_event_id: str
    string_index: int
    fret: int
    start_beat: float
    duration_beats: float

    def to_payload(self) -> dict[str, object]:
        return {
            "noteEventId": self.note_event_id,
            "stringIndex": self.string_index,
            "fret": self.fret,
            "startBeat": self.start_beat,
            "durationBeats": self.duration_beats,
        }


@dataclass(frozen=True)
class BassTranscription:
    events: tuple[NoteEvent, ...]
    tab: tuple[TabNote, ...]
    tempo_map: TempoMap
    tuning: tuple[int, ...] = (28, 33, 38, 43)
    warnings: tuple[str, ...] = ()
    model_id: str = "unknown"
    source_events: tuple[NoteEvent, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 3,
            "track": "bass",
            "events": [event.to_payload() for event in self.events],
            "tab": [note.to_payload() for note in self.tab],
            "tempoMap": self.tempo_map.to_payload(),
            "tuning": list(self.tuning),
            "warnings": list(self.warnings),
            "modelId": self.model_id,
            "sourceEvents": [event.to_payload() for event in (self.source_events or self.events)],
        }


@dataclass(frozen=True)
class DrumTranscription:
    events: tuple[DrumEvent, ...]
    tempo_map: TempoMap
    warnings: tuple[str, ...] = ()
    source_events: tuple[DrumEvent, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 2,
            "track": "drums",
            "events": [event.to_payload() for event in self.events],
            "tempoMap": self.tempo_map.to_payload(),
            "warnings": list(self.warnings),
            "sourceEvents": [event.to_payload() for event in (self.source_events or self.events)],
        }


@dataclass(frozen=True)
class TranscriptionFiles:
    events_file: Path
    midi_file: Path
    music_xml_file: Path
    transcription: BassTranscription | DrumTranscription

    def result_payload(self) -> dict[str, object]:
        return {
            "eventsFile": str(self.events_file),
            "midiFile": str(self.midi_file),
            "musicXmlFile": str(self.music_xml_file),
            "transcription": self.transcription.to_payload(),
        }


@dataclass(frozen=True)
class TranscriptionProgress:
    track: TranscriptionTrack
    stage: TranscriptionStage
    progress: float
    message: str


class TranscriptionProgressReporter:
    def __init__(self, callback: Callable[[TranscriptionProgress], None]) -> None:
        self._callback = callback

    def report(
        self,
        track: TranscriptionTrack,
        stage: TranscriptionStage,
        progress: float,
        message: str,
    ) -> None:
        self._callback(
            TranscriptionProgress(track, stage, min(1.0, max(0.0, progress)), message)
        )


@runtime_checkable
class BassTranscriber(Protocol):
    model_id: str

    def transcribe(self, audio_path: Path) -> Sequence[NoteEvent]: ...


@runtime_checkable
class DrumTranscriber(Protocol):
    model_id: str

    def transcribe(self, audio_path: Path) -> Sequence[DrumEvent]: ...


@runtime_checkable
class BeatTracker(Protocol):
    def track(self, audio_path: Path) -> TempoMap: ...
