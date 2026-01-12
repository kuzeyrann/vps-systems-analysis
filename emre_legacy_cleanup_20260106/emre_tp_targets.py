# emre_tp_targets.py
# Entry-aligned hedef ve stop üretimi
# Core uyumlu API:
#   compute_plan(mem, entry, side)
#   compute_targets(mem, entry, side, tp1)

def _f(x, d=0.0):
    try:
        return float(x)
    except:
        return d


def _expected_move(entry, mem):
    entry = _f(entry, 0.0)
    if entry <= 0:
        return 0.0

    r15 = _f(mem.get("range15", 0.0), 0.0)
    r60 = _f(mem.get("range60", 0.0), 0.0)

    base = max(r15, 0.5 * r60)

    regime = str(mem.get("regime", "RANGE")).upper()
    if regime == "TREND":
        base *= 1.2
    elif regime in ("HIGH_VOL", "VOL"):
        base *= 1.4
    else:
        base *= 0.8

    min_em = entry * 0.0015   # %0.15
    max_em = entry * 0.02     # %2

    if base <= 0:
        base = min_em

    return max(min_em, min(base, max_em))


def compute_plan(mem, entry, side):
    side = side.upper()
    entry = _f(entry, 0.0)

    em = _expected_move(entry, mem)
    regime = mem.get("regime", "RANGE")

    if side == "LONG":
        stop = entry - 0.7 * em
        gh   = entry + 1.0 * em
        tp2  = entry + 1.8 * em
        tp3  = entry + 3.0 * em
        tp4  = entry + 4.5 * em
    else:  # SHORT
        stop = entry + 0.7 * em
        gh   = entry - 1.0 * em
        tp2  = entry - 1.8 * em
        tp3  = entry - 3.0 * em
        tp4  = entry - 4.5 * em

    return (
        round(stop, 2),
        round(gh, 2),
        round(tp2, 2),
        round(tp3, 2),
        round(tp4, 2),
        regime,
    )


def compute_targets(mem, entry, side, tp1):
    # TP1 sonrası plan üretimi
    stop, gh, tp2, tp3, tp4, regime = compute_plan(mem, entry, side)
    return (tp2, tp3, tp4, regime)
