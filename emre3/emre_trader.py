#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry signal module.

Produces side (LONG/SHORT/NO-TRADE), entry price, and meta.

Dual-gate entry:
- EARLY: earlier momentum capture (old spirit), requires r4 alignment.
- LATE: stricter confirmation.

Stop/targets are calculated by the risk engine.

=== YENİ ÖZELLİKLER (BB Sendromu Fix) ===
1. Bollinger Band width detection
2. Consolidation (daralma) tespiti
3. Dynamic thresholds based on market condition
4. Band sınırı uyarıları
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import math


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


# ===== YENİ: MARKET CONDITION DETECTORS =====
def _calculate_bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float, float]:
    """Bollinger Band hesapla: upper, middle, lower, width (%)"""
    if len(closes) < period:
        return 0.0, 0.0, 0.0, 1.0
    
    recent = closes[-period:]
    middle = sum(recent) / period
    
    # Standart sapma
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = math.sqrt(variance) if variance >= 0 else 0.0
    
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    # Band genişliği (%)
    bandwidth = (upper - lower) / middle if middle > 0 else 1.0
    
    return upper, middle, lower, bandwidth


def _is_near_band(price: float, upper: float, lower: float, threshold_pct: float = 0.0015) -> Tuple[bool, str]:
    """Fiyat Bollinger band sınırlarına yakın mı?"""
    if price <= 0 or upper <= 0 or lower <= 0:
        return False, ""
    
    dist_to_upper = abs(upper - price) / price
    dist_to_lower = abs(lower - price) / price
    
    if dist_to_upper < threshold_pct:
        return True, "UPPER"
    elif dist_to_lower < threshold_pct:
        return True, "LOWER"
    
    return False, ""


def _market_condition_score(closes: List[float]) -> Dict[str, Any]:
    """Piyasa durumu skorlaması: consolidation, trend, volatility"""
    if len(closes) < 40:
        return {"consolidation": False, "bb_width": 1.0, "score": 0.0}
    
    # Bollinger Band width
    _, _, _, bb_width = _calculate_bollinger_bands(closes, period=20)
    
    # Price range (son 30 bar)
    recent = closes[-30:] if len(closes) >= 30 else closes
    price_range = (max(recent) - min(recent)) / (sum(recent) / len(recent))
    
    # Volatility (son 20 barın avg movement)
    volatilities = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0:
            volatilities.append(abs(closes[i] - closes[i-1]) / closes[i-1])
    
    recent_vol = sum(volatilities[-20:]) / 20 if len(volatilities) >= 20 else 0.001
    
    # Consolidation score (0-1)
    consolidation_score = 0.0
    
    # BB width dar mı? (BTC için %2'den dar ise)
    if bb_width < 0.02:
        consolidation_score += 0.4
    
    # Price range dar mı? (%1.5'ten az)
    if price_range < 0.015:
        consolidation_score += 0.3
    
    # Volatility düşük mü?
    if recent_vol < 0.0008:  # %0.08'den az
        consolidation_score += 0.3
    
    is_consolidating = consolidation_score >= 0.6
    
    return {
        "consolidation": is_consolidating,
        "bb_width": bb_width,
        "price_range": price_range,
        "volatility": recent_vol,
        "score": consolidation_score
    }


