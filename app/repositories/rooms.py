from collections.abc import Iterable
from pathlib import Path

from app.models.rooms import Room

EXAMPLE_ROOM_PATH = Path(__file__).resolve().parents[1] / "data" / "example-room.json"


class RoomRepository:
    """서버가 실행되는 동안 방 상태를 메모리에 보관한다."""

    def __init__(self, rooms: Iterable[Room]) -> None:
        self._rooms = {room.room_id: room for room in rooms}

    @classmethod
    def from_json_file(cls, path: Path) -> "RoomRepository":
        return cls([Room.model_validate_json(path.read_bytes())])

    def find(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)


def load_example_rooms() -> RoomRepository:
    return RoomRepository.from_json_file(EXAMPLE_ROOM_PATH)
