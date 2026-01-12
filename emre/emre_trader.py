#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry signal module.

Produces side (LONG/SHORT/NO-TRADE), entry price, and meta.

Dual-gate entry:
- EARLY: earlier momentum capture (old spirit), requires r4 alignment.
- LATE: stricter confirmation.

Stop/targets are calculated by the risk engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _closes(mem: Dict[str, Any], tf: str) -> List[float]:
    d = mem.get(tf, {}) or {}
    xs = d.get("closes", []) or []
    return [_safe_float(x, 0.0) for x in xs]


def _last_price(mem: Dict[str, Any]) -> float:
    m1 = mem.get("1m", {}) or {}
    if "price" in m1:
        return _safe_float(m1.get("price"), 0.0)
    closes1 = _closes(mem, "1m")
    return closes1[-1] if closes1 else 0.0


def _ret(xs: List[float], n: int) -> float:
    if len(xs) < n + 1:
        return 0.0
    a = xs[-1]
    b = xs[-1 - n]
    if not b:
        return 0.0
    return (a - b) / b


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


@dataclass
class Signal:
    side: str = "NO-TRADE"      # LONG/SHORT/NO-TRADE
    entry: float = 0.0
    structure: str = "RANGE"    # TREND/RANGE
    trap: str = "LOW"          # LOW/MED/HIGH
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _bias_from_15m(mem: Dict[str, Any]) -> Tuple[str, str, str, str, Dict[str, Any]]:
    closes15 = _closes(mem, "15m")
    price = _last_price(mem)

    # ~60m and ~120m returns
    r4 = _ret(closes15, 4)
    r8 = _ret(closes15, 8)

    s4 = _sign(r4)
    s8 = _sign(r8)

    # ---- thresholds ----
    # EARLY: old spirit
    EARLY_R8 = 0.003
    # LATE: confirmed
    LATE_STRUCT_R8 = 0.005
    LATE_BIAS_R8 = 0.004

    entry_mode = "NONE"  # NONE/EARLY/LATE
    bias = "NEUTRAL"
    structure = "RANGE"

    # LATE gate first (more confident)
    if abs(r8) >= LATE_STRUCT_R8 and s4 == s8 and s8 != 0:
        structure = "TREND"
        entry_mode = "LATE"
    else:
        structure = "RANGE"

    if r8 >= LATE_BIAS_R8:
        bias = "LONG"
        entry_mode = "LATE" if entry_mode != "NONE" else "LATE"
    elif r8 <= -LATE_BIAS_R8:
        bias = "SHORT"
        entry_mode = "LATE" if entry_mode != "NONE" else "LATE"

    # EARLY gate (if LATE didn't trigger)
    if bias == "NEUTRAL":
        if abs(r8) >= EARLY_R8 and s4 == s8 and s8 != 0:
            bias = "LONG" if s8 > 0 else "SHORT"
            entry_mode = "EARLY"
            # structure is still RANGE unless strong enough; keep it conservative

    # trap (simple heuristic)
    trap = "LOW"
    if structure == "RANGE" and abs(r4) > 0.002 and s4 != s8 and s8 != 0:
        trap = "MED"

    reason = f"bias15m r8={r8:.4f} r4={r4:.4f} price={price:.2f} mode={entry_mode}"
    meta = {
        "r4": r4,
        "r8": r8,
        "price": price,
        "bias": bias,
        "structure": structure,
        "trap": trap,
        "entry_mode": entry_mode,
        "gate": {"early_r8": EARLY_R8, "late_struct_r8": LATE_STRUCT_R8, "late_bias_r8": LATE_BIAS_R8},
    }
    return bias, structure, trap, reason, meta


def decide(mem: Dict[str, Any]) -> Signal:
    if mem.get("error"):
        return Signal(side="NO-TRADE", reason=f"market_error: {mem.get('error')}", meta={"error": mem.get('error')})

    price = _last_price(mem)
    bias, structure, trap, bias_reason, bmeta = _bias_from_15m(mem)

    if bias not in ("LONG", "SHORT"):
        return Signal(side="NO-TRADE", entry=float(price), structure=structure, trap=trap, reason=bias_reason, meta=bmeta)

    side = bias
    entry = float(price)
    reason = f"{side}/{structure} | {bias_reason}"

    return Signal(side=side, entry=entry, structure=structure, trap=trap, reason=reason, meta=bmeta)
