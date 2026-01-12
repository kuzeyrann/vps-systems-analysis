#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from emre_tp_micro import compute_tp1, reset_tp1

@dataclass(frozen=True)
class TP1Event:
    ts: int
    price: float
    meta: Dict[str, Any]

class TP1Module:
    def __init__(self):
        # ensure clean slate on boot
        reset_tp1()

    def update(self, mem: Dict[str, Any], position_side: str, entry: float, ts: int) -> Optional[TP1Event]:
        # compute_tp1 expects closes_1m list inside mem
        p = compute_tp1(mem, entry, position_side)
        if p is None:
            return None
        return TP1Event(ts=ts, price=float(p), meta={"source": "tp1_micro"})
