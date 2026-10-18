#!/usr/bin/env bash
# Installs scale-bot as a systemd service on the Raspberry Pi. Usage: sudo ./install.sh
# Run it again to update: an existing configuration is left untouched.
set -euo pipefail

APP_DIR=/opt/scale-bot
CONFIG=/etc/scale-bot.toml
SERVICE_USER=scalebot
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run it as root: sudo $0" >&2
  exit 1
fi

# On Debian / Raspberry Pi OS the venv module and BlueZ are separate packages
missing=()
python3 -c 'import ensurepip' 2>/dev/null || missing+=(python3-venv)
command -v bluetoothctl >/dev/null || missing+=(bluez)
if (( ${#missing[@]} )); then
  apt-get update
  apt-get install -y "${missing[@]}"
fi

if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --user-group --no-create-home --home-dir /var/lib/scale-bot \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

python3 -m venv "$APP_DIR/venv"
# build from a copy, so that no root-owned build/ and *.egg-info end up in the repository clone
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
cp -r "$SRC_DIR/pyproject.toml" "$SRC_DIR/scale_bot" "$build_dir/"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade "$build_dir"

if [[ ! -f $CONFIG ]]; then
  install -m 640 -o root -g "$SERVICE_USER" "$SRC_DIR/config.example.toml" "$CONFIG"
  echo "Created $CONFIG: fill in the Telegram token and chat_id."
fi

install -m 644 "$SRC_DIR/scale-bot.service" /etc/systemd/system/scale-bot.service
systemctl daemon-reload
systemctl enable scale-bot.service
systemctl restart scale-bot.service

cat <<EOF

scale-bot is installed and running.
  Configuration:  sudo nano $CONFIG   (then: sudo systemctl restart scale-bot)
  Logs:           journalctl -u scale-bot -f
  Commands:       sudo $APP_DIR/venv/bin/scale-bot --config $CONFIG {find-chat,test,list}
EOF
