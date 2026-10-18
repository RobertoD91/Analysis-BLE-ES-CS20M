#!/usr/bin/env python3
"""Decode an Apple PacketLogger (.pklg) capture of the BLE "broadcast" scale.

The scale does not use GATT: it sends the weight in non-connectable advertisements
(manufacturer data 0xFFFF, magic AA BB). The iPhone app replies with advertisements of
its own, named "QN-S500", hiding its data in a 128-bit UUID. The script prints the app's
commands and the scale's frames in time order.

Usage:
    python3 tools/decode_capture.py samples/complete-weighing.pklg
    python3 tools/decode_capture.py capture.pklg --all          # repeated frames too
    python3 tools/decode_capture.py capture.pklg --mac C0:FF:EE:12:34:56

Standard library only.
"""
import argparse
import datetime
import struct
import sys

PKLG_CMD, PKLG_EVT = 0x00, 0x01
HCI_LE_META = 0x3E
LE_ADV_REPORT, LE_EXT_ADV_REPORT = 0x02, 0x0D
OP_LE_SET_ADV_DATA, OP_LE_SET_EXT_ADV_DATA = 0x2008, 0x2037
AD_UUID128_COMPLETE, AD_NAME_COMPLETE, AD_MANUFACTURER = 0x07, 0x09, 0xFF
SCALE_HEADER = b"\xff\xff\xaa\xbb"  # company ID 0xFFFF + magic AA BB
STATE_FINAL_BIT = 0x01  # status 0x02 measuring, 0x23 final weight
UNITS = {1: "kg", 2: "lb"}  # display unit in bits 1-3 of the status byte


def pklg_records(data):
    """PacketLogger records: len (u32 LE) | sec (u32) | usec (u32) | type (u8) | payload."""
    off = 0
    while off + 4 <= len(data):
        (ln,) = struct.unpack_from("<I", data, off)
        if ln < 9 or off + 4 + ln > len(data):
            break
        secs, usecs = struct.unpack_from("<II", data, off + 4)
        yield secs + usecs / 1e6, data[off + 12], data[off + 13 : off + 4 + ln]
        off += 4 + ln


def ad_structures(data):
    i = 0
    while i < len(data) and data[i] and i + 1 + data[i] <= len(data):
        yield data[i + 1], data[i + 2 : i + 1 + data[i]]
        i += 1 + data[i]


def mac_str(raw_le):
    return ":".join(f"{b:02X}" for b in reversed(raw_le))


def adv_reports(evt):
    """(address, rssi, AD data) from LE Advertising Reports, legacy and extended."""
    if len(evt) < 4 or evt[0] != HCI_LE_META:
        return
    sub, off = evt[2], 4
    for _ in range(evt[3]):
        if sub == LE_EXT_ADV_REPORT:
            dlen = evt[off + 23]
            yield mac_str(evt[off + 3 : off + 9]), struct.unpack_from("b", evt, off + 13)[0], evt[off + 24 : off + 24 + dlen]
            off += 24 + dlen
        elif sub == LE_ADV_REPORT:
            dlen = evt[off + 8]
            yield mac_str(evt[off + 2 : off + 8]), struct.unpack_from("b", evt, off + 9 + dlen)[0], evt[off + 9 : off + 9 + dlen]
            off += 10 + dlen
        else:
            return


def own_adv_data(cmd):
    """AD data the iPhone sets for its own advertising, or None."""
    if len(cmd) < 3:
        return None
    (opcode,) = struct.unpack_from("<H", cmd, 0)
    if opcode == OP_LE_SET_EXT_ADV_DATA and len(cmd) >= 7:
        return cmd[7 : 7 + cmd[6]]
    if opcode == OP_LE_SET_ADV_DATA and len(cmd) >= 4:
        return cmd[4 : 4 + cmd[3]]
    return None


def decode_scale(mfg):
    """Scale frame. mfg includes the 2-byte company ID: payload offset N is mfg[N + 2]."""
    if len(mfg) < 26 or not mfg.startswith(SCALE_HEADER):
        return None
    return {
        "mac": ":".join(f"{b:02X}" for b in mfg[4:10]),
        "clock": struct.unpack_from("<I", mfg, 10)[0],
        "token": mfg[14:17].hex(),
        "state": mfg[17],
        "b16": mfg[18],
        "weight_kg": struct.unpack_from("<H", mfg, 19)[0] / 100,
        "b19_21": mfg[21:24].hex(),
        "counter": struct.unpack_from("<H", mfg, 24)[0],
    }


