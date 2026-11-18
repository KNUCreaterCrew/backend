"""혼잡도 기록(#24)을 확인한다.

앞부분은 시계를 직접 넘겨 record_minute()의 기록 내용과 1분 경계를 확인하고,
뒷부분은 백그라운드 기록 작업과 재시작, 시드 스크립트를 확인한다.
"""

import asyncio
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clock import SEOUL
from app.main import create_app
from app.repositories.rooms import ROOMS_CONFIG_PATH, RoomRepository
from app.repositories.stats import RecordSource, RoomMinute, StatsStore, floor_minute
from app.services.stats import record_every_minute, record_minute
from demo.seed_stats import seed_rows
from tests.conftest import KST, FakeClock, settings_with_test_key
from tests.test_rooms import apply_four_seat_example


def kst(hhmmss: str, micro: int = 0) -> datetime:
    return datetime.fromisoformat(f"2026-11-24T{hhmmss}+09:00").replace(microsecond=micro)


def stored(path: Path) -> list[tuple]:
    """저장소 코드를 거치지 않고 파일을 직접 읽는다."""
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT room_id, recorded_at, total_seats, available_seats, unknown_seats, edge_online, source"
            " FROM room_minutes ORDER BY room_id, recorded_at"
        ).fetchall()


@pytest.fixture
def store(stats_db_path: Path) -> StatsStore:
    store = StatsStore(stats_db_path)
    store.create_schema()
    return store


# ── 기록 내용과 1분 경계 ────────────────────────────────────────


def test_row_matches_the_room_snapshot_summary(rooms: RoomRepository, store: StatsStore, stats_db_path):
    # 네 좌석이 각각 빈자리·사용 중·짐 있음·확인 불가 → 조회 응답과 같은 4석, 빈자리 1, 확인 불가 1
    apply_four_seat_example(rooms)

    inserted = asyncio.run(record_minute(rooms, store, floor_minute(kst("10:00:00"))))

    assert inserted == 1
    assert stored(stats_db_path) == [("IT4-101", "2026-11-24T01:00:00+00:00", 4, 1, 1, 1, "OBSERVED")]


def test_offline_room_is_recorded_as_it_is(rooms: RoomRepository, store: StatsStore, stats_db_path):
    # 막 시작한 서버의 방: 장치 끊김, 전 좌석 확인 불가. 평균에서 빼는 일은 조회(#25)가 맡고 기록은 사실 그대로다.
    asyncio.run(record_minute(rooms, store, floor_minute(kst("10:00:00"))))

    assert stored(stats_db_path) == [("IT4-101", "2026-11-24T01:00:00+00:00", 4, 0, 4, 0, "OBSERVED")]


@pytest.mark.parametrize(("now", "expected"), [
    (kst("10:00:00"), "2026-11-24T01:00:00+00:00"),
    (kst("10:00:59", 999999), "2026-11-24T01:00:00+00:00"),
    (kst("10:01:00"), "2026-11-24T01:01:00+00:00"),
    (kst("09:00:30"), "2026-11-24T00:00:00+00:00"),
    (datetime(2026, 11, 24, 0, 30, tzinfo=KST), "2026-11-23T15:30:00+00:00"),  # 한국 날짜와 UTC 날짜가 다르다
])
def test_minute_is_floored_and_stored_in_utc(now, expected):
    assert floor_minute(now).isoformat() == expected


def test_same_minute_is_recorded_once(rooms: RoomRepository, store: StatsStore, stats_db_path):
    minute = floor_minute(kst("10:00:00"))
    asyncio.run(record_minute(rooms, store, minute))

    # 같은 분 안에 서버를 다시 켠 경우: 상태가 바뀌었어도 먼저 남긴 한 줄만 둔다.
    apply_four_seat_example(rooms)
    assert asyncio.run(record_minute(rooms, store, minute)) == 0
    assert len(stored(stats_db_path)) == 1


def test_recorded_at_must_be_a_utc_minute():
    with pytest.raises(ValueError):
        RoomMinute("IT4-101", kst("10:00:30"), 4, 1, 1, True)
    with pytest.raises(ValueError):
        RoomMinute("IT4-101", kst("10:00:00"), 4, 1, 1, True)  # 분 단위지만 UTC가 아님


# ── 백그라운드 기록 작업 ────────────────────────────────────────


def wait_for_rows(path: Path, count: int) -> list[tuple]:
    deadline = time.monotonic() + 5
    while len(rows := stored(path)) < count:
        if time.monotonic() > deadline:
            raise AssertionError(f"{count}줄을 기다렸지만 {len(rows)}줄입니다: {rows}")
        time.sleep(0.01)
    return rows


