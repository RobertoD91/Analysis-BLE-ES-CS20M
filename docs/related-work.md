# Related work

We decoded the scale on our own, from the iPhone captures, before we knew about any of the projects
below. Comparing afterwards showed that the frame format was already public. Next time we would
search first, starting from the FCC ID on the label (`2APXUES-CS20M`).

## The projects

| Project | Language | Device | Transport | Same protocol? |
|---|---|---|---|---|
| [renpho-escs20m](https://github.com/ronnnnnnnnnnnnn/renpho-escs20m) | Python | ES-CS20M and siblings | QN GATT, `0x55AA` GATT, `0xAABB` broadcast (experimental, since July 2026) | Yes, and it lists FCC ID `2APXUES-CS20M` as the broadcast variant |
| [openScale](https://github.com/oliexdev/openScale) | Kotlin (Android) | Dozens of scales | `QNHandlerBroadcast` for `0xAABB` (since April 2026); `ESCS20MHandler` for the `0x55AA` GATT variant | Yes |
| [bluetooth_scale](https://github.com/asd333111/bluetooth_scale) | Python, Home Assistant | Renpho ES-24M-B | `0xAABB` broadcast (March 2026), weight only | Yes |
| [renpho-scale](https://github.com/Chococoin/renpho-scale) | Swift (macOS) | Renpho Elis 1C | `0x55AA` frames over GATT, service `0x1A10` | No |
| [r-msc04-bridge](https://github.com/joelr/r-msc04-bridge) | C++ (ESP32) | Renpho R-MSC04 | `0x55AA` frames over GATT | No |
| [renpho-ble](https://github.com/Eim-make/renpho-ble) | Python | Renpho ES-SNG01 kitchen scale | GATT | No |

The marketed model name says little, because Renpho sells several ES-CS20M hardware revisions that
speak different protocols. renpho-escs20m tells them apart by the HVIN or the FCC ID on the label.

## Field by field

Offsets count after the company ID, as in [protocol.md](protocol.md).

| Bytes | This project | renpho-escs20m | openScale | bluetooth_scale |
|---|---|---|---|---|
| 0-1 `aa bb` | magic | magic | magic | magic |
| 2-7 | MAC | MAC, checked against the address | address | MAC |
| 8-11 | Unix time set by the app, the scale's clock otherwise | not interpreted | not interpreted | not used |
| 12-14 | session token from the app, `ff ff ff` without one | not interpreted | not interpreted | not used |
| 15 status | `0x02` measuring, `0x23` final; final = bit `0x01` | `0x01` committed, `0x20` stable, bits 1-3 display unit; `0x03` tare, `0x25` lb final, `0x64` provisional | stable = bit `0x20` (bit `0x01` only for FITINDEX FT-26R) | not used: stable after 5 readings within 0.05 kg |
| 17-18 weight | uint16 LE / 100 | same | same | same |
| 19-21 | constant `4c 09 03` | same bytes in its kg vectors, `4c 44 03` in the lb ones | `51 0e 03` used as the FT-26R signature | not used |
| 22-23 | counter, +1 every 0.5 s or so, frozen at final | not used | a counter is mentioned for the FT-26R | not used |

Each project's rule, applied to our two captures, gives the same answer: the final weight at
11:47:12.7 in the complete weighing (0.7 s later with bluetooth_scale's heuristic), and nothing in
the interrupted one.

On paper the two stability rules disagree. openScale takes bit `0x20` as "stable". renpho-escs20m
saw a provisional frame `0x64` (bit `0x20` set, bit `0x01` clear) on a unit set to lb, and waits for
bit `0x01`. On our unit both bits arrive in the same frame, so our captures cannot tell them apart.

## What was already known

- The frame format: magic, MAC, status byte, and the weight in hundredths of a kg, little-endian.
- That this ES-CS20M revision only broadcasts and sends no impedance.
- The status bits for stable, committed and display unit, from renpho-escs20m's captures.
- That the final frame is repeated for a while: renpho-escs20m ignores further readings for 10 s
  after a final one, a value it describes as "capture-validated only".

## What this project adds

- The app's side of the conversation. The iOS app answers with advertisements named `QN-S500`,
  which carry a Unix time, a session token, a command (`01` synchronise, `f1` acknowledge) and the
  target MAC inside a fake 128-bit service UUID. None of the six projects describes it.
- The meaning of bytes 8-14: the app's time and the token it assigns. The other projects' published
  frames agree with it.
- The counter at bytes 22-23 and the timing of a weighing: about 5 s of near silence before the
  final frame, then at least 9.4 s of repetitions (48 frames) until the capture ended. That is
  close to renpho-escs20m's 10 s window.
- The method: capturing on iOS with PacketLogger, and anonymising captures before publishing them.
  The anonymised samples come from live hardware.
- A live test of renpho-escs20m's client on this variant, whose support had been checked against
  captured advertisements only. On a Raspberry Pi next to the scale it reported the final weight,
  also with the phone switched off.
- A browser client, the progressive web app, and a Raspberry Pi to Telegram service, both tested
  in CI against the recorded samples.
