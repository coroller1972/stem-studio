"""Central mappings between drum transcription engines and General MIDI."""

from __future__ import annotations

from transcription_domain import DrumInstrument

GENERAL_MIDI_DRUM_NOTES: dict[DrumInstrument, int] = {
    "kick": 36,
    "snare": 38,
    "closed_hihat": 42,
    "open_hihat": 46,
    "ride": 51,
    "crash": 49,
    "high_tom": 50,
    "mid_tom": 47,
    "low_tom": 45,
    "other": 39,
}

_ADTOF_LABELS: dict[int, DrumInstrument] = {
    35: "kick",
    36: "kick",
    38: "snare",
    42: "closed_hihat",
    47: "mid_tom",
    49: "crash",
}

_ADTOF_NAMES: dict[str, DrumInstrument] = {
    "kick": "kick",
    "bass_drum": "kick",
    "snare": "snare",
    "hihat": "closed_hihat",
    "hi_hat": "closed_hihat",
    "closed_hihat": "closed_hihat",
    "open_hihat": "open_hihat",
    "tom": "mid_tom",
    "high_tom": "high_tom",
    "mid_tom": "mid_tom",
    "low_tom": "low_tom",
    "cymbal": "crash",
    "crash": "crash",
    "ride": "ride",
    "hi_hat_closed": "closed_hihat",
    "hi_hat_open": "open_hihat",
    "unknown": "other",
    "other": "other",
}


def normalize_adtof_instrument(value: int | str) -> DrumInstrument:
    if isinstance(value, int):
        return _ADTOF_LABELS.get(value, "other")
    normalized = value.strip().lower().replace("-", " ").replace(" ", "_")
    return _ADTOF_NAMES.get(normalized, "other")


def normalize_drum_instrument(value: int | str) -> DrumInstrument:
    """Normalize an ADTOF or DrumScript class into the public domain type."""

    return normalize_adtof_instrument(value)


def general_midi_note(instrument: DrumInstrument) -> int:
    return GENERAL_MIDI_DRUM_NOTES[instrument]
