#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import time
import hashlib

from .models import RiskSet
from .config import RiskConfig


def _id_from(ts: int, side: str, entry: float) -> str:
    h = hashlib.sha1(f"{ts}:{side}:{entry}".encode("utf-8")).hexdigest()[:10]
    return f"risk_{h}"


def _safe_float(x: Any, d: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return d


def _structure_extreme(closes_1m: List[float], side: str, lookback: int) -> float:
    if not closes_1m:
        return 0.0
    xs = closes_1m[-lookback:] if len(closes_1m) >= lookback else closes_1m
    if side == "LONG":
        return float(min(xs))
    return float(max(xs))


def _impulse_len(closes_1m: List[float], lookback: int) -> float:
    if not closes_1m:
        return 0.0
    xs = closes_1m[-lookback:] if len(closes_1m) >= lookback else closes_1m
    hi = max(xs)
    lo = min(xs)
    return float(hi - lo)


def _trend_anchor(closes_1m: List[float], side: str, lookback: int = 60) -> float:
    if not closes_1m:
        return 0.0
    xs = closes_1m[-lookback:] if len(closes_1m) >= lookback else closes_1m
    if side == "LONG":
        return float(max(xs))  # last reference high
    return float(min(xs))      # last reference low


class RiskEngine:
    def __init__(self, cfg: RiskConfig | None = None):
        self.cfg = cfg or RiskConfig()

    def open(self, mem: Dict[str, Any], side: str, entry: float, ts: int) -> RiskSet:
        stop = self._calc_stop_phase0(mem, side, entry)
        tp2, tp3, tp4 = self._calc_tps(mem, side, entry, stop, current=None)
        return RiskSet(
            id=_id_from(ts, side, entry),
            created_ts=ts,
            stop=stop,
            tp2=tp2,
            tp3=tp3,
            tp4=tp4,
            meta=self._meta(mem, side, entry, stop, phase=0)
        )

    def update(
        self,
        mem: Dict[str, Any],
        side: str,
        entry: float,
        current: RiskSet,
        ts: int,
        phase: int,
    ) -> Optional[RiskSet]:
        # always generate a proposal; core decides apply/ignore
        if phase <= 0:
            stop = self._calc_stop_phase0(mem, side, entry)
        else:
            stop = self._calc_stop_phase1plus(mem, side, entry, current.stop)

        tp2, tp3, tp4 = self._calc_tps(mem, side, entry, stop, current=current)

        return RiskSet(
            id=_id_from(ts, side, entry),
            created_ts=ts,
            stop=stop,
            tp2=tp2,
            tp3=tp3,
            tp4=tp4,
            meta=self._meta(mem, side, entry, stop, phase=phase)
        )

    # ---------------- STOP ----------------

    def _calc_stop_phase0(self, mem: Dict[str, Any], side: str, entry: float) -> float:
        closes = list(mem.get("closes_1m") or [])
        vol_1m = _safe_float(mem.get("vol_1m"), 0.0)
        range15 = _safe_float(mem.get("range15"), 0.0)
        range60 = _safe_float(mem.get("range60"), 0.0)

        # --- base distances ---
        dist_vol = entry * self.cfg.K_VOL_STOP * vol_1m
        dist_min = entry * self.cfg.MIN_STOP_BP

        # Range tabanı: choppy piyasalarda stop'u "katil" olmaktan çıkarır.
        dist_range = entry * max(range15, range60) * 0.5

        dist = max(dist_vol, dist_min, dist_range)
        stop_vol = (entry - dist) if side == "LONG" else (entry + dist)

        # Structure extreme tabanı (genişletici): son yapı ekstremine pay bırak
        extreme = _structure_extreme(closes, side=side, lookback=self.cfg.STRUCT_LOOKBACK_1M)
        pad = entry * self.cfg.STRUCT_BUFFER_BP
        if extreme == 0.0:
            stop_struct = stop_vol
        else:
            stop_struct = (extreme - pad) if side == "LONG" else (extreme + pad)

        # EARLY girişte stop'u daha "sigorta" yap (geniş)
        entry_mode = (mem.get("entry_mode") or "").upper()
        if entry_mode == "EARLY":
            if side == "LONG":
                stop_vol = entry - dist * 1.4
            else:
                stop_vol = entry + dist * 1.4

        # Daha geniş (daha fazla alan) stop seç
        if side == "LONG":
            stop = min(stop_struct, stop_vol)
        else:
            stop = max(stop_struct, stop_vol)

        return float(stop)

    def _calc_stop_phase1plus(self, mem: Dict[str, Any], side: str, entry: float, current_stop: float) -> float:
        closes = list(mem.get("closes_1m") or [])
        if not closes:
            return float(current_stop)

        # impulse-base: use recent structure extreme as base (tightens only by core "never worse")
        extreme = _structure_extreme(closes, side=side, lookback=self.cfg.IMPULSE_LOOKBACK_1M)
        pad = entry * self.cfg.STRUCT_BUFFER_BP

        proposed = (extreme - pad) if side == "LONG" else (extreme + pad)
        return float(proposed)

    # ---------------- TPS ----------------

    def _calc_tps(
        self,
        mem: Dict[str, Any],
        side: str,
        entry: float,
        stop: float,
        current: Optional[RiskSet],
    ) -> Tuple[float, float, float]:
        closes = list(mem.get("closes_1m") or [])
        regime = (mem.get("regime") or "RANGE").upper()
        vol_1m = _safe_float(mem.get("vol_1m"), 0.0)

        # TP2: impulse length (executable)
        imp = _impulse_len(closes, lookback=self.cfg.IMPULSE_LOOKBACK_1M)
        if imp <= 0:
            # fallback: use R distance
            imp = abs(entry - stop)

        mult = self.cfg.TP2_IMPULSE_MULT_HIGHVOL if vol_1m > self.cfg.HIGHVOL_THRESHOLD else self.cfg.TP2_IMPULSE_MULT
        if side == "LONG":
            tp2 = float(entry + imp * mult)
        else:
            tp2 = float(entry - imp * mult)

        # TP3/TP4: trend projection in TREND, else R-multiple fallback
        if regime == "TREND":
            anchor = _trend_anchor(closes, side=side, lookback=60)
            if anchor == 0.0:
                anchor = entry

            if side == "LONG":
                tp3 = float(anchor + imp * self.cfg.TP3_TREND_MULT)
                tp4 = float(anchor + imp * self.cfg.TP4_TREND_MULT)
            else:
                tp3 = float(anchor - imp * self.cfg.TP3_TREND_MULT)
                tp4 = float(anchor - imp * self.cfg.TP4_TREND_MULT)

            # TREND’de TP3/TP4 aşağı “hızlı” revize olmasın:
            # current varsa ve yeni değer "trend yönüne aykırı" ise core drift guard ile de tutacağız
            return tp2, tp3, tp4

        # RANGE: classic R-multiple
        r = abs(entry - stop)
        r = max(r, entry * self.cfg.MIN_STOP_BP)
        if side == "LONG":
            tp3 = float(entry + self.cfg.M3 * r)
            tp4 = float(entry + self.cfg.M4 * r)
        else:
            tp3 = float(entry - self.cfg.M3 * r)
            tp4 = float(entry - self.cfg.M4 * r)

        return tp2, tp3, tp4

    def _meta(self, mem: Dict[str, Any], side: str, entry: float, stop: float, phase: int) -> Dict[str, Any]:
        return {
            "method": "B+C+PHASE",
            "phase": phase,
            "side": side,
            "entry": entry,
            "stop": stop,
            "regime": mem.get("regime"),
            "range15": mem.get("range15"),
            "range60": mem.get("range60"),
            "vol_1m": mem.get("vol_1m"),
            "k_vol_stop": self.cfg.K_VOL_STOP,
            "struct_lookback_1m": self.cfg.STRUCT_LOOKBACK_1M,
            "impulse_lookback_1m": self.cfg.IMPULSE_LOOKBACK_1M,
        }
