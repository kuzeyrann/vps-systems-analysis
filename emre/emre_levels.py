#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
emre_levels.py
- build_level_map(mem): 15m ve (varsa) 4h/1d verilerinden yapı seviyeleri çıkarır
- pick_tp234(level_map, side, entry, stop, tp1): TP2/TP3/TP4 seçer (öncelik sıralı)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _quantize(px: float, step: float = 1.0) -> float:
    if step <= 0:
        return px
    return round(px / step) * step


def _uniq_sorted(levels: List[float]) -> List[float]:
    out = []
    for v in sorted(set([float(x) for x in levels if x is not None])):
        if not out or abs(v - out[-1]) >= 0.5:  # çok yakınları birleştir
            out.append(v)
    return out


def _get_closes(mem: Dict[str, Any], tf: str) -> List[float]:
    d = mem.get(tf) or {}
    closes = d.get("closes") or []
    return [float(x) for x in closes if x is not None]


def _get_highs_lows(mem: Dict[str, Any], tf: str) -> Tuple[List[float], List[float]]:
    d = mem.get(tf) or {}
    highs = d.get("highs") or []
    lows = d.get("lows") or []
    return (
        [float(x) for x in highs if x is not None],
        [float(x) for x in lows if x is not None],
    )


def _last_price(mem: Dict[str, Any]) -> float:
    return _safe_float((mem.get("1m") or {}).get("price"), 0.0)


def _range_hi_lo(closes: List[float], lookback: int) -> Tuple[float, float]:
    if not closes:
        return 0.0, 0.0
    w = closes[-lookback:] if len(closes) >= lookback else closes
    return max(w), min(w)


def _swing_levels(highs: List[float], lows: List[float], lookback: int) -> Tuple[float, float]:
    if not highs or not lows:
        return 0.0, 0.0
    wh = highs[-lookback:] if len(highs) >= lookback else highs
    wl = lows[-lookback:] if len(lows) >= lookback else lows
    return max(wh), min(wl)


def build_level_map(mem: Dict[str, Any]) -> Dict[str, Any]:
    """
    Çıktı formatı:
    {
      "price": float,
      "range": {"hi": float, "lo": float, "mid": float},
      "swing": {"hi": float, "lo": float},
      "sr": {"levels": [..]},         # 15m tabanlı basit SR
      "htf": {"levels": [..]},        # 4h/1d basit seviyeler
      "all": [..]                     # birleşik seviye listesi
    }
    """
    price = _last_price(mem)

    closes15 = _get_closes(mem, "15m")
    highs15, lows15 = _get_highs_lows(mem, "15m")

    # Range: son 32 adet 15m mum ~ 8 saat
    r_hi, r_lo = _range_hi_lo(closes15, lookback=32)
    r_mid = (r_hi + r_lo) / 2.0 if (r_hi and r_lo) else 0.0

    # Swing: son 48 adet 15m mum ~ 12 saat
    s_hi, s_lo = _swing_levels(highs15, lows15, lookback=48)

    # SR: 15m kapanışlarından kaba “cluster” (bin)
    sr_levels: List[float] = []
    if closes15:
        # fiyatın %0.25’i kadar bin (BTC’de ~200-300$ gibi)
        bin_step = max(price * 0.0025, 50.0) if price > 0 else 100.0
        bins = {}
        for c in closes15[-96:]:  # ~24 saat
            q = _quantize(c, step=bin_step)
            bins[q] = bins.get(q, 0) + 1
        # en sık görülen ilk 8 seviye
        top = sorted(bins.items(), key=lambda kv: kv[1], reverse=True)[:8]
        sr_levels = [float(k) for k, _ in top]

    # HTF: 4h / 1d varsa (yoksa boş)
    htf_levels: List[float] = []
    for tf, lk in [("4h", 60), ("1d", 60)]:
        c = _get_closes(mem, tf)
        if c:
            hi, lo = _range_hi_lo(c, lookback=min(lk, len(c)))
            if hi and lo:
                htf_levels += [hi, lo, (hi + lo) / 2.0]

    # Birleştir
    all_levels = []
    if r_hi and r_lo:
        all_levels += [r_hi, r_lo, r_mid]
    if s_hi and s_lo:
        all_levels += [s_hi, s_lo]
    all_levels += sr_levels
    all_levels += htf_levels

    # fiyat etrafında çok uzakları törpüle (aşırı uçları at)
    if price > 0:
        all_levels = [lv for lv in all_levels if (0.85 * price) <= lv <= (1.15 * price)]

    all_levels = _uniq_sorted(all_levels)

    return {
        "price": price,
        "range": {"hi": r_hi, "lo": r_lo, "mid": r_mid},
        "swing": {"hi": s_hi, "lo": s_lo},
        "sr": {"levels": _uniq_sorted(sr_levels)},
        "htf": {"levels": _uniq_sorted(htf_levels)},
        "all": all_levels,
    }


def _levels_above(levels: List[float], px: float) -> List[float]:
    return [lv for lv in levels if lv > px]


def _levels_below(levels: List[float], px: float) -> List[float]:
    return [lv for lv in levels if lv < px]


