#!/usr/bin/env python3
"""EMRE-2: Regime-aware trading bot (paper execution by default).

- 15m regime + bias
- 1m triggers
- Opens/closes simulated positions (logs + Telegram)
- No exchange orders unless REAL_TRADING=1 (NOT implemented in this build)

Requires: python3, requests, python3-dotenv (dotenv optional if using .env)
"""

from __future__ import annotations

import os
import sys
import time
import json
import math
import signal
import traceback
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Tuple

import requests

LOG_PATH = os.getenv("EMRE2_LOG_PATH", "/var/log/emre2.log")
STATE_PATH = os.getenv("EMRE2_STATE_PATH", "/opt/emre2/state.json")

SYMBOL = os.getenv("EMRE2_SYMBOL", "BTCUSDT")
BASE_URL = os.getenv("EMRE2_BINANCE_BASE", "https://fapi.binance.com")

LOOP_SEC = int(os.getenv("EMRE2_LOOP_SEC", "10"))
KL_INTERVAL_BIAS = os.getenv("EMRE2_BIAS_INTERVAL", "15m")
KL_INTERVAL_ENTRY = os.getenv("EMRE2_ENTRY_INTERVAL", "1m")
BIAS_BARS = int(os.getenv("EMRE2_BIAS_BARS", "200"))
ENTRY_BARS = int(os.getenv("EMRE2_ENTRY_BARS", "240"))

# Indicators parameters
BB_N = int(os.getenv("EMRE2_BB_N", "20"))
BB_K = float(os.getenv("EMRE2_BB_K", "2.0"))
ATR_N = int(os.getenv("EMRE2_ATR_N", "14"))
EMA_N = int(os.getenv("EMRE2_EMA_N", "50"))
ADX_N = int(os.getenv("EMRE2_ADX_N", "14"))
VWAP_N = int(os.getenv("EMRE2_VWAP_N", "60"))  # on entry timeframe

# Regime thresholds (tunable)
BBW_SQUEEZE_PCT = float(os.getenv("EMRE2_BBW_SQUEEZE_PCT", "0.20"))  # bottom 20% of recent BBW
ADX_TREND_TH = float(os.getenv("EMRE2_ADX_TREND_TH", "22.0"))
WICK_RATIO_TRAP_TH = float(os.getenv("EMRE2_WICK_TRAP_TH", "2.2"))

# Entry zones
PB_UPPER = float(os.getenv("EMRE2_PB_UPPER", "0.90"))
PB_LOWER = float(os.getenv("EMRE2_PB_LOWER", "0.10"))

# Execution / risk
RISK_ATR_K = float(os.getenv("EMRE2_RISK_ATR_K", "1.5"))
TP1_ATR_K = float(os.getenv("EMRE2_TP1_ATR_K", "0.8"))
TP2_ATR_K = float(os.getenv("EMRE2_TP2_ATR_K", "2.0"))
REVERSE_EXIT = os.getenv("EMRE2_REVERSE_EXIT", "1") == "1"
ALLOW_TRADE = os.getenv("EMRE2_TRADE", "1") == "1"
COOLDOWN_SEC = int(os.getenv("EMRE2_COOLDOWN_SEC", "120"))

# Telegram
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

RUN = True

def _now() -> int:
    return int(time.time())

