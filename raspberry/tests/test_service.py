import asyncio
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scale_bot.config import load_config
from scale_bot.pklg import scale_frames
from scale_bot.protocol import parse_frame
from scale_bot.service import Service, format_message
from scale_bot.storage import Storage
from scale_bot.telegram import Telegram, TelegramError

from test_protocol import COMPLETE

RASPBERRY = Path(__file__).resolve().parents[1]


class FakeTelegram:
    """Local HTTP server that answers like the Bot API and records the requests."""

    def __init__(self):
        self.requests = []
        self.fail_next = 0  # how many requests to reject with a 502
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append((self.path, body))
                if fake.fail_next:
                    fake.fail_next -= 1
                    self.send_error(502)
                    return
                if self.path.endswith("/getUpdates"):
                    result = [{"update_id": 1, "message": {"chat": {"id": 42, "type": "private", "first_name": "Ada"}}}]
                else:
                    result = {"message_id": len(fake.requests)}
                payload = json.dumps({"ok": True, "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def texts(self):
        return [body["text"] for path, body in self.requests if path.endswith("/sendMessage")]


def replay(service, path=COMPLETE):
    for _, rssi, data in scale_frames(path):
        service.on_frame(parse_frame(data), rssi)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTelegram()
        self.telegram = Telegram("123:abc", chat_id=42, api_url=self.fake.url, timeout=5)
        self.storage = Storage(":memory:")

    def tearDown(self):
        self.fake.close()

    def test_capture_reaches_telegram(self):
        service = Service(self.storage, self.telegram)
        replay(service)
        self.assertTrue(asyncio.run(service.deliver()))
        self.assertEqual(len(self.fake.texts()), 1)
        self.assertIn("75.00 kg", self.fake.texts()[0])
        path, body = self.fake.requests[0]
        self.assertEqual(path, "/bot123:abc/sendMessage")
        self.assertEqual(body["chat_id"], 42)
        self.assertIsNotNone(self.storage.latest(1)[0]["sent_at"])

    def test_network_down_then_retry(self):
        service = Service(self.storage, self.telegram)
        replay(service)
        self.fake.fail_next = 1
        self.assertFalse(asyncio.run(service.deliver()))
        self.assertEqual(len(self.storage.unsent()), 1)
        self.assertTrue(asyncio.run(service.deliver()))
        self.assertEqual(self.storage.unsent(), [])

    def test_delivery_loop_retries_by_itself(self):
        service = Service(self.storage, self.telegram, retry_seconds=0.2)
        self.fake.fail_next = 1

        async def scenario():
            loop_task = asyncio.create_task(service.delivery_loop())
            await asyncio.sleep(0.05)
            replay(service)  # measurement complete: the loop tries at once, fails, retries after 0.2 s
            for _ in range(50):
                if not self.storage.unsent():
                    break
                await asyncio.sleep(0.05)
            loop_task.cancel()

        asyncio.run(scenario())
        self.assertEqual(self.storage.unsent(), [])
        self.assertEqual(len(self.fake.texts()), 2)  # one failed attempt, one delivered

    def test_restart_does_not_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/measurements.sqlite3"
            first = Service(Storage(db), self.telegram)
            replay(first)
            asyncio.run(first.deliver())
            second = Service(Storage(db), self.telegram)  # same store, the scale still repeats the final frame
            replay(second)
            asyncio.run(second.deliver())
            self.assertEqual(len(Storage(db).latest(10)), 1)
        self.assertEqual(len(self.fake.texts()), 1)

    def test_mac_filter(self):
        service = Service(self.storage, self.telegram, scale_mac="AA:BB:CC:DD:EE:FF")
        replay(service)
        self.assertEqual(self.storage.latest(10), [])

    def test_find_chat(self):
        self.assertEqual(self.telegram.chats(), {42: ("private", "Ada")})

    def test_readable_telegram_error(self):
        with self.assertRaises(TelegramError):
            Telegram("123:abc", 42, api_url="http://127.0.0.1:9", timeout=2).send("x")


class FormatAndConfigTest(unittest.TestCase):
    def test_message_with_difference(self):
        previous = {"weight_kg": 75.4, "received_at": 1792000000}
        row = {"weight_kg": 75.0, "received_at": 1792229232}
        text = format_message(row, previous)
        self.assertTrue(text.startswith("⚖️ 75.00 kg\n"))
        self.assertRegex(text, r"\n−0\.40 kg since \d{4}-\d{2}-\d{2}$")
        self.assertIn("Same as on", format_message(row, {"weight_kg": 75.0, "received_at": 1792000000}))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_example_config(self):
        config = load_config(RASPBERRY / "config.example.toml")
        self.assertIsNone(config.telegram_token)
        self.assertIsNone(config.telegram_chat_id)
        self.assertIsNone(config.scale_mac)
        self.assertEqual(config.database, "/var/lib/scale-bot/measurements.sqlite3")

    @mock.patch.dict(os.environ, {"TELEGRAM_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "-1001", "SCALE_MAC": "c0:ff:ee:12:34:56",
                                  "DATABASE": "/data/measurements.sqlite3"}, clear=True)
    def test_environment_wins(self):
        config = load_config(RASPBERRY / "config.example.toml")
        self.assertEqual(config.telegram_token, "123:abc")
        self.assertEqual(config.telegram_chat_id, "-1001")
        self.assertEqual(config.scale_mac, "C0:FF:EE:12:34:56")
        self.assertEqual(config.database, "/data/measurements.sqlite3")


if __name__ == "__main__":
    unittest.main()
