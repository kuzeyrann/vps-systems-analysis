from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass(frozen=True)
class RiskSet:
    id: str
    created_ts: int
    stop: float
    tp2: float
    tp3: float
    tp4: float
    meta: Dict[str, Any] = field(default_factory=dict)
