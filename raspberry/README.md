# scale-bot: the scale on Telegram, from a Raspberry Pi

A service that runs all the time on a Raspberry Pi near the scale: it listens to the BLE
advertisements, spots the final weight, stores it in SQLite and sends it to a Telegram chat.

```
⚖️ 75.00 kg
2026-10-17 11:47
−0.40 kg since 2026-10-15
```

The Raspberry Pi only listens, so it should work alongside the phone app without disturbing it.

This service has not been tried on a real Raspberry Pi with the scale yet. The [tests](#development) run
on recorded captures with a fake Telegram server, but nobody has checked it with BlueZ, Docker on
the Pi and a real scale. If you try it, please open an issue with the result.

## What you need

- A Raspberry Pi with built-in Bluetooth (3B, 3B+, 4, 5, Zero W, Zero 2 W) running Raspberry Pi OS
  Bookworm or later (64-bit recommended), within a few metres of the scale.
- A Telegram bot: on Telegram, write to @BotFather, send `/newbot` and keep the token.

There are two ways to run it: Docker Compose, or a plain systemd service.

## Option A: Docker Compose

Bluetooth stays on the host: the container talks to the host's BlueZ through the D-Bus socket,
mounted read-only. No privileged mode and no host network are needed.

```sh
cd raspberry
cp .env.example .env               # then put the bot token in .env
docker compose build
docker compose run --rm scale-bot find-chat
```

`find-chat` lists the chats that wrote to the bot: send it any message first (or add it to a group
and write there), then copy the `chat_id` into `.env` as `TELEGRAM_CHAT_ID`. Then:

```sh
docker compose run --rm scale-bot test         # a test message should arrive
docker compose up -d                           # start listening, also after reboots
docker compose logs -f                         # follow the logs
docker compose run --rm scale-bot list         # latest stored measurements
```

The measurements live in the `data` volume. To try the whole chain without a scale, replay a sample
(it does not touch the store):

```sh
docker compose run --rm -v "$PWD/../samples:/samples:ro" scale-bot replay /samples/complete-weighing.pklg
```

A message "[capture replay] ⚖️ 75.00 kg" arrives on Telegram.

## Option B: systemd service

```sh
cd raspberry
sudo ./install.sh
```

The script installs what is missing (`python3-venv`, `bluez`) and creates the `scalebot` service
user, the Python environment in `/opt/scale-bot`, the configuration `/etc/scale-bot.toml` and the
`scale-bot` systemd service, which starts right away and at every boot. Run it again to update: an
existing configuration is kept.

```sh
alias scale-bot='sudo /opt/scale-bot/venv/bin/scale-bot --config /etc/scale-bot.toml'
sudo nano /etc/scale-bot.toml        # bot token, then chat_id from "scale-bot find-chat"
scale-bot test
sudo systemctl restart scale-bot
journalctl -u scale-bot -f
```

## Configuration

| Environment variable (Docker) | TOML key (systemd) | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | `[telegram] token` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | `[telegram] chat_id` | Chat that receives the measurements |
| `SCALE_MAC` | `[scale] mac` | Your scale's MAC, to ignore identical scales next door (empty = any) |
| `DATABASE` | `[storage] database` | SQLite file (the image sets `/data/measurements.sqlite3`) |

Environment variables win over the file. The time in the messages is the Raspberry Pi's: if it is
wrong, set the time zone with `sudo raspi-config` (*Localisation Options → Timezone*), and with
Docker also pass `TZ` (for example `TZ=Europe/Rome`) in `.env`.

## Commands

| Command | What it does |
|---|---|
| `listen` | Listens to the scale, stores and sends the measurements (the default in Docker) |
| `replay FILE` | Runs a `.pklg` capture through the service and sends the result |
| `test` | Sends a test message to Telegram |
| `find-chat` | Shows the chats that wrote to the bot, with their `chat_id` |
| `list [-n N]` | Shows the latest stored measurements |

Add `-v` before the command to log every frame received.

## How it works

| Module | Job |
|---|---|
| `listener.py` | Continuous BLE scanning with [bleak](https://github.com/hbldh/bleak) (BlueZ) |
| `protocol.py` | Frame decoding and final-weight detection (status `0x23`) |
| `storage.py` | SQLite store, with the time each measurement reached Telegram |
| `service.py` | Ties the pieces together: measurement → store → Telegram |
| `telegram.py` | Telegram Bot API, standard library only |

If the network is down, the measurement stays "pending" in the store and the service retries every
60 seconds, in order. The scale repeats the final weight for several seconds, so after a restart the
service compares the frame with the last stored measurement and does not store it twice. Without
Bluetooth the service exits with a message in the log, and Docker or systemd restart it.

## Limits

The scale does not say who is standing on it, so with several people in the house every weighing
goes to the same chat, and the difference is computed against the previous weighing, whoever it
was. The final weight is detected from bit `0x01` of the status byte, the same rule as
renpho-escs20m (see [protocol.md](../docs/protocol.md)); if a weighing produces no message, look at
the frames with `-v`. The bot sends messages but does not answer commands.

## Troubleshooting

| Symptom | What to check |
|---|---|
| "Bluetooth unavailable" in the log | `systemctl status bluetooth`; `bluetoothctl show` must say `Powered: yes`; with Docker, the `/run/dbus` mount |
| Bluetooth blocked | `rfkill list`; if *Soft blocked*: `sudo rfkill unblock bluetooth` |
| D-Bus access denied in Docker | On hosts with AppArmor D-Bus mediation, add `security_opt: [apparmor:unconfined]` to the service |
| No frames with `-v` | Distance: move the Raspberry Pi closer; a body on the scale absorbs the signal |
| "Telegram error: Unauthorized" | Wrong token |
| "Telegram error: Bad Request: chat not found" | Wrong `chat_id`, or you have not written to the bot yet |

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install .
cd tests && ../.venv/bin/python -m unittest -v
```

The tests use the samples in [`samples/`](../samples/) and a fake local Telegram server; the
[`raspberry.yml`](../.github/workflows/raspberry.yml) workflow runs them on Python 3.11 and 3.13,
then builds the Docker image and replays a sample inside it.