# ===== ANA SİNYAL FONKSİYONU (GÜNCELLENDİ) =====
def _bias_from_15m(mem: Dict[str, Any]) -> Tuple[str, str, str, str, Dict[str, Any]]:
    closes15 = _closes(mem, "15m")
    price = _last_price(mem)
    
    # 1. ÖNCE PİYASA DURUMUNU TESPİT ET
    condition = _market_condition_score(closes15)
    is_consolidating = condition["consolidation"]
    bb_width = condition["bb_width"]
    
    # 2. BOLLINGER BAND SINIR KONTROLÜ
    bb_upper, bb_middle, bb_lower, _ = _calculate_bollinger_bands(closes15)
    near_band, band_side = _is_near_band(price, bb_upper, bb_lower)
    
    # ~60m and ~120m returns
    r4 = _ret(closes15, 4)
    r8 = _ret(closes15, 8)
    
    s4 = _sign(r4)
    s8 = _sign(r8)
    
    # ---- DYNAMIC THRESHOLDS ----
    # Konsolidasyonda: daha katı, Trend'de: normal
    if is_consolidating:
        BASE_EARLY = 0.003
        BASE_BIAS = 0.004
        BASE_STRUCT = 0.005
        
        # Daralma şiddetine göre multiplier
        consolidation_multiplier = 1.5 + (0.02 - min(bb_width, 0.02)) * 50  # 1.5-2.5 arası
        
        EARLY_R8 = BASE_EARLY * consolidation_multiplier
        LATE_BIAS_R8 = BASE_BIAS * consolidation_multiplier
        LATE_STRUCT_R8 = BASE_STRUCT * consolidation_multiplier
        
        threshold_mode = "CONSOLIDATION"
    else:
        EARLY_R8 = 0.003
        LATE_BIAS_R8 = 0.004
        LATE_STRUCT_R8 = 0.005
        threshold_mode = "NORMAL"
    
    # Band sınırındaysa EXTRA katılık
    if near_band:
        if band_side == "UPPER":
            # Üst band + LONG sinyali = EXTRA riskli
            LATE_BIAS_R8 = max(LATE_BIAS_R8, 0.008)  # En az %0.8
        elif band_side == "LOWER":
            # Alt band + SHORT sinyali = EXTRA riskli
            LATE_BIAS_R8 = max(LATE_BIAS_R8, 0.008)
    
    entry_mode = "NONE"
    bias = "NEUTRAL"
    structure = "RANGE"
    
    # LATE gate (confirmed)
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
    
    # TRAP hesaplaması (konsolidasyonda daha yüksek trap)
    trap = "LOW"
    if structure == "RANGE":
        if abs(r4) > 0.002 and s4 != s8 and s8 != 0:
            trap = "MED"
    
    # Konsolidasyonda ve band sınırındaysa HIGH trap
    if is_consolidating and near_band:
        trap = "HIGH"
    elif is_consolidating:
        trap = "MED"
    
    # REASON string'ini zenginleştir
    reason_parts = [
        f"bias15m r8={r8:.4f} r4={r4:.4f}",
        f"price={price:.2f}",
        f"mode={entry_mode}",
        f"cond={threshold_mode}"
    ]
    
    if is_consolidating:
        reason_parts.append(f"consolidation(score={condition['score']:.2f}, bbw={bb_width:.4f})")
    if near_band:
        reason_parts.append(f"near_{band_side}_band")
    
    reason = " | ".join(reason_parts)
    
    meta = {
        "r4": r4,
        "r8": r8,
        "price": price,
        "bias": bias,
        "structure": structure,
        "trap": trap,
        "entry_mode": entry_mode,
        "gate": {
            "early_r8": EARLY_R8,
            "late_bias_r8": LATE_BIAS_R8,
            "late_struct_r8": LATE_STRUCT_R8,
            "threshold_mode": threshold_mode
        },
        "market_condition": condition,
        "bollinger": {
            "upper": bb_upper,
            "middle": bb_middle,
            "lower": bb_lower,
            "width": bb_width,
            "near_band": near_band,
            "band_side": band_side
        }
    }
    
    return bias, structure, trap, reason, meta


def decide(mem: Dict[str, Any]) -> Signal:
    if mem.get("error"):
        return Signal(side="NO-TRADE", reason=f"market_error: {mem.get('error')}", meta={"error": mem.get('error')})
    
    price = _last_price(mem)
    bias, structure, trap, bias_reason, bmeta = _bias_from_15m(mem)
    
    # KRİTİK FİLTRE: Band sınırı + zayıf sinyal = NO TRADE
    near_band = bmeta.get("bollinger", {}).get("near_band", False)
    band_side = bmeta.get("bollinger", {}).get("band_side", "")
    is_consolidating = bmeta.get("market_condition", {}).get("consolidation", False)
    r8 = bmeta.get("r8", 0)
    
    if near_band and is_consolidating:
        # Band sınırı + konsolidasyon = çok riskli
        if (band_side == "UPPER" and bias == "LONG" and r8 < 0.008) or \
           (band_side == "LOWER" and bias == "SHORT" and r8 > -0.008):
            return Signal(
                side="NO-TRADE",
                entry=float(price),
                structure=structure,
                trap="HIGH",
                reason=f"BAND_FILTER: {bias_reason}",
                meta={**bmeta, "filtered": True}
            )
    
    if bias not in ("LONG", "SHORT"):
        return Signal(
            side="NO-TRADE",
            entry=float(price),
            structure=structure,
            trap=trap,
            reason=bias_reason,
            meta=bmeta
        )
    
    side = bias
    entry = float(price)
    reason = f"{side}/{structure} | {bias_reason}"
    
    return Signal(
        side=side,
        entry=entry,
        structure=structure,
        trap=trap,
        reason=reason,
        meta=bmeta
    )
