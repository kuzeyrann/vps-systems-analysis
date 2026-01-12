#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
# .env yükle
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
    print(f"[CORE] .env yüklendi. TOKEN: {'VAR' if os.getenv('TELEGRAM_BOT_TOKEN') else 'YOK'}")
import os
import time
from typing import Any, Dict, Optional

from .position import Position, Leg

from market.market import MarketAdapter
from signals.signal_engine import SignalEngine
from risk.engine import RiskEngine
from risk.models import RiskSet
from risk.config import RiskConfig
from tp1.tp1_module import TP1Module
from notifier.notifier import Notifier

from exit.reverse_engine import ReverseEngine


def env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


# ===== TELEGRAM INTEGRATION =====
def send_telegram_message(event_type: str, payload: Dict[str, Any]) -> bool:
    """Telegram'a mesaj gönder"""
    try:
        TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        BOT_NAME = os.getenv("EMRE3_NAME", "EMRE3")
        
        if not TOKEN or not CHAT_ID:
            return False
        
        import requests
        
        if event_type == "OPEN":
            msg = f"🟢 <b>OPEN {payload.get('side', '')}</b>\n"
            msg += f"Entry: <code>{payload.get('entry')}</code>\n"
            msg += f"Stop: <code>{payload.get('stop')}</code>\n"
            if payload.get('reason'):
                msg += f"Reason: {payload.get('reason')[:80]}"
                
        elif event_type == "TP1_EVENT":
            msg = f"🟡 <b>TP1 {payload.get('side', '')}</b>\n"
            msg += f"Price: <code>{payload.get('tp1_price')}</code>"
            
        elif event_type == "STOP_TOUCH":
            msg = f"🔴 <b>STOP TOUCH {payload.get('side', '')}</b>\n"
            msg += f"Price: <code>{payload.get('price')}</code>\n"
            msg += f"Entry: <code>{payload.get('entry')}</code> → Stop: <code>{payload.get('stop')}</code>"
            
        elif event_type == "CLOSE":
            msg = f"⚫ <b>CLOSE {payload.get('side', '')}</b>\n"
            msg += f"Reason: {payload.get('reason', '')}"
            
        elif event_type == "HEARTBEAT":
            # Saat başı gönder
            if time.localtime().tm_min == 0 and time.localtime().tm_sec < 10:
                msg = f"📊 <b>{BOT_NAME} Heartbeat</b>\n"
                msg += f"Price: <code>{payload.get('price')}</code>\n"
                msg += f"Long: {payload.get('has_long')} | Short: {payload.get('has_short')}"
            else:
                return True  # Mesaj gönderme
                
        elif event_type == "DECISION":
            # Sadece NO-TRADE durumlarında konsolidasyon bilgisi gönder
            side = payload.get('side', '')
            meta = payload.get('meta', {})
            
            if side == "NO-TRADE" and meta.get('market_condition', {}).get('consolidation'):
                msg = f"⏸️ <b>NO TRADE - Consolidation</b>\n"
                msg += f"Price: <code>{payload.get('entry')}</code>\n"
                msg += f"BB Width: {meta.get('bollinger', {}).get('width', 0):.4f}\n"
                msg += f"Score: {meta.get('market_condition', {}).get('score', 0):.2f}"
            else:
                return True  # Diğer DECISION'lar için mesaj gönderme
                
        else:
            return True  # Diğer event'ler için mesaj gönderme
        
        # Telegram'a gönder
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": f"[{BOT_NAME}] {msg}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=5)
        return response.status_code == 200
        
    except Exception:
        return False


