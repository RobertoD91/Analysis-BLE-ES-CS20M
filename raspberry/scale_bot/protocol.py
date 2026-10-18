"""Frames of the broadcast scale (see docs/protocol.md).

The bytes are the manufacturer data AFTER the 0xFFFF company ID, i.e. what bleak
returns in advertisement_data.manufacturer_data[0xFFFF].
"""
import struct
from dataclasses import dataclass

COMPANY_ID = 0xFFFF
MAGIC = b"\xaa\xbb"
FRAME_LENGTH = 24
STATE_FINAL_BIT = 0x01  # state 0x02 measuring, 0x23 final


@dataclass(frozen=True)
class Frame:
    mac: str
    clock: int
    token: str
    state: int
    weight_kg: float
    counter: int
    raw: bytes

    @property
    def final(self):
        return bool(self.state & STATE_FINAL_BIT)

    @property
    def key(self):
        return (self.mac, self.counter, self.weight_kg)


def parse_frame(data):
    if len(data) < FRAME_LENGTH or data[:2] != MAGIC:
        return None
    (clock,) = struct.unpack_from("<I", data, 8)
    (weight,) = struct.unpack_from("<H", data, 17)
    (counter,) = struct.unpack_from("<H", data, 22)
    return Frame(
        mac=":".join(f"{b:02X}" for b in data[2:8]),
        clock=clock,
        token=data[12:15].hex(),
        state=data[15],
        weight_kg=weight / 100,
        counter=counter,
        raw=bytes(data[:FRAME_LENGTH]),
    )


class MeasurementTracker:
    """Spots a new measurement the first time its final frame shows up.

    The scale repeats the final frame for many seconds with the counter frozen.
    last_key lets the service resume after a restart without storing the same measurement twice.
    """

    def __init__(self, last_key=None):
        self._last_key = last_key

    def update(self, frame):
        if not frame.final or frame.weight_kg <= 0 or frame.key == self._last_key:
            return None
        self._last_key = frame.key
        return frame
