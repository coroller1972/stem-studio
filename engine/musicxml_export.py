"""MusicXML 4.0 exporters with measure-safe rhythmic notation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from gm_drums import general_midi_note
from musical_timeline import (
    DIVISIONS_PER_QUARTER,
    MeasureWindow,
    NotatedDuration,
    measure_windows,
    notation_atoms,
    spell_duration,
)
from transcription_domain import DrumEvent, NoteEvent, TabNote, TempoMap

DIVISIONS = DIVISIONS_PER_QUARTER
MIN_NOTATED_BEND_SEMITONES = 0.75
DRUM_INSTRUMENTS = (
    "kick",
    "snare",
    "closed_hihat",
    "open_hihat",
    "ride",
    "crash",
    "high_tom",
    "mid_tom",
    "low_tom",
)


def export_bass_musicxml(
    events: tuple[NoteEvent, ...],
    tab: tuple[TabNote, ...],
    tempo_map: TempoMap,
    output_path: Path,
    *,
    tuning: tuple[int, ...] = (28, 33, 38, 43),
) -> Path:
    root, part = _bass_score()
    tab_by_id = {item.note_event_id: item for item in tab}
    measure_beats = _measure_beats(tempo_map)
    windows, atoms = notation_atoms(events, measure_beats)
    by_measure = defaultdict(list)
    for atom in atoms:
        by_measure[atom.measure_number].append(atom)

    for index, window in enumerate(windows):
        measure = _measure(part, window)
        if index == 0:
            _bass_attributes(measure, tempo_map, tuning)
            _tempo_direction(measure, tempo_map.bpm)
        cursor = window.start_beat
        for atom in sorted(by_measure[window.number], key=lambda item: item.start_beat):
            if atom.start_beat > cursor:
                _rests(measure, atom.start_beat - cursor)
            _bass_note(
                measure,
                atom.event,
                tab_by_id.get(atom.event.id),
                atom.duration,
                tie_start=atom.tie_start,
                tie_stop=atom.tie_stop,
                string_count=len(tuning),
            )
            cursor = atom.start_beat + atom.duration_beats
        if cursor < window.end_beat:
            _rests(measure, window.end_beat - cursor)
        _assert_measure_duration(measure, window)
    return _write_xml(root, output_path)


def export_drums_musicxml(
    events: tuple[DrumEvent, ...], tempo_map: TempoMap, output_path: Path
) -> Path:
    root, part = _drum_score()
    measure_beats = _measure_beats(tempo_map)
    earliest = min((event.quantized_beat for event in events if event.quantized_beat is not None), default=0.0)
    latest = max(
        ((event.quantized_beat or 0.0) + 0.25 for event in events),
        default=measure_beats,
    )
    windows = measure_windows(earliest, latest, measure_beats)
    grouped: dict[float, list[DrumEvent]] = defaultdict(list)
    for event in events:
        if event.quantized_beat is not None:
            grouped[event.quantized_beat].append(event)

    for index, window in enumerate(windows):
        measure = _measure(part, window)
        if index == 0:
            _drum_attributes(measure, tempo_map)
            _tempo_direction(measure, tempo_map.bpm)
        cursor = window.start_beat
        for beat in sorted(position for position in grouped if window.start_beat <= position < window.end_beat):
            if beat > cursor:
                _rests(measure, beat - cursor)
            for chord_index, event in enumerate(grouped[beat]):
                _drum_note(measure, event, chord=chord_index > 0)
            cursor = max(cursor, beat + 0.25)
        if cursor < window.end_beat:
            _rests(measure, window.end_beat - cursor)
        _assert_measure_duration(measure, window)
    return _write_xml(root, output_path)


def _bass_score() -> tuple[ET.Element, ET.Element]:
    root, score_part = _score_skeleton("Bass")
    instrument = ET.SubElement(score_part, "score-instrument", id="P1-I1")
    ET.SubElement(instrument, "instrument-name").text = "Electric Bass"
    midi = ET.SubElement(score_part, "midi-instrument", id="P1-I1")
    ET.SubElement(midi, "midi-channel").text = "1"
    ET.SubElement(midi, "midi-program").text = "34"
    return root, ET.SubElement(root, "part", id="P1")


def _drum_score() -> tuple[ET.Element, ET.Element]:
    root, score_part = _score_skeleton("Drums")
    for instrument_name in DRUM_INSTRUMENTS:
        instrument_id = _drum_instrument_id(instrument_name)
        instrument = ET.SubElement(score_part, "score-instrument", id=instrument_id)
        ET.SubElement(instrument, "instrument-name").text = instrument_name.replace("_", " ").title()
        midi = ET.SubElement(score_part, "midi-instrument", id=instrument_id)
        ET.SubElement(midi, "midi-channel").text = "10"
        ET.SubElement(midi, "midi-program").text = "1"
        ET.SubElement(midi, "midi-unpitched").text = str(general_midi_note(instrument_name))
    return root, ET.SubElement(root, "part", id="P1")


def _score_skeleton(name: str) -> tuple[ET.Element, ET.Element]:
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = f"Stem Studio — {name} transcription"
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = name
    return root, score_part


def _measure(part: ET.Element, window: MeasureWindow) -> ET.Element:
    attributes = {"number": str(window.number)}
    if window.implicit:
        attributes["implicit"] = "yes"
    return ET.SubElement(part, "measure", attributes)


def _common_attributes(measure: ET.Element, tempo_map: TempoMap) -> ET.Element:
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = str(tempo_map.time_signature.numerator)
    ET.SubElement(time, "beat-type").text = str(tempo_map.time_signature.denominator)
    return attributes


def _bass_attributes(measure: ET.Element, tempo_map: TempoMap, tuning: tuple[int, ...]) -> None:
    attributes = _common_attributes(measure, tempo_map)
    clef = ET.SubElement(attributes, "clef")
    ET.SubElement(clef, "sign").text = "TAB"
    ET.SubElement(clef, "line").text = "5"
    staff = ET.SubElement(attributes, "staff-details")
    ET.SubElement(staff, "staff-lines").text = str(len(tuning))
    for line, midi_pitch in enumerate(tuning, start=1):
        staff_tuning = ET.SubElement(staff, "staff-tuning", line=str(line))
        step, alter, octave = _pitch_name(midi_pitch)
        ET.SubElement(staff_tuning, "tuning-step").text = step
        if alter:
            ET.SubElement(staff_tuning, "tuning-alter").text = str(alter)
        ET.SubElement(staff_tuning, "tuning-octave").text = str(octave)


def _drum_attributes(measure: ET.Element, tempo_map: TempoMap) -> None:
    attributes = _common_attributes(measure, tempo_map)
    clef = ET.SubElement(attributes, "clef")
    ET.SubElement(clef, "sign").text = "percussion"
    ET.SubElement(clef, "line").text = "2"


def _tempo_direction(measure: ET.Element, bpm: float) -> None:
    direction = ET.SubElement(measure, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(direction_type, "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = f"{bpm:.3f}"
    ET.SubElement(direction, "sound", tempo=f"{bpm:.3f}")


def _bass_note(
    measure: ET.Element,
    event: NoteEvent,
    tab: TabNote | None,
    duration: NotatedDuration,
    *,
    tie_start: bool,
    tie_stop: bool,
    string_count: int,
) -> None:
    note = ET.SubElement(measure, "note")
    pitch = ET.SubElement(note, "pitch")
    step, alter, octave = _pitch_name(event.midi_pitch)
    ET.SubElement(pitch, "step").text = step
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(octave)
    _notated_duration(note, duration)
    if tie_stop:
        ET.SubElement(note, "tie", type="stop")
    if tie_start:
        ET.SubElement(note, "tie", type="start")

    expressive_bend = max(event.pitch_bends, key=lambda point: abs(point.semitones), default=None)
    has_bend = expressive_bend is not None and abs(expressive_bend.semitones) >= MIN_NOTATED_BEND_SEMITONES
    if tab is not None or has_bend or tie_start or tie_stop:
        notations = ET.SubElement(note, "notations")
        if tie_stop:
            ET.SubElement(notations, "tied", type="stop")
        if tie_start:
            ET.SubElement(notations, "tied", type="start")
        if tab is not None or has_bend:
            technical = ET.SubElement(notations, "technical")
            if tab is not None:
                ET.SubElement(technical, "string").text = str(string_count - tab.string_index)
                ET.SubElement(technical, "fret").text = str(tab.fret)
            if has_bend:
                bend = ET.SubElement(technical, "bend")
                ET.SubElement(bend, "bend-alter").text = f"{expressive_bend.semitones:.3f}"


def _drum_note(measure: ET.Element, event: DrumEvent, *, chord: bool) -> None:
    note = ET.SubElement(measure, "note")
    if chord:
        ET.SubElement(note, "chord")
    unpitched = ET.SubElement(note, "unpitched")
    step, octave = _drum_display(event.instrument)
    ET.SubElement(unpitched, "display-step").text = step
    ET.SubElement(unpitched, "display-octave").text = str(octave)
    ET.SubElement(note, "instrument", id=_drum_instrument_id(event.instrument))
    _notated_duration(note, spell_duration(0.25)[0])
    if "hihat" in event.instrument or event.instrument in ("ride", "crash"):
        ET.SubElement(note, "notehead").text = "x"


def _rests(measure: ET.Element, beats: float) -> None:
    for duration in spell_duration(beats):
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest")
        _notated_duration(note, duration)


def _notated_duration(note: ET.Element, duration: NotatedDuration) -> None:
    ET.SubElement(note, "duration").text = str(duration.ticks)
    ET.SubElement(note, "type").text = duration.note_type
    for _ in range(duration.dots):
        ET.SubElement(note, "dot")
    if duration.actual_notes is not None and duration.normal_notes is not None:
        modification = ET.SubElement(note, "time-modification")
        ET.SubElement(modification, "actual-notes").text = str(duration.actual_notes)
        ET.SubElement(modification, "normal-notes").text = str(duration.normal_notes)


def _assert_measure_duration(measure: ET.Element, window: MeasureWindow) -> None:
    elapsed = sum(
        int(note.findtext("duration", "0"))
        for note in measure.findall("note")
        if note.find("chord") is None
    )
    expected = round(window.duration_beats * DIVISIONS)
    if elapsed != expected:
        raise ValueError(
            f"MusicXML measure {window.number} contains {elapsed} divisions; expected {expected}."
        )


def _pitch_name(midi_pitch: int) -> tuple[str, int, int]:
    names = (("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0), ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0))
    step, alter = names[midi_pitch % 12]
    return step, alter, midi_pitch // 12 - 1


def _drum_display(instrument: str) -> tuple[str, int]:
    return {
        "kick": ("F", 3),
        "snare": ("C", 5),
        "closed_hihat": ("G", 5),
        "open_hihat": ("G", 5),
        "ride": ("F", 5),
        "crash": ("A", 5),
        "high_tom": ("E", 5),
        "mid_tom": ("D", 5),
        "low_tom": ("A", 4),
    }.get(instrument, ("B", 4))


def _drum_instrument_id(instrument: str) -> str:
    return f"P1-I-{instrument.replace('_', '-')}"


def _measure_beats(tempo_map: TempoMap) -> float:
    signature = tempo_map.time_signature
    return signature.numerator * 4 / signature.denominator


def _write_xml(root: ET.Element, output_path: Path) -> Path:
    ET.indent(root, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    ET.parse(output_path)
    return output_path
