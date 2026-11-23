"""혼잡도 조회 API(#25)를 확인한다. 기대값은 공통 명세 4절의 예시와 규칙을 그대로 따른다.

기록은 #24 저장소로 직접 넣고, 조회는 실제 앱으로 한다. 시각은 읽기 쉽도록 한국 시간으로 적는다.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.repositories.stats import RecordSource, RoomMinute, StatsStore, floor_minute
from tests.conftest import FakeClock

OBSERVED, SEED = RecordSource.OBSERVED, RecordSource.SEED


def kst(text: str) -> datetime:
    return datetime.fromisoformat(f"{text}+09:00")


def minutes(start: str, *values: tuple[int, int, bool], source: RecordSource = OBSERVED) -> list[RoomMinute]:
    """start(한국 시각)부터 1분씩 (빈자리, 확인 불가, 장치 연결) 기록을 만든다. 6석 방."""
    first = kst(start)
    return [
        RoomMinute("IT4-108", floor_minute(first + timedelta(minutes=i)), 6, available, unknown, online, source)
        for i, (available, unknown, online) in enumerate(values)
    ]


def repeat(value: tuple[int, int, bool], count: int) -> list[tuple[int, int, bool]]:
    return [value] * count


OFFLINE = (0, 6, False)


@pytest.fixture
def store(client, stats_db_path: Path) -> StatsStore:
    """앱이 만든 기록 파일. client보다 나중에 만들어 앱이 테이블을 만든 뒤에 쓴다."""
    return StatsStore(stats_db_path)


def daily(client, day: str | None = "2026-11-24", room_id: str = "IT4-108"):
    query = f"?date={day}" if day else ""
    return client.get(f"/api/v1/rooms/{room_id}/stats/daily{query}")


def bucket_at(body: dict, hhmm: str) -> dict:
    hour, minute = map(int, hhmm.split(":"))
    return body["buckets"][(hour * 60 + minute) // 10]


# ── 오늘의 시간대별 혼잡도 ────────────────────────────────────────


def test_daily_reproduces_the_spec_example(client, store):
    # 명세 4절: 10:00~10:05 확인된 6분, 10:06~10:09 장치 끊김, 10:10부터 10분 동안 계속 끊김
    store.insert(minutes(
        "2026-11-24T10:00",
        (2, 0, True), (2, 0, True), (1, 0, True), (1, 0, True), (2, 1, True), (2, 0, True),
        *repeat(OFFLINE, 4 + 10),
    ))

    response = daily(client)

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("room_id", "date", "bucket_minutes", "total_seats", "data_source")} == {
        "room_id": "IT4-108", "date": "2026-11-24", "bucket_minutes": 10, "total_seats": 6,
        "data_source": "OBSERVED",
    }
    assert len(body["buckets"]) == 144
    assert body["buckets"][0]["start"] == "2026-11-24T00:00:00+09:00"
    assert body["buckets"][-1]["start"] == "2026-11-24T23:50:00+09:00"
    assert bucket_at(body, "10:00") == {
        "start": "2026-11-24T10:00:00+09:00", "observed_minutes": 6,
        "avg_available_seats": 1.7, "avg_unknown_seats": 0.2, "congestion_level": "MODERATE",
    }
    assert bucket_at(body, "10:10") == {
        "start": "2026-11-24T10:10:00+09:00", "observed_minutes": 0,
        "avg_available_seats": None, "avg_unknown_seats": None, "congestion_level": None,
    }


def test_minutes_with_every_seat_unknown_are_left_out(client, store):
    # 장치는 연결돼 있지만 6석 모두 가려진 분은 확인할 수 없는 분이다. 빈자리 0으로 넣으면 만석처럼 보인다.
    store.insert(minutes("2026-11-24T10:00", (3, 0, True), (0, 6, True)))

    assert bucket_at(daily(client).json(), "10:00")["avg_available_seats"] == 3.0
    assert bucket_at(daily(client).json(), "10:00")["observed_minutes"] == 1


def test_ratio_uses_every_seat_even_when_some_are_unknown(client, store):
    # 6석 중 빈자리 2, 확인 불가 3 → 2/6 = 33.3% → MODERATE. 확인된 좌석 기준(2/3 = 66.7% LOW)이 아니다.
    store.insert(minutes("2026-11-24T10:00", (2, 3, True)))

    bucket = bucket_at(daily(client).json(), "10:00")
    assert (bucket["avg_available_seats"], bucket["avg_unknown_seats"], bucket["congestion_level"]) == (
        2.0, 3.0, "MODERATE",
    )


def test_bucket_boundaries_follow_korean_time(client, store):
    store.insert(
        minutes("2026-11-24T10:09", (1, 0, True), (3, 0, True))      # 10:09는 10:00 칸, 10:10은 10:10 칸
        + minutes("2026-11-24T23:59", (2, 0, True), (4, 0, True))    # 25일 0시 = UTC로는 24일 15:00
    )

    day = daily(client).json()
    assert bucket_at(day, "10:00")["avg_available_seats"] == 1.0
    assert bucket_at(day, "10:10")["avg_available_seats"] == 3.0
    assert bucket_at(day, "23:50")["avg_available_seats"] == 2.0  # 25일 0시는 들어오지 않는다

    next_day = daily(client, "2026-11-25").json()
    assert bucket_at(next_day, "00:00")["avg_available_seats"] == 4.0


def test_average_rounds_half_up(client, store):
    # 1,0,0,0 → 0.25. 내장 round(0.25, 1)은 0.2지만 명세는 0.05를 올린다.
    store.insert(minutes("2026-11-24T10:00", (1, 0, True), *repeat((0, 0, True), 3)))

    assert bucket_at(daily(client).json(), "10:00")["avg_available_seats"] == 0.3


def test_congestion_uses_the_rounded_average(client, store):
    # 7분 평균 25/7 = 3.571 → 3.6. 3.6/6 = 60% → LOW. 반올림 전 값(59.5%)이면 MODERATE가 되어 숫자와 색이 어긋난다.
    store.insert(minutes("2026-11-24T10:00", *repeat((3, 0, True), 3), *repeat((4, 0, True), 4)))

    bucket = bucket_at(daily(client).json(), "10:00")
    assert (bucket["avg_available_seats"], bucket["congestion_level"]) == (3.6, "LOW")


def test_day_without_records_is_all_null(client):
    body = daily(client, "2026-11-01").json()

    assert body["data_source"] is None
    assert all(bucket["observed_minutes"] == 0 and bucket["avg_available_seats"] is None
               for bucket in body["buckets"])


def test_date_defaults_to_today_in_korea(client, clock: FakeClock):
    clock.now = kst("2026-11-24T00:30")  # UTC로는 아직 23일

    assert daily(client, day=None).json()["date"] == "2026-11-24"


# ── 요일·시간대별 평균 ────────────────────────────────────────


@pytest.fixture
def four_weeks(client, store, clock: FakeClock):
    """2026-11-24(화) 10:30에 조회한다. 기간은 2026-10-27(화) ~ 2026-11-23(월)."""
    clock.now = kst("2026-11-24T10:30")
    store.insert(
        minutes("2026-10-26T10:00", (4, 0, True))                                  # 기간 전날 → 빠짐
        + minutes("2026-10-27T10:00", (1, 0, True))                                # 기간 첫날
        + minutes("2026-11-10T10:00", *repeat((3, 0, True), 30), source=SEED)      # 예시 기록
        + minutes("2026-11-17T10:00", *repeat((2, 0, True), 60))
        + minutes("2026-11-24T10:00", (4, 0, True))                                # 오늘 → 빠짐
    )


def weekly(client, weeks: int | None = None, room_id: str = "IT4-108"):
    query = f"?weeks={weeks}" if weeks is not None else ""
    return client.get(f"/api/v1/rooms/{room_id}/stats/weekly{query}")


def cell(body: dict, weekday: str, hour: int) -> dict:
    return next(c for c in body["cells"] if c["weekday"] == weekday and c["hour"] == hour)


def test_weekly_averages_by_weekday_and_hour(client, four_weeks):
    body = weekly(client).json()

    assert {key: body[key] for key in ("start_date", "end_date", "weeks", "bucket_minutes", "data_source")} == {
        "start_date": "2026-10-27", "end_date": "2026-11-23", "weeks": 4, "bucket_minutes": 60,
        "data_source": "MIXED",
    }
    assert len(body["cells"]) == 168
    assert (body["cells"][0]["weekday"], body["cells"][0]["hour"]) == ("MON", 0)
    assert (body["cells"][-1]["weekday"], body["cells"][-1]["hour"]) == ("SUN", 23)
    # 화요일 10시: 1분×1 + 30분×3 + 60분×2 = 211 / 91분 = 2.32 → 2.3, 57.5% → MODERATE
    assert cell(body, "TUE", 10) == {
        "weekday": "TUE", "hour": 10, "observed_days": 3, "observed_minutes": 91,
        "avg_available_seats": 2.3, "avg_unknown_seats": 0.0, "congestion_level": "MODERATE",
    }
    assert cell(body, "MON", 3)["avg_available_seats"] is None
    assert cell(body, "MON", 3)["observed_days"] == 0


def test_weekly_range_follows_weeks(client, four_weeks):
    body = weekly(client, weeks=1).json()

    assert (body["start_date"], body["end_date"]) == ("2026-11-17", "2026-11-23")
    assert body["data_source"] == "OBSERVED"
    tuesday = cell(body, "TUE", 10)
    assert (tuesday["observed_days"], tuesday["avg_available_seats"]) == (1, 2.0)


def test_seed_only_range_is_marked_seed(client, store, clock):
    clock.now = kst("2026-11-24T10:30")
    store.insert(minutes("2026-11-20T10:00", (3, 0, True), source=SEED))  # 금요일

    body = weekly(client, weeks=1).json()
    assert body["data_source"] == "SEED"
    assert cell(body, "FRI", 10)["avg_available_seats"] == 3.0


def test_offline_minutes_do_not_count_as_observed_days(client, store, clock):
    clock.now = kst("2026-11-24T10:30")
    store.insert(minutes("2026-11-20T10:00", *repeat(OFFLINE, 60)))  # 금요일

    friday = cell(weekly(client, weeks=1).json(), "FRI", 10)
    assert (friday["observed_days"], friday["avg_available_seats"]) == (0, None)


# ── 잘못된 요청 ────────────────────────────────────────


@pytest.mark.parametrize("path", ["/stats/daily", "/stats/weekly"])
def test_unknown_room_is_404(client, path):
    assert client.get(f"/api/v1/rooms/IT4-999{path}").status_code == 404


@pytest.mark.parametrize("query", ["date=yesterday", "date=2026-13-01", "date=2026-11-24T10:00"])
def test_bad_date_is_422(client, query):
    assert client.get(f"/api/v1/rooms/IT4-108/stats/daily?{query}").status_code == 422


@pytest.mark.parametrize("weeks", [0, 9, -1])
def test_weeks_out_of_range_is_422(client, weeks):
    assert weekly(client, weeks).status_code == 422
