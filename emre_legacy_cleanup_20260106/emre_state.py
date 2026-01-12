# emre_state.py
import time


class TradeState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.status = "FLAT"        # FLAT | OPEN
        self.side = None
        self.entry = None
        self.stop = None
        self.tp1 = None
        self.tp2 = None
        self.tp3 = None

        self.tp1_hit = False
        self.opened_at = None
        self.last_update = None

    def open(self, side, entry, stop, tp1, tp2=None, tp3=None):
        self.status = "OPEN"
        self.side = side
        self.entry = entry
        self.stop = stop
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.tp1_hit = False
        self.opened_at = time.time()
        self.last_update = time.time()

    def mark_tp1(self):
        self.tp1_hit = True
        self.last_update = time.time()

    def close(self):
        self.reset()

    def is_open(self):
        return self.status == "OPEN"

    def snapshot(self):
        return {
            "status": self.status,
            "side": self.side,
            "entry": self.entry,
            "stop": self.stop,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "tp1_hit": self.tp1_hit,
            "opened_at": self.opened_at,
            "last_update": self.last_update,
        }
