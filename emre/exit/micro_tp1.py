#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leg-local TP1 micro momentum confirmer.
Birebir emre_tp_micro.py mantığı; ama global değil, instance state kullanır.
Reverse (LONG+SHORT aynı anda) senaryosunda çakışmayı önler.
"""

from __future__ import annotations
from collections import deque
from typing import Any, Dict, Optional


class MicroTP1:
    def __init__(self, maxlen: int = 5):
        self._closes = deque(maxlen=maxlen)
        self._confirmed = False

    def reset(self) -> None:
        self._closes.clear()
        self._confirmed = False

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    def update(self, mem: Dict[str, Any], entry: float, side: str) -> Optional[float]:
        if mem is None or entry is None or side not in ("LONG", "SHORT"):
            return None

        closes = mem.get("closes_1m")
        if not closes or len(closes) < 2:
            return None

        last = float(closes[-1])
        prev = float(closes[-2])

        # directional micro momentum
        if side == "LONG":
            if last <= prev:
                self.reset()
                return None
        else:  # SHORT
            if last >= prev:
                self.reset()
                return None

        self._closes.append(last)
        if len(self._closes) < 2:
            return None

        total_move = abs(self._closes[-1] - self._closes[0])
        min_move = float(entry) * 0.00015  # 15bp
        if total_move < min_move:
            return None

        buffer_bp = float(entry) * 0.00005  # 5bp
        if side == "LONG":
            if last < float(entry) + buffer_bp:
                return None
        else:
            if last > float(entry) - buffer_bp:
                return None

        self._confirmed = True
        return last
