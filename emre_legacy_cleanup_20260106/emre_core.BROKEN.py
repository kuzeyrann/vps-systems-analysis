#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMRE Core (State+Spam Fix)

- Market: mem["1m"] + mem["15m"] doldurur (emre_market.update_memory)
- Trader: emre_trader.decide(mem) -> Signal
- State engine:
  - OPEN: yeni pozisyon açılışı (LONG/SHORT)
  - UPDATE: aynı pozisyon devam ederken periyodik güncelleme (spam azaltır)
  - EXIT: yön değişince önce çıkış, sonra yeni OPEN
  - TP1 lock: pozisyon açıldığında tp1 sabitlenir; update'lerde tp1 asla değişmez

- NO-TRADE:
  - pozisyon YOKKEN: en fazla saatte 1 (değişse bile yine 1 saat)
  - pozisyon VARKEN: UPDATE her 5 dk (momentumdan bağımsız)

Bu dosya, tar.gz içindeki “çalışan” core taban alınarak düzenlendi:
- app.py uyumu: emre_core.run() var
- telegram_sender: send_message kullanır
- emre_market: EmreMarket.update_memory(mem) kullanır
- GH eklendi (Aşama 1) + UPDATE 15dk yapıldı
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

UTC3 = timezone(timedelta(hours=3))


