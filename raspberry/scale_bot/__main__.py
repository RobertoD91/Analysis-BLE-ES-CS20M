"""Command line: scale-bot [--config FILE] {listen,replay,test,find-chat,list}."""
import argparse
import asyncio
import logging
import sys
from datetime import datetime

from .config import load_config
from .pklg import scale_frames
from .protocol import parse_frame
from .service import Service, format_message
from .storage import Storage
from .telegram import Telegram, TelegramError

log = logging.getLogger("scale_bot")


def make_telegram(config, need_chat=True):
    if config.telegram_token and (config.telegram_chat_id or not need_chat):
        return Telegram(config.telegram_token, config.telegram_chat_id)
    return None


async def cmd_listen(config, args):
    from bleak.exc import BleakError

    from .listener import listen

    service = Service(Storage(config.database), make_telegram(config), config.scale_mac)
    if service.telegram is None:
        log.warning("Telegram not configured: measurements are only stored in %s", config.database)
    delivery = asyncio.create_task(service.delivery_loop())
    log.info("Listening for scale %s; storing in %s", config.scale_mac or "(any)", config.database)
    try:
        await listen(service.on_frame)
    except (BleakError, OSError) as err:
        # OSError: no D-Bus socket, i.e. BlueZ or D-Bus are not running (or not mounted in Docker)
        log.error("Bluetooth unavailable (%s: %s). Is the bluetooth service running (systemctl status "
                  "bluetooth) and, with Docker, is /run/dbus mounted?", type(err).__name__, err)
        return 1
    finally:
        delivery.cancel()


async def cmd_replay(config, args):
    service = Service(Storage(":memory:"), make_telegram(config), config.scale_mac, message_prefix="[capture replay] ")
    for _, rssi, data in scale_frames(args.file):
        frame = parse_frame(data)
        if frame:
            service.on_frame(frame, rssi)
    rows = service.storage.unsent()
    if not rows:
        print("No final weight in the capture.")
        return 1
    for row in rows:
        print(format_message(row, service.storage.previous(row["id"])), end="\n\n")
    if service.telegram is None:
        print("Telegram not configured: nothing sent.")
        return 0
    if await service.deliver():
        print("Sent to Telegram.")
        return 0
    return 1


async def cmd_test(config, args):
    telegram = make_telegram(config)
    if telegram is None:
        print("Set the Telegram token and chat_id first.", file=sys.stderr)
        return 1
    telegram.send("BLE scale: Telegram setup OK.")
    print("Test message sent.")
    return 0


async def cmd_find_chat(config, args):
    telegram = make_telegram(config, need_chat=False)
    if telegram is None:
        print("Set the Telegram bot token first.", file=sys.stderr)
        return 1
    chats = telegram.chats()
    if not chats:
        print("No recent messages: write something to the bot (or in the group you added it to) and try again.")
        return 1
    for chat_id, (kind, name) in chats.items():
        print(f"chat_id = {chat_id}    # {kind}: {name}")
    return 0


async def cmd_list(config, args):
    for row in Storage(config.database).latest(args.n):
        when = datetime.fromtimestamp(row["received_at"]).strftime("%Y-%m-%d %H:%M")
        sent = "sent" if row["sent_at"] else "pending"
        print(f"{when}  {row['weight_kg']:>7.2f} kg  {row['mac']}  {sent}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="scale-bot", description="Listen to the BLE scale, store the measurements and send them to Telegram."
    )
    parser.add_argument("--config", help="TOML file (default: config.toml or /etc/scale-bot.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="also log every frame received")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("listen", help="listen to the scale, store and send the measurements")
    replay = sub.add_parser("replay", help="run a .pklg capture through the service and send the result")
    replay.add_argument("file")
    sub.add_parser("test", help="send a test message to Telegram")
    sub.add_parser("find-chat", help="show the chats that wrote to the bot, with their chat_id")
    listing = sub.add_parser("list", help="show the latest stored measurements")
    listing.add_argument("-n", type=int, default=20)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    config = load_config(args.config)
    log.debug("configuration: %s", config.path or "no file, defaults and environment")
    commands = {
        "listen": cmd_listen, "replay": cmd_replay, "test": cmd_test,
        "find-chat": cmd_find_chat, "list": cmd_list,
    }
    try:
        return asyncio.run(commands[args.command](config, args)) or 0
    except TelegramError as err:
        print(f"Telegram error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
