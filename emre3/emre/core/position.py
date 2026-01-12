from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Leg:
    is_open: bool = False
    side: str = "NA"  # LONG/SHORT
    entry: float = 0.0
    stop: float = 0.0
    opened_ts: int = 0
    risk_set_id: str = ""
    last_risk_update_ts: int = 0
    tp_hits: Dict[str, bool] = field(default_factory=lambda: {"TP1": False, "TP2": False, "TP3": False, "TP4": False})
    # stop is informational only in v1.2 (no forced exit)
    stop_touched: bool = False
    stop_touch_ts: int = 0
    stop_touch_price: float = 0.0

    def reset(self) -> None:
        self.is_open = False
        self.side = "NA"
        self.entry = 0.0
        self.stop = 0.0
        self.opened_ts = 0
        self.risk_set_id = ""
        self.last_risk_update_ts = 0
        self.tp_hits = {"TP1": False, "TP2": False, "TP3": False, "TP4": False}
        self.stop_touched = False
        self.stop_touch_ts = 0
        self.stop_touch_price = 0.0


@dataclass
class Position:
    long: Leg = field(default_factory=Leg)
    short: Leg = field(default_factory=Leg)

    @property
    def has_long(self) -> bool:
        return self.long.is_open and self.long.side == "LONG"

    @property
    def has_short(self) -> bool:
        return self.short.is_open and self.short.side == "SHORT"

    @property
    def any_open(self) -> bool:
        return self.has_long or self.has_short

    def get_leg(self, side: str) -> Optional[Leg]:
        if side == "LONG":
            return self.long
        if side == "SHORT":
            return self.short
        return None

    def open_leg(self, side: str, entry: float, ts: int) -> Leg:
        leg = self.get_leg(side)
        if leg is None:
            raise ValueError(f"Unknown side: {side}")
        if leg.is_open:
            return leg
        leg.is_open = True
        leg.side = side
        leg.entry = float(entry)
        leg.opened_ts = int(ts)
        leg.tp_hits = {"TP1": False, "TP2": False, "TP3": False, "TP4": False}
        return leg

    def close_leg(self, side: str) -> None:
        leg = self.get_leg(side)
        if leg is None:
            return
        leg.reset()