class EmreCore:
    def __init__(self, symbol: str = "BTCUSDT"):
        self.market = MarketAdapter(symbol=symbol)
        self.signal_engine = SignalEngine()
        self.risk_engine = RiskEngine(RiskConfig())

        # TP1 module: tek-leg senaryoda aynen kullanılır.
        # Dual-leg (reverse) anında global state çakışmasın diye reverse_engine'in MicroTP1'i kullanılır.
        self.tp1 = TP1Module()

        self.reverse = ReverseEngine()
        self.notifier = Notifier(enabled=True)

        self.pos = Position()

        # risk sets per leg
        self.risk_long: Optional[RiskSet] = None
        self.risk_short: Optional[RiskSet] = None

        # phase per leg (0=before TP1, 1=after TP1)
        self.phase_long = 0
        self.phase_short = 0

        # timers
        self.loop_sleep = env_int("EMRE_LOOP_SLEEP_SEC", 5)
        self.heartbeat_sec = env_int("EMRE_HOURLY_SEC", 3600)
        self.risk_update_sec = env_int("EMRE_RISK_UPDATE_SEC", 900)

        self._last_hb = 0.0
        self._last_risk_update = 0.0

    def run(self) -> None:
        print("=== EMRE Core (v1 modular) started ===")
        # Başlangıç mesajı
        try:
            send_telegram_message("STARTUP", {"message": "EMRE3 BB Fix bot başlatıldı"})
        except:
            pass
        
        while True:
            try:
                self.tick()
            except Exception as e:
                print(f"[CORE_ERROR] {e}")
            time.sleep(self.loop_sleep)

    def tick(self) -> None:
        snap = self.market.fetch()
        legacy = snap.raw
        mem = snap.mem
        ts = int(mem.get("ts", int(time.time())))
        price = float(mem.get("price") or 0.0)

        now = time.time()
        if now - self._last_hb >= self.heartbeat_sec:
            self._last_hb = now
            self._emit("HEARTBEAT", {
                "price": price,
                "has_long": self.pos.has_long,
                "has_short": self.pos.has_short,
            })

        if mem.get("error"):
            return

        # 1) FLAT: open normal entry
        if not self.pos.any_open:
            sig = self.signal_engine.decide(legacy, ts=ts)
            if sig.side in ("LONG", "SHORT"):
                self._emit("DECISION", {"side": sig.side, "entry": sig.entry, "reason": sig.reason, "meta": sig.meta, "ts": ts})
                mem2 = dict(mem)
                mem2["entry_mode"] = (sig.meta or {}).get("entry_mode")
                mem2["entry_gate"] = (sig.meta or {}).get("gate")
                self._open_leg(sig.side, sig.entry, mem2, ts)
            return

        # 2) If any leg open: check stops
        self._check_stop_leg("LONG", price, ts)
        self._check_stop_leg("SHORT", price, ts)

        # If stop closed both, exit early
        if not self.pos.any_open:
            return

        # 3) While in position: we still evaluate entry signals for COUNTER ENTRY
        sig = self.signal_engine.decide(legacy, ts=ts)
        if sig.side in ("LONG", "SHORT"):
            self._emit("DECISION", {"side": sig.side, "entry": sig.entry, "reason": sig.reason, "meta": sig.meta, "ts": ts})
        mem2 = dict(mem)
        mem2["entry_mode"] = (sig.meta or {}).get("entry_mode")
        mem2["entry_gate"] = (sig.meta or {}).get("gate")
        if sig.side == "LONG" and self.pos.has_short and not self.pos.has_long:
            # only one leg open (short); counter entry opens long
            self._reverse_entry("SHORT", "LONG", sig.entry, mem2, ts)
        elif sig.side == "SHORT" and self.pos.has_long and not self.pos.has_short:
            self._reverse_entry("LONG", "SHORT", sig.entry, mem2, ts)
        elif sig.side == "SHORT" and self.pos.has_long and self.pos.has_short is False:
            # long open, short not open yet -> open short
            self._reverse_entry("LONG", "SHORT", sig.entry, mem2, ts)
        elif sig.side == "LONG" and self.pos.has_short and self.pos.has_long is False:
            self._reverse_entry("SHORT", "LONG", sig.entry, mem2, ts)

        # 4) TP1 processing
        # - single-leg: keep using existing TP1Module (no change)
        # - dual-leg: use reverse_engine MicroTP1 per leg (no global clash)
        if self.pos.has_long and not self.pos.has_short:
            self._tp1_single_leg("LONG", mem, ts)
        elif self.pos.has_short and not self.pos.has_long:
            self._tp1_single_leg("SHORT", mem, ts)
        else:
            # dual-leg: check TP1 per leg and apply authority transfer
            self._tp1_dual_leg(mem, ts)
        # 5) Risk update (DISABLED - statik stop/targets)
        # intentionally no-op

    # ---------------- OPEN / CLOSE ----------------

    def _open_leg(self, side: str, entry: float, mem: Dict[str, Any], ts: int, reason: str = "entry") -> None:
        leg = self.pos.get_leg(side)
        if leg is None:
            return
        if leg.is_open:
            return

        self.pos.open_leg(side, float(entry), ts)
        self.reverse.on_new_leg_opened(side)

        risk = self.risk_engine.open(mem, side=side, entry=float(entry), ts=ts)
        if side == "LONG":
            self.risk_long = risk
            self.phase_long = 0
            self.pos.long.stop = float(risk.stop)
            self.pos.long.risk_set_id = risk.id
            self.pos.long.last_risk_update_ts = ts
        else:
            self.risk_short = risk
            self.phase_short = 0
            self.pos.short.stop = float(risk.stop)
            self.pos.short.risk_set_id = risk.id
            self.pos.short.last_risk_update_ts = ts

        self._emit("OPEN", {
            "side": side,
            "entry": float(entry),
            "stop": float(risk.stop),
            "tp2": risk.tp2,
            "tp3": risk.tp3,
            "tp4": risk.tp4,
            "regime": mem.get("regime"),
            "vol_1m": float(mem.get("vol_1m") or 0.0),
            "range15": float(mem.get("range15") or 0.0),
            "reason": reason,
        })


    def _reverse_entry(self, from_side: str, to_side: str, entry: float, mem: Dict[str, Any], ts: int) -> None:
        """Reverse is the ONLY exit mechanism in v1.2.
        Close the currently-open leg, then open the opposite leg.
        """
        from_leg = self.pos.get_leg(from_side)
        if from_leg is not None and from_leg.is_open:
            self._emit("AUTHORITY_SHIFT", {"from": from_side, "to": to_side, "reason": "reverse_entry", "ts": ts})
            self._close_leg(from_side, reason="reverse_entry", payload={"to": to_side, "price": float(entry), "ts": ts})

        # Open the new leg (entry discipline is unchanged; only exit authority moved here)
        self._open_leg(to_side, entry, mem, ts, reason="reverse_entry")

    def _close_leg(self, side: str, reason: str, payload: Dict[str, Any]) -> None:
        self._emit("CLOSE", {"side": side, "reason": reason, **payload})
        self.pos.close_leg(side)
        if side == "LONG":
            self.risk_long = None
            self.phase_long = 0
        else:
            self.risk_short = None
            self.phase_short = 0

    # ---------------- STOP ----------------

    def _check_stop_leg(self, side: str, price: float, ts: int) -> None:
        leg = self.pos.get_leg(side)
        if leg is None or not leg.is_open:
            return
        stop = float(leg.stop)
        if side == "LONG":
            hit = price <= stop
        else:
            hit = price >= stop
        if hit:
            # v1.2: stop is informational only; do not force-exit.
            leg.stop_touched = True
            leg.stop_touch_ts = int(ts)
            leg.stop_touch_price = float(price)
            self._emit("STOP_TOUCH", {"side": side, "entry": leg.entry, "stop": stop, "price": price, "ts": ts})

    # ---------------- TP1 ----------------

    def _tp1_single_leg(self, side: str, mem: Dict[str, Any], ts: int) -> None:
        leg = self.pos.get_leg(side)
        if leg is None or not leg.is_open:
            return

        # keep old TP1 module behavior
        tp1_event = self.tp1.update(mem, side, leg.entry, ts)
        if tp1_event and not leg.tp_hits.get("TP1"):
            leg.tp_hits["TP1"] = True
            if side == "LONG":
                self.phase_long = 1
            else:
                self.phase_short = 1
            self._emit("TP1_EVENT", {"side": side, "entry": leg.entry, "tp1_price": tp1_event.price})

    def _tp1_dual_leg(self, mem: Dict[str, Any], ts: int) -> None:
        # check TP1 confirmations per leg with ReverseEngine (leg-local)
        # rule: if SHORT TP1 -> close LONG; if LONG TP1 -> close SHORT
        if self.pos.has_short:
            s_leg = self.pos.short
            dec = self.reverse.on_tick_tp1_check(mem, side="SHORT", entry=s_leg.entry)
            if dec and (not s_leg.tp_hits.get("TP1")):
                s_leg.tp_hits["TP1"] = True
                self.phase_short = 1
                self._emit("TP1_EVENT", {"side": "SHORT", "entry": s_leg.entry, "tp1_price": dec.tp1_price})
                # authority transfer
                if self.pos.has_long:
                    self._close_leg("LONG", reason="authority_short_tp1", payload={"ts": ts, "tp1_price": dec.tp1_price})

        if self.pos.has_long:
            l_leg = self.pos.long
            dec = self.reverse.on_tick_tp1_check(mem, side="LONG", entry=l_leg.entry)
            if dec and (not l_leg.tp_hits.get("TP1")):
                l_leg.tp_hits["TP1"] = True
                self.phase_long = 1
                self._emit("TP1_EVENT", {"side": "LONG", "entry": l_leg.entry, "tp1_price": dec.tp1_price})
                # authority transfer
                if self.pos.has_short:
                    self._close_leg("SHORT", reason="authority_long_tp1", payload={"ts": ts, "tp1_price": dec.tp1_price})

    # ---------------- RISK UPDATE ----------------

    def _risk_update_leg(self, side: str, mem: Dict[str, Any], ts: int) -> None:
        leg = self.pos.get_leg(side)
        if leg is None or not leg.is_open:
            return

        current = self.risk_long if side == "LONG" else self.risk_short
        if current is None:
            return

        phase = self.phase_long if side == "LONG" else self.phase_short

        proposal = self.risk_engine.update(mem, side=side, entry=leg.entry, current=current, ts=ts, phase=phase)
        if proposal is None:
            return

        old_stop = float(leg.stop)
        new_stop = float(proposal.stop)

        # never-worse stop
        apply_stop = False
        if side == "LONG" and new_stop > old_stop:
            apply_stop = True
        if side == "SHORT" and new_stop < old_stop:
            apply_stop = True

        # TP drift guard (TP2 serbest, TP3/4 trendte aşağı sıkışmasın için core seviyesinde koşullu)
        regime = (mem.get("regime") or "RANGE").upper()

        def drift_ok(old_tp: float, new_tp: float) -> bool:
            if old_tp == 0.0:
                return True
            max_drift = float(os.getenv("EMRE_MAX_TP_DRIFT", "0.20"))
            return abs(new_tp - old_tp) / abs(old_tp) <= max_drift

        tp2 = current.tp2
        tp3 = current.tp3
        tp4 = current.tp4

        # TP2: serbest (drift ile koru)
        if drift_ok(current.tp2, proposal.tp2):
            tp2 = proposal.tp2

        # TP3/TP4: TREND’de aşağı revizeye izin verme (seninle kilitlediğimiz kural)
        if regime == "TREND":
            if side == "LONG":
                if proposal.tp3 >= current.tp3 and drift_ok(current.tp3, proposal.tp3):
                    tp3 = proposal.tp3
                if proposal.tp4 >= current.tp4 and drift_ok(current.tp4, proposal.tp4):
                    tp4 = proposal.tp4
            else:
                if proposal.tp3 <= current.tp3 and drift_ok(current.tp3, proposal.tp3):
                    tp3 = proposal.tp3
                if proposal.tp4 <= current.tp4 and drift_ok(current.tp4, proposal.tp4):
                    tp4 = proposal.tp4
        else:
            # RANGE: serbest (drift ile koru)
            if drift_ok(current.tp3, proposal.tp3):
                tp3 = proposal.tp3
            if drift_ok(current.tp4, proposal.tp4):
                tp4 = proposal.tp4

        if apply_stop:
            leg.stop = new_stop
            new_set = RiskSet(
                id=proposal.id,
                created_ts=proposal.created_ts,
                stop=new_stop,
                tp2=tp2,
                tp3=tp3,
                tp4=tp4,
                meta=proposal.meta
            )
            if side == "LONG":
                self.risk_long = new_set
            else:
                self.risk_short = new_set

            self._emit("RISK_UPDATE", {
                "side": side,
                "entry": leg.entry,
                "old_stop": old_stop,
                "new_stop": new_stop,
                "tp2": tp2,
                "tp3": tp3,
                "tp4": tp4,
                "meta": proposal.meta
            })

    # ---------------- EMIT ----------------

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        # TELEGRAM gönderimi
        try:
            send_telegram_message(event_type, payload)
        except Exception as e:
            print(f"[TELEGRAM_ERROR] {e}")
        
        # ORİJİNAL PRINT'LER
        if event_type == "HEARTBEAT":
            print(f"[HEARTBEAT] price={payload.get('price')} has_long={payload.get('has_long')} has_short={payload.get('has_short')}")
        elif event_type == "OPEN":
            print(f"[OPEN] side={payload.get('side')} entry={payload.get('entry')} stop={payload.get('stop')} tp2={payload.get('tp2')} reason={payload.get('reason')}")
        elif event_type == "RISK_UPDATE":
            print(f"[RISK_UPDATE] {payload.get('side')} stop {payload.get('old_stop')} -> {payload.get('new_stop')}")
        elif event_type == "TP1_EVENT":
            print(f"[TP1_EVENT] side={payload.get('side')} tp1={payload.get('tp1_price')}")
        elif event_type == "STOP_HIT":
            print(f"[STOP_HIT] side={payload.get('side')} entry={payload.get('entry')} stop={payload.get('stop')} price={payload.get('price')}")
        elif event_type == "STOP_TOUCH":
            print(f"[STOP_TOUCH] side={payload.get('side')} entry={payload.get('entry')} stop={payload.get('stop')} price={payload.get('price')}")
        elif event_type == "DECISION":
            m = payload.get("meta") or {}
            print(f"[DECISION] side={payload.get('side')} entry={payload.get('entry')} gate={m.get('gate')} mode={m.get('entry_mode')} r4={m.get('r4')} r8={m.get('r8')} structure={m.get('structure')} trap={m.get('trap')}")
        elif event_type == "AUTHORITY_SHIFT":
            print(f"[AUTHORITY_SHIFT] {payload.get('from')} -> {payload.get('to')} reason={payload.get('reason')}")
        elif event_type == "CLOSE":
            print(f"[CLOSE] side={payload.get('side')} reason={payload.get('reason')}")
        else:
            print(f"[{event_type}] {payload}")

        self.notifier.emit(event_type, payload)


def run():
    symbol = os.getenv("EMRE_SYMBOL", "BTCUSDT")
    EmreCore(symbol=symbol).run()