def recording_app(rooms: RoomRepository, clock: FakeClock):
    return create_app(lambda: rooms, settings_with_test_key, clock, stats_check_interval=0.01)


def test_background_task_records_each_minute_and_survives_restart(stats_db_path):
    clock = FakeClock(kst("13:50:20"))

    def fresh_rooms() -> RoomRepository:
        return RoomRepository.from_config_file(ROOMS_CONFIG_PATH, started_at=clock.now)

    # 서버 시작 → 바로 13:50 기록. 시계를 13:51로 옮기면 한 줄 더.
    with TestClient(recording_app(fresh_rooms(), clock)):
        wait_for_rows(stats_db_path, 1)
        clock.now = kst("13:50:59", 999999)
        time.sleep(0.05)
        assert len(stored(stats_db_path)) == 1  # 같은 분은 건너뛴다
        clock.now = kst("13:51:00", 400000)
        wait_for_rows(stats_db_path, 2)

    # 서버를 다시 켜도(새 앱, 새 메모리) 같은 파일의 이전 기록은 남고, 새 분이 이어서 쌓인다.
    clock.now = kst("13:53:10")
    with TestClient(recording_app(fresh_rooms(), clock)):
        rows = wait_for_rows(stats_db_path, 3)

    assert [row[1] for row in rows] == [
        "2026-11-24T04:50:00+00:00", "2026-11-24T04:51:00+00:00", "2026-11-24T04:53:00+00:00",
    ]  # 13:52는 서버가 꺼져 있어 기록이 없다 → 조회에서 '확인할 수 없는 분'


def test_recording_failure_does_not_stop_the_task(rooms: RoomRepository, stats_db_path, caplog):
    class FlakyStore(StatsStore):
        """첫 기록만 실패하는 저장소."""

        failed = False

        def insert(self, rows):
            if not self.failed:
                self.failed = True
                raise sqlite3.OperationalError("database is locked")
            return super().insert(rows)

    store = FlakyStore(stats_db_path)
    store.create_schema()
    clock = FakeClock(kst("10:00:10"))

    async def scenario():
        task = asyncio.create_task(record_every_minute(rooms, store, clock=clock, interval=0.01))
        await asyncio.sleep(0.05)
        clock.now = kst("10:01:00")
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(scenario())

    assert "혼잡도 기록 실패" in caplog.text
    # 10:00은 실패해서 비고, 다음 분부터 다시 쌓인다. 실패한 분을 1초마다 다시 시도하지 않는다.
    assert [row[1] for row in stored(stats_db_path)] == ["2026-11-24T01:01:00+00:00"]


# ── 시연용 예시 기록 ────────────────────────────────────────


def test_seed_fills_past_days_only_and_marks_them(rooms: RoomRepository):
    configs = tuple(room.config for room in rooms.all())
    rows = seed_rows(configs, today=date(2026, 11, 24), days=2)

    local_days = {row.recorded_at.astimezone(SEOUL).date() for row in rows}
    assert local_days == {date(2026, 11, 22), date(2026, 11, 23)}  # 오늘(24일)은 넣지 않는다
    assert len(rows) == 2 * 1440 * len(configs)
    assert {row.source for row in rows} == {RecordSource.SEED}
    for row in rows:
        assert row.available_seats + row.unknown_seats <= row.total_seats
        if row.recorded_at.astimezone(SEOUL).hour < 8:
            assert (row.edge_online, row.available_seats, row.unknown_seats) == (False, 0, row.total_seats)

    assert rows == seed_rows(configs, today=date(2026, 11, 24), days=2)  # 몇 번을 돌려도 같다


def test_seed_does_not_overwrite_observed_rows(rooms: RoomRepository, store: StatsStore, stats_db_path):
    observed_minute = floor_minute(datetime(2026, 11, 23, 10, 0, tzinfo=KST))
    store.insert([RoomMinute("IT4-101", observed_minute, 4, 3, 0, True)])

    configs = tuple(room.config for room in rooms.all())
    rows = seed_rows(configs, today=date(2026, 11, 24), days=1)
    inserted = store.insert(rows)

    assert inserted == len(rows) - 1
    with sqlite3.connect(stats_db_path) as conn:
        assert conn.execute(
            "SELECT available_seats, source FROM room_minutes WHERE recorded_at = ?",
            (observed_minute.isoformat(),),
        ).fetchone() == (3, "OBSERVED")