def pick_tp234(
    level_map: Dict[str, Any],
    side: str,
    entry: float,
    stop: float,
    tp1: float,
) -> Tuple[float, float, float]:
    """
    Öncelik:
    - TP2: en yakın seviye (range/swing/sr/htf birleşik)
    - TP3: bir sonraki seviye
    - TP4: bir sonraki seviye; yoksa TP3’ün uzatması

    Not: TP2/3/4, TP1’in “ötesinde” seçilir (TP1 mikro hedef; TP2 yapı hedefi).
    """
    levels = (level_map.get("all") or [])[:]
    levels = [float(x) for x in levels if x is not None]

    side = (side or "").upper().strip()
    entry = float(entry)
    tp1 = float(tp1)

    # minimum mantıksal mesafe (çok yakın seviyeleri ele)
    min_gap = max(abs(entry - stop) * 0.15, abs(tp1 - entry) * 0.6, entry * 0.0008)

    if side == "LONG":
        candidates = _levels_above(levels, max(entry, tp1) + min_gap)
        candidates = sorted(candidates)
        if len(candidates) >= 3:
            tp2, tp3, tp4 = candidates[0], candidates[1], candidates[2]
        elif len(candidates) == 2:
            tp2, tp3 = candidates[0], candidates[1]
            tp4 = tp3 + max((tp3 - entry) * 0.5, (tp3 - tp2) * 1.0)
        elif len(candidates) == 1:
            tp2 = candidates[0]
            tp3 = tp2 + max((tp2 - entry) * 0.6, entry * 0.002)
            tp4 = tp3 + max((tp3 - entry) * 0.5, entry * 0.0025)
        else:
            # fallback extension
            r = max(abs(entry - stop), abs(tp1 - entry), entry * 0.002)
            tp2 = entry + 1.2 * r
            tp3 = entry + 1.8 * r
            tp4 = entry + 2.5 * r

    else:  # SHORT
        candidates = _levels_below(levels, min(entry, tp1) - min_gap)
        candidates = sorted(candidates, reverse=True)
        if len(candidates) >= 3:
            tp2, tp3, tp4 = candidates[0], candidates[1], candidates[2]
        elif len(candidates) == 2:
            tp2, tp3 = candidates[0], candidates[1]
            tp4 = tp3 - max((entry - tp3) * 0.5, (tp2 - tp3) * 1.0)
        elif len(candidates) == 1:
            tp2 = candidates[0]
            tp3 = tp2 - max((entry - tp2) * 0.6, entry * 0.002)
            tp4 = tp3 - max((entry - tp3) * 0.5, entry * 0.0025)
        else:
            r = max(abs(entry - stop), abs(tp1 - entry), entry * 0.002)
            tp2 = entry - 1.2 * r
            tp3 = entry - 1.8 * r
            tp4 = entry - 2.5 * r

    return float(tp2), float(tp3), float(tp4)

# === GH / TP helpers (FULL API) ===

def pick_gh(level_map, entry, side):
    """Return first structural liquidity level in trade direction."""
    levels = [float(x) for x in (level_map.get("all") or []) if x is not None]
    entry = float(entry)
    side = (side or "").upper()
    min_gap = entry * 0.0008

    if side == "LONG":
        cands = sorted(_levels_above(levels, entry + min_gap))
        return cands[0] if cands else entry + entry * 0.002
    else:
        cands = sorted(_levels_below(levels, entry - min_gap), reverse=True)
        return cands[0] if cands else entry - entry * 0.002


def pick_tp_after_gh(level_map, gh, side, n=3):
    """Return up to n structural levels after GH."""
    levels = [float(x) for x in (level_map.get("all") or []) if x is not None]
    gh = float(gh)
    side = (side or "").upper()
    min_gap = gh * 0.0005

    if side == "LONG":
        cands = sorted(_levels_above(levels, gh + min_gap))
    else:
        cands = sorted(_levels_below(levels, gh - min_gap), reverse=True)

    return cands[:n]


def pick_stop_from_gh(entry, gh, side):
    """Structural stop candidate based on entry-GH relation."""
    entry = float(entry)
    gh = float(gh)
    side = (side or "").upper()
    d = abs(gh - entry)

    if side == "LONG":
        return entry - max(d * 0.6, entry * 0.0015)
    else:
        return entry + max(d * 0.6, entry * 0.0015)


def pick_gh_tp234(
    level_map,
    side,
    entry,
    stop=None,
    tp1_hint=None,
):
    """Return GH, TP2, TP3, TP4 using structural hierarchy."""
    gh = pick_gh(level_map, entry, side)
    tps = pick_tp_after_gh(level_map, gh, side, n=3)

    # extend if not enough structure
    entry = float(entry)
    side = (side or "").upper()

    def _ext(px, k):
        r = max(abs(gh - entry), entry * 0.002)
        return px + k * r if side == "LONG" else px - k * r

    while len(tps) < 3:
        base = tps[-1] if tps else gh
        tps.append(_ext(base, 0.8))

    tp2, tp3, tp4 = tps[0], tps[1], tps[2]

    # monotonic safety
    if side == "LONG":
        tp2 = max(tp2, gh); tp3 = max(tp3, tp2); tp4 = max(tp4, tp3)
    else:
        tp2 = min(tp2, gh); tp3 = min(tp3, tp2); tp4 = min(tp4, tp3)

    return float(gh), float(tp2), float(tp3), float(tp4)
