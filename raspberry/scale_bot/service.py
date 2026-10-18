"""From final measurements to the store and to Telegram, retrying while the network is down."""
import asyncio
import logging
import time
from datetime import datetime

from .protocol import MeasurementTracker
from .telegram import TelegramError

RETRY_SECONDS = 60

log = logging.getLogger("scale_bot")


def format_message(row, previous=None, prefix=""):
    lines = [
        f"{prefix}⚖️ {row['weight_kg']:.2f} kg",
        datetime.fromtimestamp(row["received_at"]).strftime("%Y-%m-%d %H:%M"),
    ]
    if previous is not None:
        delta = round(row["weight_kg"] - previous["weight_kg"], 2)
        day = datetime.fromtimestamp(previous["received_at"]).strftime("%Y-%m-%d")
        if delta == 0:
            lines.append(f"Same as on {day}")
        else:
            lines.append(f"{'+' if delta > 0 else '−'}{abs(delta):.2f} kg since {day}")
    return "\n".join(lines)


class Service:
    def __init__(self, storage, telegram=None, scale_mac=None, message_prefix="", retry_seconds=RETRY_SECONDS):
        self.storage = storage
        self.telegram = telegram
        self.scale_mac = scale_mac
        self.tracker = MeasurementTracker(storage.last_key())
        self.retry_seconds = retry_seconds
        self._prefix = message_prefix
        self._pending = asyncio.Event()

    def on_frame(self, frame, rssi=None):
        """Receives every scale frame; returns the measurement id when a measurement completes."""
        if self.scale_mac and frame.mac != self.scale_mac:
            return None
        log.debug("frame %s %.2f kg state 0x%02x rssi %s", frame.mac, frame.weight_kg, frame.state, rssi)
        measurement = self.tracker.update(frame)
        if measurement is None:
            return None
        measurement_id = self.storage.add(measurement, time.time())
        log.info("Final weight: %.2f kg (scale %s)", measurement.weight_kg, measurement.mac)
        self._pending.set()
        return measurement_id

    async def deliver(self):
        """Sends the measurements not yet on Telegram; True when none is left."""
        if self.telegram is None:
            return True
        for row in self.storage.unsent():
            text = format_message(row, self.storage.previous(row["id"]), self._prefix)
            try:
                await asyncio.to_thread(self.telegram.send, text)
            except TelegramError as err:
                log.warning("Telegram delivery failed (%s): retrying in %g s", err, self.retry_seconds)
                return False
            self.storage.mark_sent(row["id"], time.time())
            log.info("Measurement %d sent to Telegram", row["id"])
        return True

    async def delivery_loop(self):
        while True:
            self._pending.clear()
            await self.deliver()
            try:
                await asyncio.wait_for(self._pending.wait(), self.retry_seconds)
            except TimeoutError:
                pass
