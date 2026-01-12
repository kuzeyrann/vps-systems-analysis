# EMRE v1 Modular Architecture (Locked)

- GH removed.
- TP1 is independent module; emits event only.
- Stop is B+C hybrid and updates only in improvement direction (never worse).
- TP2/TP3/TP4 are produced by RiskEngine.
- Core holds state + timers + apply/ignore decisions; no calculations.

## Timers
- Hourly heartbeat: EMRE_HOURLY_SEC (default 3600)
- Risk update tick: EMRE_RISK_UPDATE_SEC (default 900)

## RiskEnv knobs
- EMRE_K_VOL_STOP
- EMRE_MIN_STOP_BP
- EMRE_STRUCT_LOOKBACK_1M
- EMRE_STRUCT_BUFFER_BP
- EMRE_TP_M2 / M3 / M4
- EMRE_MAX_TP_DRIFT
