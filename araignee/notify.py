"""Notifications Telegram (optionnelles) : TELEGRAM_TOKEN + TELEGRAM_CHAT_ID."""
import json
import os
import urllib.request


def telegram():
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return None

    def send(text):
        try:
            body = json.dumps({"chat_id": chat, "text": text}).encode()
            req = urllib.request.Request("https://api.telegram.org/bot{}/sendMessage".format(token),
                                         data=body, headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print("  (telegram indisponible :", e, ")")

    return send
