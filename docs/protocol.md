# The scale's protocol

The scale is a Renpho ES-CS20M, hardware revision with FCC ID `2APXUES-CS20M` (see the
[label](images/es-cs20m-label.jpg)). Other ES-CS20M revisions use connection-based protocols; this
one only broadcasts.

All values below come from the anonymised samples: the scale's MAC is `C0:FF:EE:12:34:56`, the
session token is `12 34 56`, and the weights are scaled. Structure and timing are those of the real
captures. Offsets count from the start of the manufacturer data after the 2-byte company ID. That
is how Web Bluetooth, bleak and Android hand the data over, and how the
[related projects](related-work.md) number the bytes.

## Summary

- The scale does not use GATT. It only sends non-connectable advertisements, and the weight is in
  them. The iPhone app replies with advertisements of its own, named `QN-S500`.
- The weight is an unsigned 16-bit little-endian integer in hundredths of a kg.
- A status byte goes from `0x02` (measuring) to `0x23` (final) when the measurement is complete.
  From then on the counter stays frozen and the scale repeats the final frame, for at least 9
  seconds in the sample (until the capture ends).
- The scale broadcasts the weight before the app sends anything (token `ff ff ff`), so a receiver
  that only listens, like a browser or a Raspberry Pi, can read it.

## Samples

| File | Content |
|---|---|
| `samples/complete-weighing.pklg` | Full weighing: 78 scale frames, final weight 75.00 kg (status `0x23`) |
| `samples/interrupted-weighing.pklg` | Settling readings only, no final frame |

## Scale frame (manufacturer data, AD type `0xFF`)

The frame travels in a legacy `ADV_NONCONN_IND` advertisement (non-connectable) with flags `0x06`
and no name. The company ID is `0xFFFF`, which the Bluetooth SIG reserves for testing; many vendors
use it anyway.

Example payload: `aa bb c0 ff ee 12 34 56 8e 40 d3 6a 12 34 56 02 00 6e 1c 4c 09 03 7d 06`

| Offset | Bytes (example) | Meaning | Confidence |
|---|---|---|---|
| 0-1 | `aa bb` | Protocol magic | certain |
| 2-7 | `c0 ff ee 12 34 56` | The scale's MAC address, big-endian | certain |
| 8-11 | `8e 40 d3 6a` | Little-endian Unix time (see below) | high |
| 12-14 | `12 34 56` | Session token: `ff ff ff` until the app assigns one | high |
| 15 | `02` | Status (see below) | high |
| 16 | `00` | Always `00` in the captures | unknown |
| 17-18 | `6e 1c` | Weight, uint16 little-endian, hundredths of a kg (`0x1C6E` = 7278, so 72.78 kg), always in kg whatever the display shows | certain |
| 19-21 | `4c 09 03` | Constant on this unit; `09 03` also appears in the app's command | unknown |
| 22-23 | `7d 06` | Little-endian uint16 counter, +1 about every 0.5 s, frozen once the measurement is final | high |

### Status byte

