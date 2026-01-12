#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import time
from typing import Dict, Any
import requests


class EmreMarket:
    def __init__(self, symbol: str = "BTCUSDT", *args, **kwargs):
        self.symbol = kwargs.get("symbol", symbol)
        self._cache = {}
        self._cache_ts = {}
        self._ttl = {"1m": 10, "15m": 45}

    def _fetch(self, interval: str, limit: int):
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": self.symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def _cached(self, interval: str, limit: int):
        key = f"{interval}:{limit}"
        now = time.time()
        if key in self._cache and now - self._cache_ts.get(key, 0) < self._ttl.get(interval, 10):
            return self._cache[key]

        data = self._fetch(interval, limit)
        self._cache[key] = data
        self._cache_ts[key] = now
        return data

    @staticmethod
    def _f(x, d=0.0):
        try:
            return float(x)
        except Exception:
            return d

    # ✅ TEK VE NET İMZA
    def update_memory(self, mem: Dict[str, Any] | None = None):
        if mem is None:
            mem = {}
        else:
            mem.clear()

        try:
            k1 = self._cached("1m", 130)
            closes1 = [self._f(k[4]) for k in k1]

            k15 = self._cached("15m", 210)
            closes15 = [self._f(k[4]) for k in k15]
            highs15 = [self._f(k[2]) for k in k15]
            lows15 = [self._f(k[3]) for k in k15]

            price = closes1[-1] if closes1 else 0.0

            mem["1m"] = {"price": price, "closes": closes1}
            mem["15m"] = {"closes": closes15, "highs": highs15, "lows": lows15}

            def cum_move(xs):
                if len(xs) < 2 or xs[0] == 0:
                    return 0.0
                return (xs[-1] - xs[0]) / xs[0]

            def cum_range(xs):
                if not xs or xs[0] == 0:
                    return 0.0
                return (max(xs) - min(xs)) / xs[0]

            mem["cum"] = {
                "move60": cum_move(closes1[-60:]),
                "move120": cum_move(closes1[-120:]),
                "range60": cum_range(closes1[-60:]),
                "range120": cum_range(closes1[-120:]),
            }

            mem.pop("error", None)

        except Exception as e:
            mem.clear()
            mem["error"] = str(e)
            mem["1m"] = {"price": 0.0, "closes": []}
            mem["15m"] = {"closes": [], "highs": [], "lows": []}
            mem["cum"] = {"move60": 0.0, "move120": 0.0, "range60": 0.0, "range120": 0.0}

        return mem
