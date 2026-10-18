"""Continuous BLE advertisement scanning with bleak (BlueZ on the Raspberry Pi)."""
import asyncio

from bleak import BleakScanner

from .protocol import COMPANY_ID, parse_frame


def make_callback(on_frame):
    def callback(device, advertisement_data):
        data = advertisement_data.manufacturer_data.get(COMPANY_ID)
        frame = parse_frame(data) if data else None
        if frame:
            on_frame(frame, advertisement_data.rssi)

    return callback


async def listen(on_frame):
    # The scale sends non-connectable, non-scannable advertisements: even with the default
    # active scanning the Raspberry Pi sends it nothing, it only listens.
    async with BleakScanner(detection_callback=make_callback(on_frame)):
        await asyncio.Event().wait()
