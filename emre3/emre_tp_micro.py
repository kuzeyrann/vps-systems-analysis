# emre_tp_micro.py
# TP1 micro-momentum confirmation logic
# Guarantees TP1 is on the correct side of entry

from collections import deque

_tp1_state = {
    "closes": deque(maxlen=5),
    "confirmed": False
}

def reset_tp1():
    _tp1_state["closes"].clear()
    _tp1_state["confirmed"] = False


def compute_tp1(mem, entry, side):
    if mem is None or entry is None or side not in ("LONG", "SHORT"):
        return None

    closes = mem.get("closes_1m")
    if not closes or len(closes) < 2:
        return None

    last = closes[-1]
    prev = closes[-2]

    # directional micro momentum
    if side == "LONG":
        if last <= prev:
            reset_tp1()
            return None
    else:  # SHORT
        if last >= prev:
            reset_tp1()
            return None

    _tp1_state["closes"].append(last)
    if len(_tp1_state["closes"]) < 2:
        return None

    total_move = abs(_tp1_state["closes"][-1] - _tp1_state["closes"][0])
    min_move = entry * 0.00015  # 15bp

    if total_move < min_move:
        return None

    buffer_bp = entry * 0.00005  # 5bp

    if side == "LONG":
        if last < entry + buffer_bp:
            return None
    else:
        if last > entry - buffer_bp:
            return None

    _tp1_state["confirmed"] = True
    return last
