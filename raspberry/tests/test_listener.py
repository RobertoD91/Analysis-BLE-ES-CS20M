import unittest

try:
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
except ImportError:  # bleak is only needed on the Raspberry Pi
    BLEDevice = None

from test_protocol import COMPLETE, SAMPLE_MAC


@unittest.skipIf(BLEDevice is None, "bleak not installed")
class ListenerTest(unittest.TestCase):
    def test_bleak_callback_with_sample_frames(self):
        from scale_bot.listener import make_callback
        from scale_bot.pklg import scale_frames

        received = []
        callback = make_callback(lambda frame, rssi: received.append((frame, rssi)))
        device = BLEDevice(SAMPLE_MAC, None, None)
        frames = scale_frames(COMPLETE)
        for _, rssi, data in frames:
            callback(device, AdvertisementData(None, {0xFFFF: bytes(data)}, {}, [], None, rssi, ()))
        # advertisement from another device: ignored
        callback(device, AdvertisementData("iPhone", {0x004C: b"\x10\x07"}, {}, [], None, -60, ()))
        self.assertEqual(len(received), len(frames))
        self.assertTrue(any(f.final and f.weight_kg == 75.0 for f, _ in received))
        self.assertEqual(received[0][1], frames[0][1])


if __name__ == "__main__":
    unittest.main()