def log(line: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    out = f"[{ts}] {line}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(out + "\n")
    except Exception:
        print(out, file=sys.stderr)
    print(out)

def tg_send(msg: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        log("[TG] missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TG_CHAT, "text": msg}, timeout=10)
        if r.status_code != 200:
            log(f"[TG] send failed status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        log(f"[TG] send exception: {e}")

def binance_klines(symbol: str, interval: str, limit: int) -> List[List[Any]]:
    url = f"{BASE_URL}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json()

def parse_ohlcv(kl: List[List[Any]]) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    o = [float(x[1]) for x in kl]
    h = [float(x[2]) for x in kl]
    l = [float(x[3]) for x in kl]
    c = [float(x[4]) for x in kl]
    v = [float(x[5]) for x in kl]
    return o, h, l, c, v

def sma(xs: List[float], n: int) -> Optional[float]:
    if len(xs) < n: return None
    return sum(xs[-n:]) / n

def std(xs: List[float], n: int) -> Optional[float]:
    if len(xs) < n: return None
    m = sma(xs, n)
    if m is None: return None
    var = sum((x - m) ** 2 for x in xs[-n:]) / n
    return math.sqrt(var)

def ema(xs: List[float], n: int) -> Optional[float]:
    if len(xs) < n: return None
    k = 2.0 / (n + 1.0)
    e = xs[-n]
    for x in xs[-n+1:]:
        e = x * k + e * (1 - k)
    return e

def atr(high: List[float], low: List[float], close: List[float], n: int) -> Optional[float]:
    if len(close) < n + 1: return None
    trs = []
    for i in range(-n, 0):
        h = high[i]; lo = low[i]; pc = close[i-1]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        trs.append(tr)
    return sum(trs) / n

def bbands(close: List[float], n: int, k: float) -> Optional[Tuple[float, float, float, float]]:
    m = sma(close, n)
    s = std(close, n)
    if m is None or s is None: return None
    up = m + k * s
    dn = m - k * s
    bbw = (up - dn) / m if m != 0 else 0.0
    return dn, m, up, bbw

def percent_b(price: float, dn: float, up: float) -> float:
    if up == dn: return 0.5
    return (price - dn) / (up - dn)

def vwap(close: List[float], vol: List[float], n: int) -> Optional[float]:
    if len(close) < n: return None
    cv = close[-n:]; vv = vol[-n:]
    s_v = sum(vv)
    if s_v == 0: return None
    return sum(c * v for c, v in zip(cv, vv)) / s_v

def wick_ratio(open_: List[float], high: List[float], low: List[float], close: List[float], lookback: int=50) -> Optional[float]:
    if len(close) < lookback: return None
    ratios = []
    for i in range(-lookback, 0):
        o = open_[i]; h = high[i]; l = low[i]; c = close[i]
        body = abs(c - o)
        wick = (h - max(o, c)) + (min(o, c) - l)
        ratios.append((wick / body) if body > 1e-9 else 10.0)
    return sum(ratios) / len(ratios)

def adx(high: List[float], low: List[float], close: List[float], n: int) -> Optional[float]:
    if len(close) < n + 2: return None
    plus_dm = []; minus_dm = []; tr_list = []
    for i in range(-n-1, 0):
        up_move = high[i] - high[i-1]
        down_move = low[i-1] - low[i]
        pdm = up_move if up_move > down_move and up_move > 0 else 0.0
        mdm = down_move if down_move > up_move and down_move > 0 else 0.0
        plus_dm.append(pdm); minus_dm.append(mdm)
        tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        tr_list.append(tr)
    atr_n = sum(tr_list) / n
    if atr_n <= 1e-9: return 0.0
    pdi = 100.0 * (sum(plus_dm[-n:]) / n) / atr_n
    mdi = 100.0 * (sum(minus_dm[-n:]) / n) / atr_n
    dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 1e-9 else 0.0
    return dx  # simplified

@dataclass
class Position:
    side: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    opened_ts: int
    last_action_ts: int
    regime: str
    bias: str
    confidence: float
    meta: Dict[str, Any]

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"pos": None, "cooldown_until": 0}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pos": None, "cooldown_until": 0}

def save_state(st: Dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)

def classify_regime(close15: List[float], open15: List[float], high15: List[float], low15: List[float]) -> Tuple[str, float, float, float]:
    bb = bbands(close15, BB_N, BB_K)
    ad = adx(high15, low15, close15, ADX_N)
    wr = wick_ratio(open15, high15, low15, close15, lookback=min(50, len(close15)))
    if bb is None or ad is None or wr is None:
        return "UNKNOWN", 0.0, 0.0, 0.0
    dn, mid, up, bbw = bb
    bbw_hist = []
    for i in range(max(0, len(close15)-120), len(close15)):
        bbi = bbands(close15[:i+1], BB_N, BB_K)
        if bbi: bbw_hist.append(bbi[3])
    squeeze = 0.0
    if len(bbw_hist) >= 30:
        sorted_b = sorted(bbw_hist)
        idx = int(BBW_SQUEEZE_PCT * (len(sorted_b)-1))
        th = sorted_b[idx]
        squeeze = 1.0 if bbw <= th else 0.0
    if squeeze >= 1.0 and ad < ADX_TREND_TH:
        regime = "SQUEEZE"
    else:
        regime = "TREND" if ad >= ADX_TREND_TH else "RANGE"
    return regime, bbw, ad, wr

def compute_bias_confidence(close15: List[float], vol1: List[float], close1: List[float]) -> Tuple[str, float, Dict[str, Any]]:
    e = ema(close15, EMA_N)
    if e is None:
        return "NEUTRAL", 0.0, {}
    price = close15[-1]
    slope = (close15[-1] - close15[-8]) / close15[-8] if len(close15) >= 9 else 0.0
    b = "LONG" if price > e and slope > 0 else "SHORT" if price < e and slope < 0 else "NEUTRAL"
    vw = vwap(close1, vol1, VWAP_N)
    vwap_bias = "NEUTRAL"; vwap_dev = 0.0
    if vw:
        vwap_dev = (close1[-1] - vw) / vw
        if vwap_dev > 0.0006: vwap_bias = "LONG"
        elif vwap_dev < -0.0006: vwap_bias = "SHORT"
    look = min(30, len(close1)-1)
    net = close1[-1] - close1[-1-look]
    total = sum(abs(close1[i] - close1[i-1]) for i in range(-look, 0))
    eff = abs(net) / total if total > 1e-9 else 0.0
    score = 0.0
    score += 0.6 * (1.0 if b == "LONG" else -1.0 if b == "SHORT" else 0.0)
    score += 0.3 * (1.0 if vwap_bias == "LONG" else -1.0 if vwap_bias == "SHORT" else 0.0)
    score += 0.1 * (1.0 if net > 0 else -1.0 if net < 0 else 0.0) * min(1.0, eff*2)
    if score > 0.25: bias = "LONG"
    elif score < -0.25: bias = "SHORT"
    else: bias = "NEUTRAL"
    conf = min(1.0, abs(score) + 0.2*eff)
    return bias, conf, {"ema": e, "slope": slope, "vwap": vw, "vwap_dev": vwap_dev, "eff": eff, "score": score}

def range_trigger(price1: float, close1: List[float]) -> Tuple[Optional[str], Dict[str, Any]]:
    bb = bbands(close1, BB_N, BB_K)
    if bb is None: return None, {}
    dn, mid, up, bbw = bb
    pb = percent_b(price1, dn, up)
    last = close1[-1]; prev = close1[-2] if len(close1) >= 2 else last
    rej_up = (prev > up and last < up) or (pb > PB_UPPER and last < prev)
    rej_dn = (prev < dn and last > dn) or (pb < PB_LOWER and last > prev)
    if pb >= PB_UPPER and rej_up:
        return "SHORT", {"pb": pb, "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "reason": "range_reject_upper"}
    if pb <= PB_LOWER and rej_dn:
        return "LONG", {"pb": pb, "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "reason": "range_reject_lower"}
    return None, {"pb": pb, "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "reason": "no_trigger"}

def expansion_trigger(price1: float, close1: List[float]) -> Tuple[Optional[str], Dict[str, Any]]:
    bb = bbands(close1, BB_N, BB_K)
    if bb is None: return None, {}
    dn, mid, up, bbw = bb
    last = close1[-1]; prev = close1[-2] if len(close1) >= 2 else last
    if prev > up and last >= up:
        return "LONG", {"reason": "breakout_upper_hold", "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "pb": percent_b(price1, dn, up)}
    if prev < dn and last <= dn:
        return "SHORT", {"reason": "breakout_lower_hold", "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "pb": percent_b(price1, dn, up)}
    return None, {"reason": "no_trigger", "dn": dn, "mid": mid, "up": up, "bbw_entry": bbw, "pb": percent_b(price1, dn, up)}

def compute_levels(side: str, price: float, atr15: float) -> Tuple[float, float, float]:
    base = atr15 if atr15 > 0 else max(10.0, price * 0.0008)
    if side == "LONG":
        stop = price - base * RISK_ATR_K
        tp1 = price + base * TP1_ATR_K
        tp2 = price + base * TP2_ATR_K
    else:
        stop = price + base * RISK_ATR_K
        tp1 = price - base * TP1_ATR_K
        tp2 = price - base * TP2_ATR_K
    return stop, tp1, tp2

def maybe_reverse(pos: Position, new_side: Optional[str], st: Dict[str, Any]) -> bool:
    if not pos or not new_side or new_side == pos.side or not REVERSE_EXIT:
        return False
    log(f"[CLOSE] side={pos.side} entry={pos.entry:.2f} reason=reverse_entry")
    tg_send(f"🔁 EMRE-2 REVERSE EXIT\nClose: {pos.side} @ {pos.entry:.2f}\nReason: reverse_entry")
    st["pos"] = None
    st["cooldown_until"] = _now() + COOLDOWN_SEC
    save_state(st)
    return True

def check_tp(pos: Position, price: float, st: Dict[str, Any]) -> None:
    if pos.side == "LONG":
        if price >= pos.tp2:
            log(f"[TP2_HIT] LONG entry={pos.entry:.2f} tp2={pos.tp2:.2f} price={price:.2f}")
            tg_send(f"🟩 EMRE-2 TP2 HIT\nLONG entry={pos.entry:.2f}\nTP2={pos.tp2:.2f}\nprice={price:.2f}")
            st["pos"] = None; st["cooldown_until"] = _now() + COOLDOWN_SEC; save_state(st); return
        if price >= pos.tp1 and not pos.meta.get("tp1_hit"):
            pos.meta["tp1_hit"] = True
            log(f"[TP1_HIT] LONG entry={pos.entry:.2f} tp1={pos.tp1:.2f} price={price:.2f}")
            tg_send(f"🟩 EMRE-2 TP1 HIT\nLONG entry={pos.entry:.2f}\nTP1={pos.tp1:.2f}\nprice={price:.2f}")
            st["pos"] = asdict(pos); save_state(st); return
    else:
        if price <= pos.tp2:
            log(f"[TP2_HIT] SHORT entry={pos.entry:.2f} tp2={pos.tp2:.2f} price={price:.2f}")
            tg_send(f"🟥 EMRE-2 TP2 HIT\nSHORT entry={pos.entry:.2f}\nTP2={pos.tp2:.2f}\nprice={price:.2f}")
            st["pos"] = None; st["cooldown_until"] = _now() + COOLDOWN_SEC; save_state(st); return
        if price <= pos.tp1 and not pos.meta.get("tp1_hit"):
            pos.meta["tp1_hit"] = True
            log(f"[TP1_HIT] SHORT entry={pos.entry:.2f} tp1={pos.tp1:.2f} price={price:.2f}")
            tg_send(f"🟥 EMRE-2 TP1 HIT\nSHORT entry={pos.entry:.2f}\nTP1={pos.tp1:.2f}\nprice={price:.2f}")
            st["pos"] = asdict(pos); save_state(st); return

def check_hard_stop(pos: Position, price: float, st: Dict[str, Any]) -> None:
    if os.getenv("EMRE2_HARD_STOP", "1") != "1":
        return
    if pos.side == "LONG" and price <= pos.stop:
        log(f"[STOP] LONG entry={pos.entry:.2f} stop={pos.stop:.2f} price={price:.2f}")
        tg_send(f"🛑 EMRE-2 HARD STOP\nLONG entry={pos.entry:.2f}\nstop={pos.stop:.2f}\nprice={price:.2f}")
        st["pos"] = None; st["cooldown_until"] = _now() + COOLDOWN_SEC; save_state(st)
    if pos.side == "SHORT" and price >= pos.stop:
        log(f"[STOP] SHORT entry={pos.entry:.2f} stop={pos.stop:.2f} price={price:.2f}")
        tg_send(f"🛑 EMRE-2 HARD STOP\nSHORT entry={pos.entry:.2f}\nstop={pos.stop:.2f}\nprice={price:.2f}")
        st["pos"] = None; st["cooldown_until"] = _now() + COOLDOWN_SEC; save_state(st)

def decide_once() -> None:
    st = load_state()
    kl15 = binance_klines(SYMBOL, KL_INTERVAL_BIAS, BIAS_BARS)
    o15,h15,l15,c15,v15 = parse_ohlcv(kl15)
    kl1 = binance_klines(SYMBOL, KL_INTERVAL_ENTRY, ENTRY_BARS)
    o1,h1,l1,c1,v1 = parse_ohlcv(kl1)
    price = c1[-1]
    regime, bbw15, adx15, wr15 = classify_regime(c15, o15, h15, l15)
    atr15 = atr(h15, l15, c15, ATR_N) or 0.0
    bias, conf, bmeta = compute_bias_confidence(c15, v1, c1)
    if regime in ("RANGE","SQUEEZE"):
        raw, tmeta = range_trigger(price, c1)
    else:
        raw, tmeta = expansion_trigger(price, c1)
    final = None
    reason = []
    if raw:
        reason.append(tmeta.get("reason","trigger"))
        if conf < 0.25:
            reason.append("conf_low")
        else:
            if bias == "NEUTRAL":
                if regime in ("RANGE","SQUEEZE"):
                    final = raw; reason.append("bias_neutral_allow_range")
                else:
                    reason.append("bias_neutral_block")
            else:
                if raw == bias:
                    final = raw; reason.append("align_bias")
                else:
                    if regime in ("RANGE","SQUEEZE") and conf < 0.7:
                        final = raw; reason.append("contrarian_range_allow")
                    else:
                        reason.append("bias_block")
    if wr15 and wr15 >= WICK_RATIO_TRAP_TH and final and conf < 0.55:
        final = None; reason.append("trap_block")
    bb = bbands(c1, BB_N, BB_K)
    pb = percent_b(price, bb[0], bb[2]) if bb else None
    log(f"[DECISION] price={price:.2f} regime={regime} bbw15={bbw15:.5f} adx15={adx15:.2f} wick15={wr15:.2f} "
        f"bias={bias} conf={conf:.2f} raw={raw or 'NA'} final={final or 'NA'} pb={pb if pb is not None else 'NA'} "
        f"reason={'|'.join(reason) if reason else 'none'}")
    # manage open position
    if st.get("pos") is not None:
        pos = Position(**st["pos"])
        check_tp(pos, price, st)
        st = load_state()
        if st.get("pos") is not None:
            pos = Position(**st["pos"])
            check_hard_stop(pos, price, st)
            st = load_state()
            # compute reverse candidate (final) and reverse if needed
            if st.get("pos") is not None and final and final != pos.side:
                if maybe_reverse(pos, final, st):
                    # aggressive: open immediately
                    st = load_state()
                    st["cooldown_until"] = 0
                    save_state(st)
                    decide_once()
        return
    # open new
    if not ALLOW_TRADE:
        return
    if final and _now() >= int(st.get("cooldown_until", 0)):
        stop, tp1, tp2 = compute_levels(final, price, atr15)
        pos = Position(
            side=final, entry=price, stop=stop, tp1=tp1, tp2=tp2,
            opened_ts=_now(), last_action_ts=_now(),
            regime=regime, bias=bias, confidence=conf,
            meta={"pb": pb, "trigger": tmeta, "bias_meta": bmeta}
        )
        st["pos"] = asdict(pos)
        save_state(st)
        log(f"[OPEN] side={pos.side} entry={pos.entry:.2f} stop={pos.stop:.2f} tp1={pos.tp1:.2f} tp2={pos.tp2:.2f} regime={regime} conf={conf:.2f}")
        tg_send(f"🟦 EMRE-2 OPEN\nSide: {pos.side}\nEntry: {pos.entry:.2f}\nStop: {pos.stop:.2f}\nTP1: {pos.tp1:.2f}\nTP2: {pos.tp2:.2f}\nRegime: {regime}\nBias: {bias} (conf {conf:.2f})\npercentB: {pb if pb is not None else 'NA'}")

def main() -> None:
    global RUN
    log("=== EMRE-2 started ===")
    tg_send("EMRE-2 started ✅")
    while RUN:
        try:
            decide_once()
        except Exception as e:
            log(f"[ERROR] {e}\n{traceback.format_exc()}")
        time.sleep(LOOP_SEC)

def _handle_sigterm(signum, frame):
    global RUN
    RUN = False
    log("=== EMRE-2 stopping ===")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    main()
