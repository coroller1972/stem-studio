"""MIDI exporters generated from Stem Studio domain events."""

from __future__ import annotations

from pathlib import Path

from errors import TranscriptionError
from gm_drums import general_midi_note
from quantization import time_to_beat
from transcription_domain import DrumEvent, NoteEvent, TempoMap

TICKS_PER_BEAT = 480


def export_bass_midi(events: tuple[NoteEvent, ...], tempo_map: TempoMap, output_path: Path) -> Path:
    mido = _mido()
    track_events: list[tuple[int, int, object]] = []
    starts = [
        event.quantized_start_beat
        if event.quantized_start_beat is not None
        else time_to_beat(event.detected_start_seconds, tempo_map)
        for event in events
    ]
    beat_shift = max(0.0, -min(starts, default=0.0))
    for event in events:
        start_beat = event.quantized_start_beat
        if start_beat is None:
            start_beat = time_to_beat(event.detected_start_seconds, tempo_map)
        duration = event.quantized_duration_beats
        if duration is None:
            duration = max(0.05, time_to_beat(event.detected_end_seconds, tempo_map) - start_beat)
        shifted_start = start_beat + beat_shift
        start_tick = round(shifted_start * TICKS_PER_BEAT)
        end_tick = max(start_tick + 1, round((shifted_start + duration) * TICKS_PER_BEAT))
        if event.pitch_bends:
            track_events.append((start_tick, 1, mido.Message("pitchwheel", pitch=0, channel=0)))
        track_events.append((start_tick, 2, mido.Message("note_on", note=event.midi_pitch, velocity=event.velocity, channel=0)))
        detected_duration = event.detected_end_seconds - event.detected_start_seconds
        for point in event.pitch_bends:
            relative_position = min(1.0, max(0.0, point.time_offset_seconds / detected_duration))
            bend_tick = max(
                start_tick,
                min(end_tick - 1, round((shifted_start + duration * relative_position) * TICKS_PER_BEAT)),
            )
            pitchwheel = round(point.semitones / 2.0 * 8192)
            pitchwheel = max(-8192, min(8191, pitchwheel))
            track_events.append(
                (bend_tick, 3, mido.Message("pitchwheel", pitch=pitchwheel, channel=0))
            )
        track_events.append((end_tick, 0, mido.Message("note_off", note=event.midi_pitch, velocity=0, channel=0)))
        if event.pitch_bends:
            track_events.append((end_tick, 1, mido.Message("pitchwheel", pitch=0, channel=0)))
    return _write_midi(output_path, tempo_map, track_events, is_drums=False, downbeat_shift=beat_shift)


def export_drums_midi(events: tuple[DrumEvent, ...], tempo_map: TempoMap, output_path: Path) -> Path:
    mido = _mido()
    track_events: list[tuple[int, int, object]] = []
    duration_ticks = TICKS_PER_BEAT // 8
    starts = [
        event.quantized_beat
        if event.quantized_beat is not None
        else time_to_beat(event.detected_time_seconds, tempo_map)
        for event in events
    ]
    beat_shift = max(0.0, -min(starts, default=0.0))
    for event in events:
        beat = event.quantized_beat
        if beat is None:
            beat = time_to_beat(event.detected_time_seconds, tempo_map)
        start_tick = round((beat + beat_shift) * TICKS_PER_BEAT)
        note = general_midi_note(event.instrument)
        track_events.append((start_tick, 1, mido.Message("note_on", note=note, velocity=event.velocity, channel=9)))
        track_events.append((start_tick + duration_ticks, 0, mido.Message("note_off", note=note, velocity=0, channel=9)))
    return _write_midi(output_path, tempo_map, track_events, is_drums=True, downbeat_shift=beat_shift)


def _write_midi(
    output_path: Path,
    tempo_map: TempoMap,
    events: list[tuple[int, int, object]],
    *,
    is_drums: bool,
    downbeat_shift: float = 0.0,
) -> Path:
    mido = _mido()
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    tempo_track = mido.MidiTrack()
    tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    tempo_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo_map.bpm), time=0))
    tempo_track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=tempo_map.time_signature.numerator,
            denominator=tempo_map.time_signature.denominator,
            time=0,
        )
    )
    if downbeat_shift > 0:
        tempo_track.append(
            mido.MetaMessage(
                "marker",
                text="Measure 1",
                time=round(downbeat_shift * TICKS_PER_BEAT),
            )
        )
    midi.tracks.append(tempo_track)
    note_track = mido.MidiTrack()
    note_track.append(mido.MetaMessage("track_name", name="Drums" if is_drums else "Bass", time=0))
    if not is_drums:
        note_track.append(mido.Message("program_change", program=33, channel=0, time=0))
        if any(getattr(message, "type", None) == "pitchwheel" for _, _, message in events):
            # Explicitly configure the conventional +/- 2 semitone bend range.
            for control, value in ((101, 0), (100, 0), (6, 2), (38, 0), (101, 127), (100, 127)):
                note_track.append(
                    mido.Message(
                        "control_change",
                        control=control,
                        value=value,
                        channel=0,
                        time=0,
                    )
                )
    previous_tick = 0
    for absolute_tick, _order, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = absolute_tick - previous_tick
        note_track.append(message)
        previous_tick = absolute_tick
    midi.tracks.append(note_track)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    midi.save(output_path)
    return output_path


def _mido():
    try:
        import mido

        return mido
    except ImportError as error:
        raise TranscriptionError("Unable to export MIDI.", "Install mido from engine/requirements.txt.") from error
