import os
import requests
from dotenv import load_dotenv

load_dotenv(override=False)  # prefer systemd EnvironmentFile; do not override

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def send_message(text: str):
    if not TOKEN or not CHAT_ID:
        print("[TG] Token veya chat_id yok")
        return

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        requests.post(API_URL, json=payload, timeout=10)
    except Exception as e:
        print("[TG] gönderim hatası:", e)
