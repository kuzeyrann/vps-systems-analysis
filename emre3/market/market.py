#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import time

from emre_market import EmreMarket

def _pct_range(xs: List[float]) -> float:
    if not xs:
        return 0.0
    base = xs[0] if xs[0] else 0.0
    if base == 0.0:
        return 0.0
    return (max(xs) - min(xs)) / base

def _avg_abs_return(xs: List[float], n: int) -> float:
    if not xs or len(xs) < 2:
        return 0.0
    ys = xs[-(n+1):]
    if len(ys) < 2:
        return 0.0
    acc = 0.0
    cnt = 0
    for i in range(1, len(ys)):
        a = ys[i-1]
        b = ys[i]
        if a:
            acc += abs(b - a) / a
            cnt += 1
    return acc / cnt if cnt else 0.0

def _regime(range15: float, range60: float, vol_1m: float) -> str:
    # very simple regime classifier; tune later
    if range15 > 0.008 or vol_1m > 0.0015:
        return "VOL"
    if range60 > 0.015 and range15 > 0.004:
        return "TREND"
    return "RANGE"

@dataclass
class MarketSnapshot:
    raw: Dict[str, Any]
    mem: Dict[str, Any]

class MarketAdapter:
    def __init__(self, symbol: str = "BTCUSDT"):
        self._mkt = EmreMarket(symbol=symbol)

    def fetch(self) -> MarketSnapshot:
        raw = self._mkt.update_memory({})
        mem: Dict[str, Any] = {}
        if raw.get("error"):
            mem["error"] = raw.get("error")
            mem["ts"] = int(time.time())
            mem["price"] = 0.0
            mem["closes_1m"] = []
            mem["closes_15m"] = []
            mem["range15"] = 0.0
            mem["range60"] = 0.0
            mem["vol_1m"] = 0.0
            mem["regime"] = "RANGE"
            return MarketSnapshot(raw=raw, mem=mem)

        closes1 = list(raw.get("1m", {}).get("closes") or [])
        closes15 = list(raw.get("15m", {}).get("closes") or [])

        price = float(raw.get("1m", {}).get("price") or (closes1[-1] if closes1 else 0.0))

        mem["ts"] = int(time.time())
        mem["price"] = price
        mem["closes_1m"] = closes1
        mem["closes_15m"] = closes15

        # ranges
        mem["range15"] = _pct_range(closes1[-15:]) if len(closes1) >= 15 else _pct_range(closes1)
        mem["range60"] = float(raw.get("cum", {}).get("range60") or 0.0)

        # volatility (avg abs return over last N 1m bars)
        mem["vol_1m"] = _avg_abs_return(closes1, n=20)

        mem["regime"] = _regime(mem["range15"], mem["range60"], mem["vol_1m"])

        # keep a reference to legacy structure if needed
        mem["_legacy"] = raw

        return MarketSnapshot(raw=raw, mem=mem)
