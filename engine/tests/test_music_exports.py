import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from fretboard import BassFretboardSolver
from midi_export import export_bass_midi, export_drums_midi
from musicxml_export import export_bass_musicxml, export_drums_musicxml
from transcription_domain import DrumEvent, NoteEvent, PitchBendPoint, TempoBeat, TempoMap


class MusicExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempo = TempoMap(120, tuple(TempoBeat(index, index * 0.5) for index in range(17)))
        self.bass = (
            NoteEvent("n1", 0, 0.5, 40, 100, quantized_start_beat=0, quantized_duration_beats=1),
            NoteEvent("n2", 1, 1.5, 43, 90, quantized_start_beat=2, quantized_duration_beats=1),
        )
        self.drums = (
            DrumEvent("d1", 0, "kick", 100, quantized_beat=0),
            DrumEvent("d2", 0.5, "snare", 100, quantized_beat=1),
            DrumEvent("d3", 1, "closed_hihat", 90, quantized_beat=2),
        )

    def test_musicxml_documents_have_measures_notes_and_tempo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bass_path = export_bass_musicxml(
                self.bass, BassFretboardSolver().solve(self.bass), self.tempo, root / "bass.musicxml"
            )
            drums_path = export_drums_musicxml(self.drums, self.tempo, root / "drums.musicxml")
            for path in (bass_path, drums_path):
                document = ET.parse(path).getroot()
                self.assertEqual(document.tag, "score-partwise")
                self.assertTrue(document.findall(".//measure"))
                self.assertTrue(document.findall(".//note"))
                self.assertIsNotNone(document.find(".//sound[@tempo]"))

    def test_five_string_musicxml_declares_beadg_and_low_b_string(self) -> None:
        low_b = (
            NoteEvent("b0", 0, 0.5, 23, 100, quantized_start_beat=0, quantized_duration_beats=1),
        )
        tuning = (23, 28, 33, 38, 43)
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_musicxml(
                low_b,
                BassFretboardSolver(tuning).solve(low_b),
                self.tempo,
                Path(directory) / "bass-5.musicxml",
                tuning=tuning,
            )
            document = ET.parse(path).getroot()
            self.assertEqual(document.findtext(".//staff-lines"), "5")
            self.assertEqual(len(document.findall(".//staff-tuning")), 5)
            self.assertEqual(document.findtext(".//technical/string"), "5")

    def test_musicxml_preserves_an_expressive_bend(self) -> None:
        bent = (
            NoteEvent(
                "bend",
                0,
                0.5,
                40,
                100,
                quantized_start_beat=0,
                quantized_duration_beats=1,
                pitch_bends=(PitchBendPoint(0.25, 1.0),),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_musicxml(
                bent,
                BassFretboardSolver().solve(bent),
                self.tempo,
                Path(directory) / "bend.musicxml",
            )
            document = ET.parse(path).getroot()

        self.assertEqual(document.findtext(".//bend/bend-alter"), "1.000")

    def test_bass_musicxml_splits_cross_measure_notes_with_ties(self) -> None:
        crossing = (
            NoteEvent("crossing", 0, 1, 40, 100, quantized_start_beat=3.5, quantized_duration_beats=1.5),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_musicxml(
                crossing,
                BassFretboardSolver().solve(crossing),
                self.tempo,
                Path(directory) / "crossing.musicxml",
            )
            document = ET.parse(path).getroot()

        pitched = [note for note in document.findall(".//note") if note.find("pitch") is not None]
        self.assertEqual([note.findtext("duration") for note in pitched], ["12", "24"])
        self.assertIsNotNone(pitched[0].find("tie[@type='start']"))
        self.assertIsNotNone(pitched[1].find("tie[@type='stop']"))

    def test_musicxml_spells_dotted_duration_and_fills_every_measure(self) -> None:
        dotted = (
            NoteEvent("dotted", 0, 1, 40, 100, quantized_start_beat=0, quantized_duration_beats=1.5),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_musicxml(
                dotted,
                BassFretboardSolver().solve(dotted),
                self.tempo,
                Path(directory) / "dotted.musicxml",
            )
            document = ET.parse(path).getroot()

        pitched = next(note for note in document.findall(".//note") if note.find("pitch") is not None)
        self.assertEqual(pitched.findtext("type"), "quarter")
        self.assertIsNotNone(pitched.find("dot"))
        for measure in document.findall(".//measure"):
            elapsed = sum(
                int(note.findtext("duration", "0"))
                for note in measure.findall("note")
                if note.find("chord") is None
            )
            self.assertEqual(elapsed, 96)

    def test_musicxml_represents_pickup_measure_explicitly(self) -> None:
        pickup = (
            NoteEvent("pickup", 0, 0.2, 40, 100, quantized_start_beat=-0.5, quantized_duration_beats=0.5),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_musicxml(
                pickup,
                BassFretboardSolver().solve(pickup),
                self.tempo,
                Path(directory) / "pickup.musicxml",
            )
            document = ET.parse(path).getroot()

        pickup_measure = document.find(".//measure[@number='0']")
        self.assertIsNotNone(pickup_measure)
        self.assertEqual(pickup_measure.get("implicit"), "yes")
        self.assertEqual(sum(int(note.findtext("duration", "0")) for note in pickup_measure.findall("note")), 12)

    def test_drum_musicxml_declares_distinct_general_midi_instruments(self) -> None:
        simultaneous = (
            DrumEvent("kick", 0, "kick", 100, quantized_beat=0),
            DrumEvent("snare", 0, "snare", 100, quantized_beat=0),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_drums_musicxml(simultaneous, self.tempo, Path(directory) / "drums.musicxml")
            document = ET.parse(path).getroot()

        note_ids = {node.get("id") for node in document.findall(".//part/measure/note/instrument")}
        self.assertEqual(note_ids, {"P1-I-kick", "P1-I-snare"})
        midi_by_id = {
            node.get("id"): node.findtext("midi-unpitched")
            for node in document.findall(".//midi-instrument")
        }
        self.assertEqual(midi_by_id["P1-I-kick"], "36")
        self.assertEqual(midi_by_id["P1-I-snare"], "38")

    @unittest.skipUnless(importlib.util.find_spec("music21"), "music21 is an optional interoperability parser")
    def test_musicxml_survives_a_music21_round_trip(self) -> None:
        from music21 import converter

        crossing = (
            NoteEvent("crossing", 0, 1, 40, 100, quantized_start_beat=3.5, quantized_duration_beats=1.5),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = export_bass_musicxml(
                crossing,
                BassFretboardSolver().solve(crossing),
                self.tempo,
                root / "source.musicxml",
            )
            score = converter.parse(source)
            round_trip = Path(score.write("musicxml", fp=root / "round-trip.musicxml"))
            reparsed = converter.parse(round_trip)

        self.assertGreater(len(reparsed.recurse().notes), 0)

    @unittest.skipUnless(importlib.util.find_spec("mido"), "mido is an optional transcription dependency")
    def test_midi_exports_contain_tempo_and_notes(self) -> None:
        import mido

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bass_path = export_bass_midi(self.bass, self.tempo, root / "bass.mid")
            drums_path = export_drums_midi(self.drums, self.tempo, root / "drums.mid")
            bass = mido.MidiFile(bass_path)
            drums = mido.MidiFile(drums_path)
            self.assertTrue(any(message.type == "set_tempo" for track in bass.tracks for message in track))
            self.assertEqual(sum(message.type == "note_on" for track in bass.tracks for message in track), 2)
            self.assertTrue(any(message.type == "note_on" and message.channel == 9 for track in drums.tracks for message in track))

    @unittest.skipUnless(importlib.util.find_spec("mido"), "mido is an optional transcription dependency")
    def test_bass_midi_exports_pitch_bends_and_resets_channel(self) -> None:
        import mido

        bent = (
            NoteEvent(
                "bend",
                0,
                0.5,
                40,
                100,
                quantized_start_beat=0,
                quantized_duration_beats=1,
                pitch_bends=(
                    PitchBendPoint(0.0, 0.0),
                    PitchBendPoint(0.25, 1.0),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_midi(bent, self.tempo, Path(directory) / "bend.mid")
            midi = mido.MidiFile(path)
            bends = [
                message.pitch
                for track in midi.tracks
                for message in track
                if message.type == "pitchwheel"
            ]

        self.assertIn(4096, bends)
        self.assertEqual(bends[-1], 0)

    @unittest.skipUnless(importlib.util.find_spec("mido"), "mido is an optional transcription dependency")
    def test_midi_preserves_pickup_spacing_and_marks_measure_one(self) -> None:
        import mido

        pickup = (
            NoteEvent("pickup", 0, 0.2, 40, 100, quantized_start_beat=-0.5, quantized_duration_beats=0.25),
            NoteEvent("downbeat", 0.5, 0.7, 43, 100, quantized_start_beat=0, quantized_duration_beats=0.25),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_bass_midi(pickup, self.tempo, Path(directory) / "pickup.mid")
            midi = mido.MidiFile(path)

        note_ticks = []
        absolute = 0
        for message in midi.tracks[1]:
            absolute += message.time
            if message.type == "note_on":
                note_ticks.append(absolute)
        markers = [message for message in midi.tracks[0] if message.type == "marker"]
        self.assertEqual(note_ticks, [0, 240])
        self.assertEqual(markers[0].text, "Measure 1")
        self.assertEqual(markers[0].time, 240)


if __name__ == "__main__":
    unittest.main()
