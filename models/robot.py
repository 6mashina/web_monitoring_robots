from dataclasses import dataclass
from typing import Optional


@dataclass
class Robot:
    id: int
    name: str
    is_active: bool
    mode: str
    cycles_current: int
    cycles_total: int
    oee: float
    room_id: int
    mode_color: Optional[str] = None
