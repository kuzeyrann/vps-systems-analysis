# TP LOGIC PATCH
# Deterministic TP1 / TP2 from stop distance
# TP1 = 0.5R, TP2 = 1.0R

def compute_tps_from_stop(entry, stop, side):
    try:
        entry = float(entry)
        stop = float(stop)
    except Exception:
        return 0.0, 0.0, 0.0, 0.0

    if entry <= 0 or stop <= 0 or side not in ("LONG", "SHORT"):
        return 0.0, 0.0, 0.0, 0.0

    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0, 0.0, 0.0, 0.0

    if side == "LONG":
        tp1 = entry + risk * 0.5
        tp2 = entry + risk * 1.0
    else:
        tp1 = entry - risk * 0.5
        tp2 = entry - risk * 1.0

    return tp1, tp2, 0.0, 0.0
