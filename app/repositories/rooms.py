from pathlib import Path

from app.schemas.rooms import Room

_example_path = Path(__file__).resolve().parents[1] / "data" / "example-room.json"
_example_room = Room.model_validate_json(_example_path.read_bytes())


def find_room(room_id: str) -> Room | None:
    if room_id == _example_room.room_id:
        return _example_room
    return None