def decode_app_command(uuid_raw):
    """128-bit UUID sent by the app, in on-air byte order."""
    if len(uuid_raw) != 16:
        return None
    if uuid_raw[10:16] == b"\x00\x00\x00\x00\xfe\xfe":
        return {"kind": "idle"}
    return {
        "kind": "command",
        "clock": struct.unpack_from(">I", uuid_raw, 0)[0],
        "token": uuid_raw[4:7].hex(),
        "b7_9": uuid_raw[7:10].hex(),
        "mac": ":".join(f"{b:02X}" for b in uuid_raw[10:16]),
    }


def fmt_time(ts):
    # PacketLogger stores the iPhone's local time as if it were UTC
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def fmt_unix(sec):
    return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pklg")
    ap.add_argument("--mac", help="only this scale (e.g. C0:FF:EE:12:34:56)")
    ap.add_argument("--all", action="store_true", help="do not hide repeated frames")
    args = ap.parse_args()

    with open(args.pklg, "rb") as f:
        records = list(pklg_records(f.read()))
    if not records:
        sys.exit("no PacketLogger records found")

    last_scale, last_app, weights, finals = {}, None, [], set()
    for ts, typ, payload in records:
        if typ == PKLG_CMD:
            ad = own_adv_data(payload)
            if ad is None:
                continue
            fields = dict(ad_structures(ad))
            name = fields.get(AD_NAME_COMPLETE, b"").decode("utf-8", "replace")
            cmd = decode_app_command(fields.get(AD_UUID128_COMPLETE, b""))
            if not cmd or (args.mac and cmd.get("mac") not in (None, args.mac.upper())):
                continue
            key = tuple(sorted(cmd.items()))
            if key == last_app and not args.all:
                continue
            last_app = key
            if cmd["kind"] == "idle":
                print(f"{fmt_time(ts)}  APP    [{name}] waiting (idle UUID)")
            else:
                print(f"{fmt_time(ts)}  APP    [{name}] command: time={fmt_unix(cmd['clock'])} "
                      f"token={cmd['token']} bytes7-9={cmd['b7_9']} scale={cmd['mac']}")
        elif typ == PKLG_EVT:
            for addr, rssi, ad in adv_reports(payload):
                for ad_type, value in ad_structures(ad):
                    frame = decode_scale(value) if ad_type == AD_MANUFACTURER else None
                    if not frame or (args.mac and frame["mac"] != args.mac.upper()):
                        continue
                    key = tuple(frame.values())
                    if last_scale.get(addr) == key and not args.all:
                        continue
                    last_scale[addr] = key
                    if frame["weight_kg"]:
                        weights.append(frame["weight_kg"])
                    final = frame["state"] & STATE_FINAL_BIT
                    if final and frame["weight_kg"]:
                        finals.add(frame["weight_kg"])
                    print(f"{fmt_time(ts)}  SCALE  {frame['mac']} weight={frame['weight_kg']:6.2f} kg "
                          f"state=0x{frame['state']:02x}{' FINAL' if final else ''} "
                          f"unit={UNITS.get((frame['state'] >> 1) & 0x07, '?')} "
                          f"token={frame['token']} time={fmt_unix(frame['clock'])} "
                          f"counter=0x{frame['counter']:04x} b16={frame['b16']:02x} "
                          f"b19-21={frame['b19_21']} rssi={rssi} dBm")

    print()
    if weights:
        print(f"non-zero weight readings: {len(weights)} -> " + ", ".join(f"{w:.2f}" for w in weights))
        print(f"min {min(weights):.2f}  max {max(weights):.2f}  last {weights[-1]:.2f} kg")
    else:
        print("no non-zero weight readings")
    if finals:
        print("final weight: " + ", ".join(f"{w:.2f} kg" for w in sorted(finals)))
    else:
        print("no frame with a final weight")


if __name__ == "__main__":
    main()
