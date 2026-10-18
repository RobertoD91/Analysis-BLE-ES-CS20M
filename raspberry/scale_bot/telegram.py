"""Minimal client for the Telegram Bot API, standard library only."""
import json
import urllib.error
import urllib.request

API_URL = "https://api.telegram.org"


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token, chat_id=None, api_url=API_URL, timeout=15):
        self._base = f"{api_url}/bot{token}"
        self.chat_id = chat_id
        self._timeout = timeout

    def call(self, method, **params):
        request = urllib.request.Request(
            f"{self._base}/{method}",
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as err:
            # Telegram explains the error in the JSON body (wrong token, unknown chat...)
            try:
                reply = json.load(err)
            except ValueError:
                raise TelegramError(f"HTTP {err.code}") from err
        except OSError as err:
            raise TelegramError(f"network unreachable: {err}") from err
        if not reply.get("ok"):
            raise TelegramError(reply.get("description", "invalid response"))
        return reply["result"]

    def send(self, text):
        return self.call("sendMessage", chat_id=self.chat_id, text=text)

    def chats(self):
        """Chats that recently wrote to the bot: id, type and name."""
        found = {}
        for update in self.call("getUpdates"):
            message = update.get("message") or update.get("channel_post") or update.get("my_chat_member") or {}
            chat = message.get("chat")
            if chat:
                name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                found[chat["id"]] = (chat.get("type"), name or chat.get("username", ""))
        return found
