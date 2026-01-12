#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict

from emre_trader import decide as legacy_decide

@dataclass(frozen=True)
class Signal:
    side: str              # LONG/SHORT/NO-TRADE
    entry: float
    reason: str
    ts: int
    meta: Dict[str, Any]

class SignalEngine:
    def decide(self, legacy_mem: Dict[str, Any], ts: int) -> Signal:
        sig = legacy_decide(legacy_mem)
        side = getattr(sig, "side", "NO-TRADE")
        entry = float(getattr(sig, "entry", 0.0) or 0.0)
        reason = getattr(sig, "reason", "") or ""
        meta = getattr(sig, "meta", {}) or {}
        return Signal(side=side, entry=entry, reason=reason, ts=ts, meta=meta)
