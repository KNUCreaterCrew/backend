from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.models.rooms import RoomConfig, RoomState

ROOMS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "rooms.json"


class RoomsFile(BaseModel):
    """방 배치 설정 파일의 형식."""

    rooms: tuple[RoomConfig, ...]


class RoomRepository:
    """설정 파일의 배치로 방을 만들고, 서버가 실행되는 동안 상태를 메모리에 보관한다."""

    def __init__(self, configs: Iterable[RoomConfig], *, started_at: datetime) -> None:
        self._rooms: dict[str, RoomState] = {}
        for config in configs:
            if config.room_id in self._rooms:
                raise ValueError(f"방 ID가 중복됐습니다: {config.room_id}")
            self._rooms[config.room_id] = RoomState.unobserved(config, started_at)

    @classmethod
    def from_config_file(cls, path: Path, *, started_at: datetime) -> "RoomRepository":
        rooms_file = RoomsFile.model_validate_json(path.read_bytes())
        return cls(rooms_file.rooms, started_at=started_at)

    def find(self, room_id: str) -> RoomState | None:
        return self._rooms.get(room_id)

    def all(self) -> list[RoomState]:
        return list(self._rooms.values())


def load_rooms() -> RoomRepository:
    return RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=datetime.now(timezone.utc))
