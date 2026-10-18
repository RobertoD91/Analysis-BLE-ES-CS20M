# Sniffing Bluetooth LE on iOS

This is how the captures in [`samples/`](../samples/) were made, and how the scale was then found
and decoded. No extra radio hardware is needed: the iPhone itself records every Bluetooth packet
its controller sends and receives, and a Mac reads them live.

## What you need

- An iPhone and the vendor app of the device under test (here, the scale's app).
- A Mac with PacketLogger, part of Apple's *Additional Tools for Xcode*.
- A free Apple Developer account, to download the Bluetooth logging profile.
- A USB cable.

## 1. Enable Bluetooth logging on the iPhone

1. On the iPhone, open Apple's [Profiles and Logs](https://developer.apple.com/bug-reporting/profiles-and-logs/)
   page, find the *Bluetooth* profile for iOS and download it.
2. Open *Settings → Profile Downloaded* and install it, then restart the iPhone.

The profile makes iOS keep a full HCI log: the commands the host sends to the Bluetooth chip and
the events the chip sends back, including every advertisement it hears. Logging profiles are
temporary: if a trace stays empty, reinstall the profile and restart the phone.

## 2. Record a trace with PacketLogger

1. Download *Additional Tools for Xcode* from [Apple's downloads](https://developer.apple.com/download/all/)
   and open `Hardware/PacketLogger.app`.
2. Connect the iPhone with the cable and trust the Mac.
3. In PacketLogger choose *File → New iOS Trace*. Packets start scrolling.
4. Reproduce one scenario per trace: open the vendor app, step on the scale, wait for the app to
   show the result. Write down the value and the time the app shows.
5. Stop and save the trace as `.pklg`. A descriptive name pays off later; the original captures were
   named after the weight the app showed.

PacketLogger can also export the trace in btsnoop format, which opens in Wireshark.

A few things helped here. Change one thing per capture: the first capture had only the settling
readings, and a second, complete weighing revealed the "final weight" flag. Keep the phone close
and in sight, because a body standing on the scale absorbs 2.4 GHz; in the first capture the signal
dropped to -90 dBm and the final frame never showed up. Know the expected value: decoding is much
easier when you can look for a number you already know, the weight shown by the app, inside the
bytes.

## 3. Find the device in the haystack

A two-minute trace holds thousands of packets, because a home is full of Bluetooth devices. The
first capture had advertisements from about thirty of them, most of them Apple devices. Three
things gave the scale away:

- it appeared only while someone was standing on it;
- its manufacturer data used company ID `0xFFFF`, which the Bluetooth SIG reserves for testing,
  instead of a registered vendor ID;
- its own MAC address appeared inside the payload, and the iPhone app started advertising a
  128-bit UUID that ended with that same address.

The only connection in the trace was traffic to another accessory, encrypted and unrelated. The
scale never connects. It only broadcasts, and the app talks back with advertisements of its own.

## 4. Decode the payload

With the scale's frames isolated, decoding is a matter of correlation:

1. Line up the frames in time and look at which bytes change while you step on and stand still.
2. Look for the value shown by the app. 75.00 kg is `0x1D4C` as hundredths of a kg, i.e. the bytes
   `4c 1d` in little-endian order.
3. Explain every other field: the MAC address, a counter, a timestamp that matches the time the app
   sent, a session token the app hands out.
4. Make a second capture to confirm, and compare the last frames: one byte goes from `0x02` to `0x23`
   when the weight is final.

The result is documented in [protocol.md](protocol.md), and
[`tools/decode_capture.py`](../tools/decode_capture.py) prints any capture decoded:

```sh
python3 tools/decode_capture.py samples/complete-weighing.pklg
```

## 5. Look for prior work

We did this last; do it first. The label under the scale gives the model (ES-CS20M) and the FCC ID
(`2APXUES-CS20M`). Searching for them leads to open-source projects that already decode the same
frames, and that also explain bits we could not: the display unit in the status byte and a
provisional "stable but not committed" state seen on other units. Your captures are still worth
making: they confirm or correct what others found on different units, and they show what nobody
documented yet, like the app's replies. See [related-work.md](related-work.md).

## 6. Before you publish a capture

A raw `.pklg` is personal data: it contains the phone's Bluetooth address, model and iOS version,
the names and addresses of the devices around you, and here also the owner's body weight. The same
goes for photos of the device: the label carries a serial number, masked in
[the published photo](images/es-cs20m-label.jpg).
[`tools/anonymize_capture.py`](../tools/anonymize_capture.py) keeps only the scale's frames and the
app's replies and rewrites the identifiers. The samples in this repository were made with:

```sh
python3 tools/anonymize_capture.py raw.pklg samples/complete-weighing.pklg \
    --mac C0:FF:EE:12:34:56 --token 123456 --weight-factor 0.69444444
```

Timing and structure are real; the scale's MAC, the session token and the weights are not.
