import unittest

from transcription_domain import (
    BassTranscription,
    NoteEvent,
    PitchBendPoint,
    TempoMap,
)


class TranscriptionDomainTests(unittest.TestCase):
    def test_bass_payload_preserves_pitch_bends_and_tempo_candidates(self) -> None:
        event = NoteEvent(
            "bend",
            0.0,
            0.5,
            40,
            100,
            pitch_bends=(PitchBendPoint(0.25, 1.0),),
        )
        transcription = BassTranscription(
            events=(event,),
            tab=(),
            tempo_map=TempoMap(152, (), tempo_candidates=(76, 152)),
        )

        payload = transcription.to_payload()

        self.assertEqual(payload["schemaVersion"], 3)
        self.assertEqual(payload["events"][0]["pitchBends"][0]["semitones"], 1.0)
        self.assertEqual(payload["sourceEvents"][0]["id"], "bend")
        self.assertEqual(payload["tempoMap"]["tempoCandidates"], [76, 152])


if __name__ == "__main__":
    unittest.main()
