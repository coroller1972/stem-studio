import unittest

import numpy as np

from drumscript_transcriber import events_from_drumscript


class DrumScriptTranscriberTests(unittest.TestCase):
    def test_converts_polyphonic_onsets_and_normalizes_classes(self) -> None:
        audio = np.zeros(44_100, dtype=np.float32)
        audio[4_410:4_500] = 0.8
        classified = [
            {
                "time_sec": 0.1,
                "instruments": ["kick", "hi_hat_closed", "kick"],
                "debug_features": {},
            }
        ]

        events = events_from_drumscript(classified, audio, 44_100, np)

        self.assertEqual(len(events), 2)
        self.assertEqual({event.instrument for event in events}, {"kick", "closed_hihat"})
        self.assertEqual({event.detected_time_seconds for event in events}, {0.1})
        self.assertTrue(all(event.confidence is None for event in events))
        self.assertTrue(all(1 <= event.velocity <= 127 for event in events))


if __name__ == "__main__":
    unittest.main()
