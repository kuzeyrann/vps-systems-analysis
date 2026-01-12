#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reverse Authority Model v1 (senin kilitlediğin hali):
- LONG açıkken SHORT entry gelirse: SHORT aç (LONG açık kalır)
- SHORT TP1 gelirse: LONG tamamen kapat (PnL bakmadan)
Simetri: SHORT açıkken LONG entry -> LONG aç; LONG TP1 -> SHORT kapat

Bu modül "karar" üretir; core uygular.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .micro_tp1 import MicroTP1


@dataclass(frozen=True)
class ReverseDecision:
    open_side: Optional[str] = None          # "LONG"/"SHORT"
    close_side: Optional[str] = None         # "LONG"/"SHORT"
    tp1_price: Optional[float] = None
    meta: Dict[str, Any] = None


class ReverseEngine:
    def __init__(self):
        self.tp1_long = MicroTP1()
        self.tp1_short = MicroTP1()

    def on_new_leg_opened(self, side: str) -> None:
        # Yeni leg açıldığında karşılıklı state karışmasın diye sadece ilgili state'i resetle
        if side == "LONG":
            self.tp1_long.reset()
        elif side == "SHORT":
            self.tp1_short.reset()

    def on_counter_entry(self, existing_side: str, counter_side: str) -> ReverseDecision:
        # Long açıkken short entry gelirse short aç; short açıkken long entry gelirse long aç
        return ReverseDecision(open_side=counter_side, meta={"reason": "counter_entry", "existing": existing_side})

    def on_tick_tp1_check(self, mem: Dict[str, Any], side: str, entry: float) -> Optional[ReverseDecision]:
        # Her leg için kendi TP1 doğrulaması
        if side == "LONG":
            p = self.tp1_long.update(mem, entry=entry, side="LONG")
            if p is None:
                return None
            return ReverseDecision(meta={"reason": "tp1_confirm", "side": "LONG"}, tp1_price=float(p))
        if side == "SHORT":
            p = self.tp1_short.update(mem, entry=entry, side="SHORT")
            if p is None:
                return None
            return ReverseDecision(meta={"reason": "tp1_confirm", "side": "SHORT"}, tp1_price=float(p))
        return None
