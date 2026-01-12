from __future__ import annotations
import os


def env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default


def env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


class RiskConfig:
    # Volatility stop params
    VOL_LOOKBACK_1M = env_int("EMRE_VOL_LOOKBACK_1M", 20)
    K_VOL_STOP = env_float("EMRE_K_VOL_STOP", 2.2)
    MIN_STOP_BP = env_float("EMRE_MIN_STOP_BP", 0.0008)

    # Structure stop params
    STRUCT_LOOKBACK_1M = env_int("EMRE_STRUCT_LOOKBACK_1M", 30)
    STRUCT_BUFFER_BP = env_float("EMRE_STRUCT_BUFFER_BP", 0.0002)

    # Phase-aware + impulse TP2
    IMPULSE_LOOKBACK_1M = env_int("EMRE_IMPULSE_LOOKBACK_1M", 15)
    TP2_IMPULSE_MULT = env_float("EMRE_TP2_IMPULSE_MULT", 1.0)
    TP2_IMPULSE_MULT_HIGHVOL = env_float("EMRE_TP2_IMPULSE_MULT_HIGHVOL", 1.2)
    HIGHVOL_THRESHOLD = env_float("EMRE_HIGHVOL_THRESHOLD", 1.5)  # meta momentum proxy (vol_1m scaled)

    # Trend projection for TP3/TP4 (TREND regime)
    TP3_TREND_MULT = env_float("EMRE_TP3_TREND_MULT", 0.5)
    TP4_TREND_MULT = env_float("EMRE_TP4_TREND_MULT", 1.2)

    # Legacy R-multiples fallback (RANGE)
    M2 = env_float("EMRE_TP_M2", 1.8)
    M3 = env_float("EMRE_TP_M3", 3.0)
    M4 = env_float("EMRE_TP_M4", 4.5)

    # Update behavior
    MAX_TP_DRIFT = env_float("EMRE_MAX_TP_DRIFT", 0.20)