Our captures only show `0x02` (measuring) and `0x23` (final). Captures that
[renpho-escs20m](https://github.com/ronnnnnnnnnnnnn/renpho-escs20m) published from two other units
explain the bits:

| Bits | Meaning | Source |
|---|---|---|
| `0x01` | Committed: the weight is final | both |
| `0x0E` (bits 1-3) | Display unit: `1` kg, `2` lb | renpho-escs20m |
| `0x20` | Stable: the reading has settled | renpho-escs20m |
| `0x40` | Seen in the provisional frame `0x64` (stable but not committed, lb unit) | renpho-escs20m |

So `0x02` is kg and measuring, `0x23` is kg, stable and committed, and `0x03` is tare (0 kg,
committed). On this unit the stable and committed bits arrive together. The decoder, the web app
and the Raspberry Pi service treat a frame with bit `0x01` set as final, as renpho-escs20m does.

### Time and token

While the app is running (token assigned), the time field holds the time the app sent, which
matches the capture timestamp to the second. It changes only when the app sends a new time. Without
the app the field runs as a real-time clock: in a browser session with the phone switched off it
advanced one second per second, about 10 seconds behind the computer, with the token at `ff ff ff`.

Other data agrees. In the frames published by renpho-escs20m the field decodes to plausible 2026
dates next to an assigned token. A FITINDEX FT-26R frame that openScale recorded without the app
holds a clock about 100 seconds after 1970, with the token `ff ff ff`.

### Impedance

The label says "Body Composition Scale", but no impedance value shows up: bytes 19-21 stay the same
in the final frame too. renpho-escs20m reports that a fixed impedance of about 500 Ω reproduces the
official app's body-composition figures, which suggests the app estimates them from the weight and
the user's profile.

## App command (128-bit UUID, AD type `0x07`)

iOS lets apps advertise only a local name and service UUIDs. The app therefore puts its data in a
fake 128-bit service UUID, and names itself `QN-S500`.

Example (bytes in on-air order): `6a d3 40 8e 12 34 56 01 09 03 c0 ff ee 12 34 56`

| Offset | Bytes | Meaning |
|---|---|---|
| 0-3 | `6a d3 40 8e` | Unix time, big-endian (it matches the capture timestamp to the second) |
| 4-6 | `12 34 56` | Token that the scale adopts right after |
| 7 | `01` / `f1` | Command: `01` synchronise and start, `f1` acknowledge the final weight |
| 8-9 | `09 03` | Same as bytes 20-21 of the scale's frame |
| 10-15 | `c0 ff ee 12 34 56` | MAC of the target scale |

While idle the app advertises `00 00 00 00 00 01 00 00 00 00 00 00 00 00 fe fe` instead.

## A complete weighing

From `samples/complete-weighing.pklg` (capture time):

| Time | Event |
|---|---|
| 11:47:00.7 | The scale is broadcasting 0 kg with the token of the previous session |
| 11:47:01.0 | First touch: 77.57 kg, then 64.41 kg, with token `ff ff ff` |
| 11:47:01.19 | The app sends command `01` with time, token and MAC; the scale adopts them within 80 ms |
| 11:47:04.3 to 11:47:07.2 | The weight rises and settles: 0.28, 40.94, 66.25, 74.79, 75.07, 75.00 kg |
| 11:47:07.2 | The counter stops at `0x06B3`, with 75.00 kg and status `0x02` |
| 11:47:07 to 11:47:12 | The scale is almost silent (2 frames in 5.5 s), while the iPhone still hears 60 to 75 advertisements per second from other devices |
| 11:47:12.735 | Final frame: 75.00 kg, status `0x23` |
| 11:47:12.749 | The app answers with command `f1` (acknowledgement) and a new time |
| 11:47:13 to 11:47:22 | The scale keeps repeating the final frame |

We do not know what the scale does during the 5-second pause before the final frame. The app is
not needed for it: with the phone switched off, renpho-escs20m's client on a Raspberry Pi still
received the final weight, and so did the web app in a later test.

In `samples/interrupted-weighing.pklg` the readings stop after the settling phase and come back at
0 kg about 11 seconds later, with no final frame in between. The signal was weak, -84 to -90 dBm
with a person on the scale, so frames may have been lost.

## Security notes

- Anyone within radio range can read the weight with a BLE scanner, a browser or a Raspberry Pi,
  without pairing, and the scale cannot tell.
- Nothing in the frame is signed. A laptop advertising the same bytes would be accepted by the web
  app and the Raspberry Pi service, and probably by the vendor app too (not tested).
- The scale's MAC address is fixed and also sits in the payload, so the scale can be tracked.
- The "pairing" between app and scale is a token sent in clear in an advertisement.

## Open questions

- The meaning of byte 16, of the app's idle UUID, and of bytes 19-21, which differ between units:
  `4c 09 03` here, `4c 44 03` on another ES-CS20M, `51 0e 03` on a FITINDEX FT-26R.
- What happens during the pause before the final frame.
