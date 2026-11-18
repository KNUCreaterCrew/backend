"""혼잡도 기록 저장소. 1분마다 방 요약 한 줄을 SQLite에 쌓는다.

표준 sqlite3는 동기 라이브러리다. 이 모듈의 메서드는 디스크를 기다리는 동안 이벤트 루프를 막으므로,
서버 안에서는 asyncio.to_thread로 호출한다(app/services/stats.py).
"""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class RecordSource(StrEnum):
    OBSERVED = "OBSERVED"
    """서버가 실제 장치 보고로 남긴 기록."""
    SEED = "SEED"
    """시연용으로 만든 예시 기록."""


def floor_minute(at: datetime) -> datetime:
    """시각을 UTC의 분 단위로 내린다. 10:00:59.999(KST) → 01:00:00(UTC)."""
    return at.astimezone(UTC).replace(second=0, microsecond=0)


@dataclass(frozen=True)
class RoomMinute:
    """어느 방의 어느 1분에 남긴 방 요약 한 줄. 좌석별 상태는 담지 않는다."""

    room_id: str
    recorded_at: datetime
    total_seats: int
    available_seats: int
    unknown_seats: int
    edge_online: bool
    source: RecordSource = RecordSource.OBSERVED

    def __post_init__(self) -> None:
        if self.recorded_at != floor_minute(self.recorded_at) or self.recorded_at.tzinfo is not UTC:
            raise ValueError(f"recorded_at은 UTC의 분 단위여야 합니다: {self.recorded_at.isoformat()}")


SCHEMA = """
CREATE TABLE IF NOT EXISTS room_minutes (
    room_id         TEXT    NOT NULL,
    recorded_at     TEXT    NOT NULL,  -- '2026-11-24T01:00:00+00:00' (UTC, 초는 항상 00)
    total_seats     INTEGER NOT NULL,
    available_seats INTEGER NOT NULL,
    unknown_seats   INTEGER NOT NULL,
    edge_online     INTEGER NOT NULL CHECK (edge_online IN (0, 1)),
    source          TEXT    NOT NULL CHECK (source IN ('OBSERVED', 'SEED')),
    PRIMARY KEY (room_id, recorded_at)
)
"""


class StatsStore:
    """혼잡도 기록 파일 하나를 맡는다.

    sqlite3 연결은 만든 스레드에서만 쓸 수 있고, to_thread는 매번 같은 스레드를 쓴다는 보장이 없다.
    그래서 연결을 들고 있지 않고 작업마다 새로 연다. 1분에 한 번이라 여는 비용은 무시할 만하다.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def create_schema(self) -> None:
        """파일과 테이블이 없으면 만든다. 이미 있으면 그대로 두므로 재시작해도 기록이 남는다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # closing()은 연결을 닫고, 안쪽 `conn`은 트랜잭션을 커밋한다. `with sqlite3.connect()`만으로는 연결이 닫히지 않는다.
        with closing(self._connect()) as conn, conn:
            conn.execute(SCHEMA)

    def insert(self, rows: Iterable[RoomMinute]) -> int:
        """기록을 한 트랜잭션으로 넣고, 실제로 들어간 줄 수를 돌려준다.

        같은 방·같은 분의 기록이 이미 있으면 건너뛴다(INSERT OR IGNORE). 서버를 같은 분 안에 다시 켜도
        한 줄만 남고, 시드가 실제 기록을 덮어쓰지 않는다.
        """
        params = [
            (row.room_id, row.recorded_at.isoformat(), row.total_seats, row.available_seats,
             row.unknown_seats, int(row.edge_online), row.source.value)
            for row in rows
        ]
        with closing(self._connect()) as conn, conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO room_minutes (room_id, recorded_at, total_seats, available_seats,"
                " unknown_seats, edge_online, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            return conn.total_changes - before

