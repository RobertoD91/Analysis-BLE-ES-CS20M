#!/usr/bin/env python3
"""Make a shareable copy of a PacketLogger (.pklg) capture of the scale.

A raw capture is full of personal data: the phone's Bluetooth address, model and iOS version,
every device nearby, connections to other accessories. This tool keeps only what the lab needs,
the scale's advertisements and the app's replies, and rewrites the identifiers in them: the
scale's MAC address, the app's session token and, optionally, the weight. Record timing and
every other byte are left untouched.

Usage:
    python3 tools/anonymize_capture.py raw.pklg sample.pklg --mac C0:FF:EE:12:34:56 \\
        --token 123456 --weight-factor 0.7

Standard library only.
"""
import argparse
import struct
import sys

PKLG_CMD, PKLG_EVT = 0x00, 0x01
HCI_LE_META = 0x3E
LE_ADV_REPORT, LE_EXT_ADV_REPORT = 0x02, 0x0D
OP_LE_SET_ADV_DATA, OP_LE_SET_EXT_ADV_DATA = 0x2008, 0x2037
AD_UUID128_COMPLETE = 0x07
SCALE_HEADER = b"\xff\xff\xaa\xbb"  # AD value: company ID 0xFFFF + magic AA BB
NO_TOKEN = b"\xff\xff\xff"


def records(data):
    off = 0
    while off + 4 <= len(data):
        (length,) = struct.unpack_from("<I", data, off)
        if length < 9 or off + 4 + length > len(data):
            return
        yield data[off + 4 : off + 12], data[off + 12], bytearray(data[off + 13 : off + 4 + length])
        off += 4 + length


def pack_record(timestamp, typ, payload):
    return struct.pack("<I", 9 + len(payload)) + timestamp + bytes([typ]) + payload


def scale_report(evt):
    """(address offset, frame offset) for an advertising report carrying one scale frame, else None."""
    if len(evt) < 4 or evt[0] != HCI_LE_META or evt[3] != 1:
        return None
    if evt[2] == LE_EXT_ADV_REPORT:
        addr = 4 + 3
    elif evt[2] == LE_ADV_REPORT:
        addr = 4 + 2
    else:
        return None
    frame = evt.find(SCALE_HEADER)
    return (addr, frame) if frame > 0 else None


def app_uuid(cmd):
    """Offset of the 128-bit UUID in which the app hides its data, else None."""
    if len(cmd) < 4:
        return None
    (opcode,) = struct.unpack_from("<H", cmd, 0)
    if opcode == OP_LE_SET_EXT_ADV_DATA and len(cmd) >= 7:
        start, length = 7, cmd[6]
    elif opcode == OP_LE_SET_ADV_DATA:
        start, length = 4, cmd[3]
    else:
        return None
    i, end = start, start + length
    while i < end and cmd[i]:
        if cmd[i + 1] == AD_UUID128_COMPLETE and cmd[i] == 17:
            return i + 2
        i += 1 + cmd[i]
    return None


def mac_bytes(text):
    raw = bytes.fromhex(text.replace(":", ""))
    if len(raw) != 6:
        raise argparse.ArgumentTypeError("a MAC address has 6 bytes, e.g. C0:FF:EE:12:34:56")
    return raw


def token_bytes(text):
    raw = bytes.fromhex(text)
    if len(raw) != 3:
        raise argparse.ArgumentTypeError("the token has 3 bytes, e.g. 123456")
    return raw


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--mac", type=mac_bytes, required=True, help="new MAC address for the scale")
    ap.add_argument("--token", type=token_bytes, required=True, help="new session token (3 bytes in hex)")
    ap.add_argument("--weight-factor", type=float, default=1.0, help="multiply every weight by this factor")
    args = ap.parse_args()

    with open(args.source, "rb") as f:
        data = f.read()

    out, kept, dropped, scale_mac = [], 0, 0, None
    for timestamp, typ, payload in records(data):
        if typ == PKLG_EVT and (found := scale_report(payload)):
            addr, frame = found
            mac = bytes(payload[frame + 4 : frame + 10])
            if scale_mac and mac != scale_mac:
                sys.exit(f"more than one scale in the capture ({scale_mac.hex(':')}, {mac.hex(':')})")
            scale_mac = mac
            payload[addr : addr + 6] = args.mac[::-1]  # the report carries the address little-endian
            payload[frame + 4 : frame + 10] = args.mac
            if payload[frame + 14 : frame + 17] != NO_TOKEN:
                payload[frame + 14 : frame + 17] = args.token
            (weight,) = struct.unpack_from("<H", payload, frame + 19)
            struct.pack_into("<H", payload, frame + 19, round(weight * args.weight_factor))
        elif typ == PKLG_CMD and (uuid := app_uuid(payload)) is not None:
            if payload[uuid + 10 : uuid + 16] != b"\x00\x00\x00\x00\xfe\xfe":  # not the idle UUID
                payload[uuid + 4 : uuid + 7] = args.token
                payload[uuid + 10 : uuid + 16] = args.mac
        else:
            dropped += 1
            continue
        kept += 1
        out.append(pack_record(timestamp, typ, payload))

    if scale_mac is None:
        sys.exit("no scale frames found")
    with open(args.target, "wb") as f:
        f.write(b"".join(out))
    print(f"kept {kept} records, dropped {dropped}; scale {scale_mac.hex(':').upper()} -> {args.mac.hex(':').upper()}")


if __name__ == "__main__":
    main()
