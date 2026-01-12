#!/usr/bin/env python3
import os
import requests
import time

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_NAME = os.getenv("EMRE3_NAME", "EMRE3")

def send_message(text: str, max_retries: int = 3):
    """Telegram'a mesaj gönder"""
    if not TOKEN or not CHAT_ID:
        print(f"[{BOT_NAME}] Telegram token/chat_id eksik")
        return False
    
    message = f"🔧 [{BOT_NAME}] {text}"
    
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = {
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                print(f"[{BOT_NAME}] Telegram hatası {response.status_code}")
                time.sleep(1)
                
        except Exception as e:
            print(f"[{BOT_NAME}] Telegram exception: {e}")
            time.sleep(1)
    
    return False

# Test fonksiyonu
def test_telegram():
    """Telegram bağlantısını test et"""
    if send_message("🟢 EMRE3 Test Bot başlatıldı! BB Fix aktif."):
        print("✅ Telegram testi başarılı!")
    else:
        print("❌ Telegram testi başarısız. Token/chat_id kontrol et.")

if __name__ == "__main__":
    test_telegram()
