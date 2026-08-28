#!/usr/bin/env python3
"""Print stable quality metrics for a Stem Studio bass transcription JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bass_event_normalizer import normalize_bass_events
from bass_quality import measure_bass_quality
from quantization import quantize_notes
from transcription_domain import NoteEvent, PitchBendPoint, TempoBeat, TempoMap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcription", type=Path, help="Path to bass.json")
    parser.add_argument(
        "--postprocess",
        action="store_true",
        help="Apply the current monophonic normalization and quantization first.",
    )
    parser.add_argument("--subdivision", type=int, default=4)
    args = parser.parse_args()
    payload = json.loads(args.transcription.read_text(encoding="utf-8"))
    events = tuple(_event_from_payload(item) for item in payload.get("events", ()))
    if args.postprocess:
        tempo_map = _tempo_map_from_payload(payload["tempoMap"])
        events = quantize_notes(
            normalize_bass_events(events),
            tempo_map,
            args.subdivision,
        )
    result = {
        "file": str(args.transcription.resolve()),
        "modelId": payload.get("modelId", "unknown"),
        "postprocessed": args.postprocess,
        **measure_bass_quality(events).to_payload(),
    }
    print(json.dumps(result, indent=2))
    return 0


def _event_from_payload(payload: dict[str, object]) -> NoteEvent:
    return NoteEvent(
        id=str(payload["id"]),
        detected_start_seconds=float(payload["detectedStartSeconds"]),
        detected_end_seconds=float(payload["detectedEndSeconds"]),
        midi_pitch=int(payload["midiPitch"]),
        velocity=int(payload["velocity"]),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        quantized_start_beat=(
            float(payload["quantizedStartBeat"])
            if payload.get("quantizedStartBeat") is not None
            else None
        ),
        quantized_duration_beats=(
            float(payload["quantizedDurationBeats"])
            if payload.get("quantizedDurationBeats") is not None
            else None
        ),
        pitch_bends=tuple(
            PitchBendPoint(
                float(point["timeOffsetSeconds"]),
                float(point["semitones"]),
            )
            for point in payload.get("pitchBends", ())
        ),
    )


def _tempo_map_from_payload(payload: dict[str, object]) -> TempoMap:
    beats = payload.get("beats", ())
    return TempoMap(
        bpm=float(payload["bpm"]),
        beats=tuple(
            TempoBeat(int(item["beatIndex"]), float(item["timeSeconds"]))
            for item in beats
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
