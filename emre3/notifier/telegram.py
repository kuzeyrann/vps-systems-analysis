"""Telegram Notifier"""
class TelegramNotifier:
    def __init__(self, config):
        self.config = config
    async def initialize(self): pass
    async def send_message(self, message): print(f"[TG] {message}")
    async def shutdown(self): pass
