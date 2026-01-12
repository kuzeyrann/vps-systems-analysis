#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, Optional

from telegram_sender import send_message

def _fmt_float(x: float) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return str(x)

class Notifier:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        msg = self._format(event_type, payload)
        if msg:
            send_message(msg)

    def _format(self, event_type: str, p: Dict[str, Any]) -> Optional[str]:
        if event_type == "HEARTBEAT":
            return f"[HEARTBEAT] price={_fmt_float(p.get('price', 0.0))} is_open={p.get('is_open')} side={p.get('side','NA')}"
        if event_type == "OPEN":
            return (
                f"🟥 EMRE OPEN\n"
                f"Side: {p.get('side')}\n"
                f"Entry: {_fmt_float(p.get('entry'))}\n"
                f"Stop: {_fmt_float(p.get('stop'))}\n"
                f"TP2: {_fmt_float(p.get('tp2'))} | TP3: {_fmt_float(p.get('tp3'))} | TP4: {_fmt_float(p.get('tp4'))}\n"
                f"Regime: {p.get('regime')} | vol_1m={p.get('vol_1m'):.5f} | range15={p.get('range15'):.5f}"
            )
        if event_type == "RISK_UPDATE":
            return (
                f"🟧 EMRE RISK UPDATE\n"
                f"Side: {p.get('side')}\n"
                f"Entry: {_fmt_float(p.get('entry'))}\n"
                f"Stop: {_fmt_float(p.get('old_stop'))} -> {_fmt_float(p.get('new_stop'))}\n"
                f"TP2: {_fmt_float(p.get('tp2'))} | TP3: {_fmt_float(p.get('tp3'))} | TP4: {_fmt_float(p.get('tp4'))}\n"
                f"meta: {p.get('meta', {})}"
            )
        if event_type == "TP1_EVENT":
            return f"🟨 EMRE TP1 EVENT\nSide: {p.get('side')} Entry: {_fmt_float(p.get('entry'))}\nTP1: {_fmt_float(p.get('tp1_price'))}"
        if event_type == "STOP_HIT":
            return (
                f"🟥 EMRE STOP HIT\n"
                f"Side: {p.get('side')} Entry: {_fmt_float(p.get('entry'))} Stop: {_fmt_float(p.get('stop'))}\n"
                f"Price: {_fmt_float(p.get('price'))}"
            )
        return None
