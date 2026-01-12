from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass(frozen=True)
class Event:
    type: str
    ts: int
    payload: Dict[str, Any]

def event(event_type: str, ts: int, payload: Optional[Dict[str, Any]] = None) -> Event:
    return Event(type=event_type, ts=ts, payload=payload or {})
