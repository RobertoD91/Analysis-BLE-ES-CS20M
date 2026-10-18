import unittest
from pathlib import Path

from scale_bot.pklg import scale_frames
from scale_bot.protocol import MeasurementTracker, parse_frame

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
COMPLETE = SAMPLES / "complete-weighing.pklg"
INTERRUPTED = SAMPLES / "interrupted-weighing.pklg"
SAMPLE_MAC = "C0:FF:EE:12:34:56"


def measurements(path, tracker=None):
    tracker = tracker or MeasurementTracker()
    frames = [parse_frame(data) for _, _, data in scale_frames(path)]
    return frames, [m for m in map(tracker.update, frames) if m]


class ProtocolTest(unittest.TestCase):
    def test_measuring_frame(self):
        frame = parse_frame(bytes.fromhex("aabbc0ffee1234568e40d36a123456020" "06e1c4c09037d06"))
        self.assertEqual(frame.mac, SAMPLE_MAC)
        self.assertEqual(frame.clock, 0x6AD3408E)
        self.assertEqual(frame.token, "123456")
        self.assertEqual(frame.state, 0x02)
        self.assertFalse(frame.final)
        self.assertEqual(frame.weight_kg, 72.78)
        self.assertEqual(frame.counter, 0x067D)

    def test_ignores_other_data(self):
        self.assertIsNone(parse_frame(bytes.fromhex("abbbc0ffee1234568e40d36a123456020" "06e1c4c09037d06")))
        self.assertIsNone(parse_frame(bytes.fromhex("aabbc0ffee12")))

    def test_complete_weighing_gives_one_measurement(self):
        frames, found = measurements(COMPLETE)
        self.assertEqual(len(frames), 78)
        self.assertTrue(all(f.mac == SAMPLE_MAC for f in frames))
        self.assertEqual([(m.weight_kg, m.state) for m in found], [(75.0, 0x23)])

    def test_interrupted_weighing_gives_none(self):
        frames, found = measurements(INTERRUPTED)
        self.assertEqual(len(frames), 93)
        self.assertEqual(max(f.weight_kg for f in frames), 75.35)
        self.assertEqual(found, [])

    def test_restart_does_not_duplicate(self):
        _, first = measurements(COMPLETE)
        _, again = measurements(COMPLETE, MeasurementTracker(last_key=first[0].key))
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
