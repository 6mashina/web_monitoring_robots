from dataclasses import dataclass


@dataclass
class Camera:
    id: int
    name: str
    ip_address: str
    port: int
    room_id: int
