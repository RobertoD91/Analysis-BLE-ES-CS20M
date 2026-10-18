"""Scale frames read from an Apple PacketLogger (.pklg) capture, for testing without BLE."""
import struct

from .protocol import COMPANY_ID

PKLG_EVENT = 0x01
HCI_LE_META = 0x3E
LE_ADV_REPORT, LE_EXT_ADV_REPORT = 0x02, 0x0D
AD_MANUFACTURER = 0xFF


def _records(data):
    # length (u32 LE) | seconds (u32) | microseconds (u32) | type (u8) | payload
    off = 0
    while off + 4 <= len(data):
        (length,) = struct.unpack_from("<I", data, off)
        if length < 9 or off + 4 + length > len(data):
            return
        secs, usecs = struct.unpack_from("<II", data, off + 4)
        yield secs + usecs / 1e6, data[off + 12], data[off + 13 : off + 4 + length]
        off += 4 + length


def _adv_reports(evt):
    if len(evt) < 4 or evt[0] != HCI_LE_META:
        return
    sub, off = evt[2], 4
    for _ in range(evt[3]):
        if sub == LE_EXT_ADV_REPORT:
            length = evt[off + 23]
            yield struct.unpack_from("b", evt, off + 13)[0], evt[off + 24 : off + 24 + length]
            off += 24 + length
        elif sub == LE_ADV_REPORT:
            length = evt[off + 8]
            yield struct.unpack_from("b", evt, off + 9 + length)[0], evt[off + 9 : off + 9 + length]
            off += 10 + length
        else:
            return


def _ad_structures(data):
    i = 0
    while i < len(data) and data[i] and i + 1 + data[i] <= len(data):
        yield data[i + 1], data[i + 2 : i + 1 + data[i]]
        i += 1 + data[i]


def scale_frames(path):
    """[(timestamp, rssi, manufacturer data without company ID)] in capture order."""
    with open(path, "rb") as f:
        data = f.read()
    frames = []
    for ts, typ, payload in _records(data):
        if typ != PKLG_EVENT:
            continue
        for rssi, adv in _adv_reports(payload):
            for ad_type, value in _ad_structures(adv):
                if ad_type == AD_MANUFACTURER and len(value) > 2 and value[0] | value[1] << 8 == COMPANY_ID:
                    frames.append((ts, rssi, value[2:]))
    return frames