def _now_str() -> str:
    return datetime.now(UTC3).strftime("%H:%M:%S")


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _clamp_int(x, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def _bp(a: float, b: float) -> float:
    """basis points difference a->b (absolute)"""
    if not a:
        return 0.0
    return abs((b - a) / a) * 10000.0


@dataclass
class _FallbackState:
    is_open: bool = False
    side: str = "NA"            # LONG / SHORT
    entry: float = 0.0
    stop: float = 0.0
    gh: float = 0.0
    gh_seen: bool = False
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    tp4: float = 0.0

    structure: str = "NA"
    trap: str = "NA"
    bias_4h: str = "NA"

    opened_ts: float = 0.0
    last_update_ts: float = 0.0
    tp1_hit: bool = False

    # spam control helpers
    last_sent_fp: str = ""
    last_state_key: str = ""


class EmreCore:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        loop_sleep: int = 10,

        # UPDATE throttles (kept for compatibility; loop enforces fixed cadence)
        update_interval_sec: int = 600,
        update_min_price_move_bp: int = 8,
        update_min_stop_move_bp: int = 8,

        # NO-TRADE throttles (kept for compatibility; loop enforces fixed cadence)
        no_trade_flat_interval_sec: int = 3600,
        no_trade_change_interval_sec: int = 600,
        no_trade_open_interval_sec: int = 300,

        # Hourly status (opsiyonel)
        status_interval_sec: int = 0,            # 0 => kapalı
        debug_log: bool = True,

        state_path: str = "/opt/emre/emre_state.json",
    ):
        self.symbol = symbol
        self.loop_sleep = int(loop_sleep)

        self.update_interval_sec = int(update_interval_sec)
        self.update_min_price_move_bp = int(update_min_price_move_bp)
        self.update_min_stop_move_bp = int(update_min_stop_move_bp)

        self.no_trade_flat_interval_sec = int(no_trade_flat_interval_sec)
        self.no_trade_change_interval_sec = int(no_trade_change_interval_sec)
        self.no_trade_open_interval_sec = int(no_trade_open_interval_sec)

        self.status_interval_sec = int(status_interval_sec)
        self.debug_log = bool(debug_log)

        self.state_path = state_path

        self._market = None
        self._last_telegram_ts = 0.0
        self._last_no_trade_ts = 0.0
        self._last_status_ts = 0.0

        # Load state
        self.state = self._load_state()

    # -----------------------------
    # Dependencies
    # -----------------------------
    def _get_market(self):
        if self._market is None:
            from emre_market import EmreMarket
            self._market = EmreMarket(symbol=self.symbol)
        return self._market

    def _send(self, text: str):
        from telegram_sender import send_message
        send_message(text)

    # -----------------------------
    # State load/save (prefers emre_state.py)
    # -----------------------------
    def _load_state(self):
        # Prefer project state engine if present
        try:
            import emre_state  # type: ignore
            # If emre_state has a loader, use it; else fall back to json
            if hasattr(emre_state, "load_state"):
                return emre_state.load_state(self.state_path)
            if hasattr(emre_state, "EmreState"):
                st = emre_state.EmreState(self.state_path)
                # Some implementations need explicit load()
                if hasattr(st, "load"):
                    st.load()
                return st
        except Exception:
            pass

        # Fallback: JSON to dataclass
        st = _FallbackState()
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                for k, v in data.items():
                    if hasattr(st, k):
                        setattr(st, k, v)
            except Exception:
                pass
        return st

    def _save_state(self):
        # If external state has save, use it
        try:
            if hasattr(self.state, "save"):
                self.state.save()
                return
        except Exception:
            pass

        # Fallback: JSON dump
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                if isinstance(self.state, _FallbackState):
                    json.dump(asdict(self.state), f, indent=2, ensure_ascii=False)
                else:
                    # best-effort: dump known attrs
                    out = {}
                    for k in asdict(_FallbackState()).keys():
                        if hasattr(self.state, k):
                            out[k] = getattr(self.state, k)
                    json.dump(out, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # -----------------------------
    # Fingerprints / dedupe
    # -----------------------------
    def _state_key(self, sig) -> str:
        side = getattr(sig, "side", "NA")
        entry = _safe_float(getattr(sig, "entry", 0.0), 0.0)
        stop = _safe_float(getattr(sig, "stop", 0.0), 0.0)
        tps = getattr(sig, "tps", []) or []
        tp1 = _safe_float(tps[0], 0.0) if len(tps) >= 1 else 0.0
        return f"{side}|{entry:.2f}|{stop:.2f}|{tp1:.2f}"

    def _fingerprint_open(self, side: str, entry: float, stop: float, tp1: float, tp2: float, tp3: float, tp4: float, key: str) -> str:
        return f"OPEN|{side}|{entry:.2f}|{stop:.2f}|{tp1:.2f}|{tp2:.2f}|{tp3:.2f}|{tp4:.2f}|{key}"

    def _fingerprint_update(self, side: str, price: float, stop: float, tp1: float, key: str) -> str:
        return f"UPD|{side}|{price:.2f}|{stop:.2f}|{tp1:.2f}|{key}"

    # -----------------------------
    # Formatters
    # -----------------------------
    def _fmt_open(self, sig, mem: Dict[str, Any]) -> str:
        tps = getattr(sig, "tps", []) or []
        tp1 = _safe_float(tps[0], 0.0) if len(tps) >= 1 else 0.0
        tp2 = _safe_float(tps[1], 0.0) if len(tps) >= 2 else 0.0
        tp3 = _safe_float(tps[2], 0.0) if len(tps) >= 3 else 0.0
        tp4 = _safe_float(tps[3], 0.0) if len(tps) >= 4 else 0.0

        side = getattr(sig, "side", "NA")
        entry = _safe_float(getattr(sig, "entry", 0.0), 0.0)
        stop = _safe_float(getattr(sig, "stop", 0.0), 0.0)
        # GH: entry ± 0.35 * |entry-stop| (only if stop is set)
        gh = 0.0
        try:
            d = abs(entry - stop)
            if d > 0 and side in ("LONG", "SHORT"):
                gh = entry + (0.35 * d) if side == "LONG" else entry - (0.35 * d)
        except Exception:
            gh = 0.0
        gh_line = f"• GH: <b>{gh:.2f}</b>\n" if gh else ""

        return (
            f"🚨 <b>EMRE OPEN</b>\n"
            f"• {self.symbol} | <b>{side}</b>\n"
            f"• entry: <b>{entry:.2f}</b>\n"
            f"• stop: <b>{stop:.2f}</b>\n"
            f"{gh_line}"
            f"• TP1: <b>{tp1:.2f}</b>\n"
            f"• TP2: {tp2:.2f}  TP3: {tp3:.2f}  TP4: {tp4:.2f}\n"
            f"• struct: {getattr(sig,'structure','')}  trap={getattr(sig,'trap','')}  bias={getattr(sig,'bias_4h','')}\n"
            f"• time: {_now_str()}\n"
        )

    def _fmt_update(self, mem: Dict[str, Any]) -> str:
        side = getattr(self.state, "side", "NA")
        entry = _safe_float(getattr(self.state, "entry", 0.0), 0.0)
        stop = _safe_float(getattr(self.state, "stop", 0.0), 0.0)
        gh = _safe_float(getattr(self.state, "gh", 0.0), 0.0)
        gh_seen = bool(getattr(self.state, "gh_seen", False))
        gh_flag = "✅" if gh_seen else "⏳"
        gh_line = f"• GH: <b>{gh:.2f}</b> {gh_flag}\n" if gh else ""
        tp1 = _safe_float(getattr(self.state, "tp1", 0.0), 0.0)
        price = _safe_float((mem.get("1m") or {}).get("price"), 0.0)

        tp1_hit = bool(getattr(self.state, "tp1_hit", False))
        tp1_flag = "✅" if tp1_hit else "⏳"

        return (
            f"🔁 <b>EMRE UPDATE</b>\n"
            f"• {self.symbol} | <b>{side}</b>\n"
            f"• price: <b>{price:.2f}</b> | entry: {entry:.2f}\n"
            f"• stop: <b>{stop:.2f}</b>\n"
            f"{gh_line}"
            f"• TP1: <b>{tp1:.2f}</b> {tp1_flag}\n"
            f"• struct: {getattr(self.state,'structure','')}  trap={getattr(self.state,'trap','')}  bias={getattr(self.state,'bias_4h','')}\n"
            f"• time: {_now_str()}\n"
        )

    def _fmt_exit(self, reason: str) -> str:
        return (
            f"🧯 <b>EMRE EXIT</b>\n"
            f"• reason: {reason}\n"
            f"• time: {_now_str()}\n"
        )

    def _fmt_no_trade(self, sig, mem: Dict[str, Any]) -> str:
        side = getattr(sig, "side", "NO-TRADE")
        price = _safe_float((mem.get("1m") or {}).get("price"), 0.0)
        return (
            f"🟨 <b>EMRE NO-TRADE</b>\n"
            f"• {self.symbol} | {side}\n"
            f"• price: {price:.2f}\n"
            f"• time: {_now_str()}\n"
        )

    def _fmt_status(self, mem: Dict[str, Any]) -> str:
        price = _safe_float((mem.get("1m") or {}).get("price"), 0.0)
        is_open = bool(getattr(self.state, "is_open", False))
        side = getattr(self.state, "side", "NA")
        return (
            f"🛰 <b>EMRE STATUS</b>\n"
            f"• {self.symbol}\n"
            f"• is_open: {is_open} side={side}\n"
            f"• price: {price:.2f}\n"
            f"• time: {_now_str()}\n"
        )

    # -----------------------------
    # Market + Trader step
    # -----------------------------
    def step(self) -> Tuple[Optional[Any], Dict[str, Any]]:
        mem: Dict[str, Any] = {}
        mkt = self._get_market()
        mkt.update_memory(mem)

        # Trader
        from emre_trader import decide
        sig = decide(mem)
        return sig, mem

    # -----------------------------
    # TP1 hit marker (price touches TP1)
    # -----------------------------
    def _maybe_mark_tp1(self, price: float):
        try:
            tp1 = _safe_float(getattr(self.state, "tp1", 0.0), 0.0)
            side = getattr(self.state, "side", "NA")
            if not tp1 or side not in ("LONG", "SHORT"):
                return

            if side == "LONG" and price >= tp1:
                if not getattr(self.state, "tp1_hit", False):
                    setattr(self.state, "tp1_hit", True)
                    self._save_state()
            if side == "SHORT" and price <= tp1:
                if not getattr(self.state, "tp1_hit", False):
                    setattr(self.state, "tp1_hit", True)
                    self._save_state()
        except Exception:
            pass

    # -----------------------------
    # Main loop
    # -----------------------------
    def run(self):
        # NOTE: We keep hard-coded cadences for stability:
        # - flat no-trade: 1h fixed
        # - open update: fixed interval (set below)
        # This prevents "restart once then silence" style surprises.

        FLAT_EVERY_SEC = 3600
        UPDATE_EVERY_SEC = 900  # 15dk update (pozisyon açıkken)
        GH_WINDOW_SEC = 900        # 15dk içinde GH görülmezse pozisyonu kapat (silent)
        GH_FACTOR = 0.35            # GH = entry ± GH_FACTOR * |entry-stop|

        while True:
            try:
                sig, mem = self.step()
                if sig is None:
                    time.sleep(self.loop_sleep)
                    continue

                now = time.time()
                price = _safe_float((mem.get("1m") or {}).get("price"), 0.0)

                side = getattr(sig, "side", "NO-TRADE") or "NO-TRADE"

                # 1) If position open: mark TP1 hit
                if getattr(self.state, "is_open", False) and price:
                    self._maybe_mark_tp1(price)

                # 2) If we HAVE an open position, UPDATE cadence is fixed, independent from momentum/signal.
                if getattr(self.state, "is_open", False):
                    cur_side = getattr(self.state, "side", "NA")

                    # GH check (once) + timeout close (silent)
                    try:
                        gh = _safe_float(getattr(self.state, "gh", 0.0), 0.0)
                        gh_seen = bool(getattr(self.state, "gh_seen", False))
                        opened_ts = _safe_float(getattr(self.state, "opened_ts", 0.0), 0.0)
                        if gh and (not gh_seen):
                            if (cur_side == "LONG" and price >= gh) or (cur_side == "SHORT" and price <= gh):
                                setattr(self.state, "gh_seen", True)
                                self._save_state()
                                self._send(
                                    f"🎯 <b>GH GORULDU</b>\n"
                                    f"• {self.symbol} | <b>{cur_side}</b>\n"
                                    f"• price: <b>{price:.2f}</b>  GH: <b>{gh:.2f}</b>\n"
                                    f"• time: {_now_str()}\n"
                                )
                                self._last_telegram_ts = now
                            elif opened_ts and (now - opened_ts) >= GH_WINDOW_SEC:
                                setattr(self.state, "is_open", False)
                                self._save_state()
                                time.sleep(self.loop_sleep)
                                continue
                    except Exception:
                        pass


                    # If signal shows a clear reverse (LONG<->SHORT), EXIT then allow OPEN below.
                    if side in ("LONG", "SHORT") and cur_side in ("LONG", "SHORT") and side != cur_side:
                        self._send(self._fmt_exit("Yön değişti (state)"))
                        self._last_telegram_ts = now

                        # close state
                        setattr(self.state, "is_open", False)
                        self._save_state()
                        # continue to OPEN handling below (same tick)

                    else:
                        last_upd = _safe_float(getattr(self.state, "last_update_ts", 0.0), 0.0)

                        if (now - last_upd) >= UPDATE_EVERY_SEC:
                            # Best-effort: refresh some state fields from latest signal when same side
                            try:
                                if side in ("LONG", "SHORT") and side == cur_side:
                                    new_stop = _safe_float(getattr(sig, "stop", 0.0), 0.0)
                                    if new_stop:
                                        setattr(self.state, "stop", float(new_stop))
                                # Keep context updated
                                setattr(self.state, "structure", getattr(sig, "structure", getattr(self.state, "structure", "NA")))
                                setattr(self.state, "trap", getattr(sig, "trap", getattr(self.state, "trap", "NA")))
                                setattr(self.state, "bias_4h", getattr(sig, "bias_4h", getattr(self.state, "bias_4h", "NA")))
                                # Update last price
                                if price:
                                    setattr(self.state, "last_price", float(price))
                                setattr(self.state, "last_update_ts", now)
                                # Update state key for dedupe/debug visibility
                                if side in ("LONG", "SHORT"):
                                    setattr(self.state, "last_state_key", self._state_key(sig))
                                self._save_state()
                            except Exception:
                                pass

                            # Send UPDATE (dedupe fingerprint)
                            try:
                                fp = self._fingerprint_update(
                                    cur_side,
                                    float(price or 0.0),
                                    _safe_float(getattr(self.state, "stop", 0.0), 0.0),
                                    _safe_float(getattr(self.state, "tp1", 0.0), 0.0),
                                    getattr(self.state, "last_state_key", "") or ""
                                )
                                last_fp = getattr(self.state, "last_sent_fp", "") or ""
                                if fp != last_fp:
                                    self._send(self._fmt_update(mem))
                                    self._last_telegram_ts = now
                                    setattr(self.state, "last_sent_fp", fp)
                                    self._save_state()
                            except Exception:
                                pass

                        time.sleep(self.loop_sleep)
                        continue

                # 3) If NO open position:
                # - Only attempt OPEN if signal is LONG/SHORT (momentum gates are inside trader)
                if side in ("LONG", "SHORT"):
                    key = self._state_key(sig)

                    # OPEN (dedupe)
                    entry = _safe_float(getattr(sig, "entry", price), price)
                    stop = _safe_float(getattr(sig, "stop", 0.0), 0.0)
                    tps = getattr(sig, "tps", []) or []
                    tp1 = _safe_float(tps[0], 0.0) if len(tps) >= 1 else 0.0
                    tp2 = _safe_float(tps[1], 0.0) if len(tps) >= 2 else 0.0
                    tp3 = _safe_float(tps[2], 0.0) if len(tps) >= 3 else 0.0
                    tp4 = _safe_float(tps[3], 0.0) if len(tps) >= 4 else 0.0

                    fp_open = self._fingerprint_open(side, entry, stop, tp1, tp2, tp3, tp4, key)
                    last_fp = getattr(self.state, "last_sent_fp", "") or ""
                    if fp_open != last_fp:
                        setattr(self.state, "is_open", True)
                        setattr(self.state, "side", side)
                        setattr(self.state, "entry", float(entry))
                        setattr(self.state, "stop", float(stop))
                        # GH (Geçici Hedef): entry ± GH_FACTOR * |entry-stop|
                        try:
                            d = abs(float(entry) - float(stop))
                            gh = 0.0
                            if d > 0 and side in ("LONG", "SHORT"):
                                gh = float(entry) + (GH_FACTOR * d) if side == "LONG" else float(entry) - (GH_FACTOR * d)
                            setattr(self.state, "gh", float(gh))
                            setattr(self.state, "gh_seen", False)
                        except Exception:
                            setattr(self.state, "gh", 0.0)
                            setattr(self.state, "gh_seen", False)
                        setattr(self.state, "tp1", float(tp1))
                        setattr(self.state, "tp2", float(tp2))
                        setattr(self.state, "tp3", float(tp3))
                        setattr(self.state, "tp4", float(tp4))

                        setattr(self.state, "structure", getattr(sig, "structure", "NA"))
                        setattr(self.state, "trap", getattr(sig, "trap", "NA"))
                        setattr(self.state, "bias_4h", getattr(sig, "bias_4h", "NA"))

                        setattr(self.state, "opened_ts", now)
                        setattr(self.state, "last_update_ts", now)
                        setattr(self.state, "tp1_hit", False)
                        setattr(self.state, "last_state_key", key)
                        try:
                            setattr(self.state, "last_sent_fp", fp_open)
                            if price:
                                setattr(self.state, "last_price", float(price))
                        except Exception:
                            pass

                        self._save_state()

                        self._send(self._fmt_open(sig, mem))
                        self._last_telegram_ts = now

                    time.sleep(self.loop_sleep)
                    continue

                # 4) NO-TRADE while flat: strictly 1 msg/hour
                if (now - self._last_no_trade_ts) >= FLAT_EVERY_SEC:
                    self._send(self._fmt_no_trade(sig, mem))
                    self._last_telegram_ts = now
                    self._last_no_trade_ts = now

                # 5) Optional STATUS cadence
                if self.status_interval_sec > 0:
                    if (now - self._last_status_ts) >= self.status_interval_sec:
                        self._send(self._fmt_status(mem))
                        self._last_telegram_ts = now
                        self._last_status_ts = now

            except Exception:
                # never crash service loop
                pass

            time.sleep(self.loop_sleep)


_core_singleton: Optional[EmreCore] = None


def run():
    global _core_singleton
    if _core_singleton is None:
        _core_singleton = EmreCore()
    _core_singleton.run()
