import os, time, json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta

from emre_tp_micro import compute_tp1
from emre_tp_targets import compute_targets, compute_plan

UTC3 = timezone(timedelta(hours=3))
def now(): return datetime.now(UTC3).strftime("%H:%M:%S")

def safe_float(x, d=0.0):
    try: return float(x)
    except: return d

def env_int(k, d):
    try: return int(os.getenv(k, d))
    except: return d


@dataclass
class State:
    is_open: bool = False
    side: str = "NA"
    entry: float = 0.0
    stop: float = 0.0
    gh: float = 0.0
    tp1: float = 0.0
    tp1_sent: bool = False
    plan_sent: bool = False
    opened_ts: float = 0.0


class EmreCore:
    def __init__(self):
        self.symbol = "BTCUSDT"
        self.loop_sleep = env_int("EMRE_LOOP_SLEEP_SEC", 10)
        self.energy_timeout = env_int("EMRE_ENERGY_TIMEOUT_SEC", 1800)
        self.heartbeat_sec = env_int("EMRE_HEARTBEAT_SEC", 60)
        self.state_path = "/opt/emre/emre_state.json"
        self.state = self._load_state()
        self._market = None
        self._last_hb = 0
        self._last_continue = 0
        self._last_hourly = 0

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    raw = json.load(f)
                return State(
                    is_open=raw.get("is_open", False),
                    side=raw.get("side", "NA"),
                    entry=raw.get("entry", 0.0),
                    stop=raw.get("stop", 0.0),
                    gh=raw.get("gh", 0.0),
                    tp1=raw.get("tp1", 0.0),
                    tp1_sent=raw.get("tp1_sent", False),
                    plan_sent=raw.get("plan_sent", False),
                    opened_ts=raw.get("opened_ts", 0.0),
                )
            except:
                pass
        return State()

    def _save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    def _market_obj(self):
        if not self._market:
            from emre_market import EmreMarket
            self._market = EmreMarket(self.symbol)
        return self._market

    def _send(self, msg):
        from telegram_sender import send_message
        send_message(msg)

    def _open_msg(self):
        return (
            f"EMRE OPEN {self.symbol} {self.state.side}\n"
            f"entry: {self.state.entry:.2f}\n"
            f"stop: {self.state.stop:.2f}\n"
            f"GH: {self.state.gh:.2f}\n"
            f"TP1: bekleniyor\n"
            f"time: {now()}"
        )

    def _tp1_msg(self):
        return (
            f"TP1 ONAY {self.symbol} {self.state.side}\n"
            f"TP1: {self.state.tp1:.2f}\n"
            f"time: {now()}"
        )

    def _plan_msg(self, tp2, tp3, tp4, regime):
        return (
            f"EMRE PLAN {self.symbol} {self.state.side}\n"
            f"TP2: {tp2:.2f}\n"
            f"TP3: {tp3:.2f}\n"
            f"TP4: {tp4:.2f}\n"
            f"regime: {regime}\n"
            f"stop: {self.state.stop:.2f}\n"
            f"time: {now()}"
        )

    def _heartbeat(self, price):
        print(
            f"[HEARTBEAT] {now()} "
            f"is_open={self.state.is_open} "
            f"side={self.state.side} "
            f"price={price:.2f}"
        )

    def step(self):
        mem = {}
        self._market_obj().update_memory(mem)
        from emre_trader import decide
        return decide(mem), mem

    def loop(self):
        print("=== EMRE Core started ===")
        while True:
            sig, mem = self.step()
            now_ts = time.time()
            side = getattr(sig, "side", "NO-TRADE")
            price = safe_float(mem.get("1m", {}).get("price"), 0.0)

            # HEARTBEAT
            if now_ts - self._last_hb >= self.heartbeat_sec:
                self._last_hb = now_ts
                self._heartbeat(price)

            # DEVAM (15 dk) - pozisyon açıksa düzenli “yaşıyor” mesajı
            if self.state.is_open and (now_ts - self._last_continue) >= 900:
                self._last_continue = now_ts
                self._send(
                    f"[DEVAM] {self.symbol} {self.state.side} "
                    f"entry={self.state.entry:.2f} stop={self.state.stop:.2f} "
                    f"gh={self.state.gh:.2f} price={price:.2f} time={now()}"
                )

            # SAATLIK (1h) - sistem yaşıyor mesajı (pozisyon açık/kapalı)
            if (now_ts - self._last_hourly) >= 3600:
                self._last_hourly = now_ts
                self._send(
                    f"[SAATLIK] {self.symbol} is_open={self.state.is_open} "
                    f"side={self.state.side} price={price:.2f} time={now()}"
                )

            # 1) STOP (mutlak kapatma)
            if self.state.is_open:
                if (
                    (self.state.side == "LONG" and price <= self.state.stop) or
                    (self.state.side == "SHORT" and price >= self.state.stop)
                ):
                    self.state = State()
                    self._save_state()
                    continue

            # 2) TERS SİNYAL (kapat, sonra OPEN bloğu yeni yönü açacak)
            if self.state.is_open and side in ("LONG", "SHORT") and side != self.state.side:
                self.state = State()
                self._save_state()

            # OPEN
            if not self.state.is_open and side in ("LONG", "SHORT"):
                self.state = State(
                    is_open=True,
                    side=side,
                    entry=safe_float(getattr(sig, "entry", price)),
                    stop=0.0,
                    gh=0.0,
                    opened_ts=now_ts,
                )

                # Entry-aligned plan (Stop + GH(H1) + TP2/3/4)
                stop, gh, tp2, tp3, tp4, regime = compute_plan(mem, self.state.entry, side)
                self.state.stop = safe_float(stop, 0.0)
                self.state.gh = safe_float(gh, self.state.entry)
                self.state.plan_sent = True

                self._save_state()
                self._send(self._open_msg())
                self._send(self._plan_msg(tp2, tp3, tp4, regime))

            # TP1
            if self.state.is_open and not self.state.tp1_sent:
                tp1 = compute_tp1(mem, self.state.entry, self.state.side)
                if tp1 and abs(tp1 - self.state.entry) > 0:
                    self.state.tp1 = tp1
                    self.state.tp1_sent = True
                    D = abs(tp1 - self.state.entry)
                    if self.state.side == "LONG":
                        self.state.stop = self.state.entry - 0.2 * D
                    else:
                        self.state.stop = self.state.entry + 0.2 * D
                    self._save_state()
                    self._send(self._tp1_msg())

            # PLAN (dokunulmadı)
            if self.state.is_open and self.state.tp1_sent and not self.state.plan_sent:
                tp2, tp3, tp4, regime = compute_targets(
                    mem, self.state.entry, self.state.side, self.state.tp1
                )
                self.state.plan_sent = True
                self._save_state()
                self._send(self._plan_msg(tp2, tp3, tp4, regime))

            # ENERGY STOP (dokunulmadı)
            if self.state.is_open:
                if now_ts - self.state.opened_ts > self.energy_timeout:
                    if abs(price - self.state.entry) < abs(self.state.gh - self.state.entry):
                        self.state = State()
                        self._save_state()

            time.sleep(self.loop_sleep)


def run():
    print("=== EMRE başlatılıyor ===")
    EmreCore().loop()


if __name__ == "__main__":
    run()
