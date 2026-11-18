"""시나리오를 실행하고, 단계마다 REST 조회와 WebSocket 이벤트를 대조한다.

서버와 어떻게 주고받는지는 Driver가 맡는다.
    - 시연:   실제 서버에 HTTP·WebSocket으로 보내고, 실제 시간을 기다린다. (demo/__main__.py)
    - 테스트: TestClient와 가짜 시계를 쓴다. 30초를 기다리지 않는다. (tests/test_e2e.py)
같은 시나리오와 같은 대조 규칙을 쓰므로, 시연에서 확인한 흐름을 CI가 매번 다시 확인한다.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from demo.scenario import INITIAL, ROOM_ID, STEPS, Expect, Step, build_report


class Driver(Protocol):
    start: datetime  # 시나리오의 0초에 해당하는 시각

    def wait_until(self, seconds: float) -> None:
        """시나리오 시작 후 seconds초가 될 때까지 시간을 보낸다."""

    def send(self, report: dict) -> dict:
        """장치 보고를 보내고 응답(ack)을 돌려준다."""

    def fetch(self) -> dict:
        """방 전체를 조회한다."""

    def receive(self, count: int) -> list[dict]:
        """WebSocket 이벤트를 count개 받는다."""

    def unexpected_event(self) -> dict | None:
        """이벤트가 오지 않아야 하는 단계에서, 잠시 기다려 도착한 이벤트가 있으면 돌려준다."""


# ── 웹 흉내: 조회 결과에 이벤트를 반영한다 ─────────────────────────


def apply_events(room: dict, events: list[dict], *, fetched_version: int) -> dict:
    """웹이 하는 일: 조회 응답의 version 이하인 이벤트는 버리고, 나머지를 좌석 표시와 집계에 반영한다.

    비교 기준은 조회 응답의 version(fetched_version)으로 고정한다. 한 번의 변경에서 같은 version의 이벤트가
    두 개(EDGE_STATUS_CHANGED, SEAT_UPDATED) 나가므로, 이벤트를 반영할 때마다 기준을 올리면 두 번째를 버리게 된다.
    """
    room = copy.deepcopy(room)
    seats = {seat["seat_id"]: seat for seat in room["seats"]}
    for event in events:
        if event["version"] <= fetched_version:
            continue
        if event["event"] == "EDGE_STATUS_CHANGED":
            room["edge_online"] = event["edge_online"]
        else:
            for change in event["changes"]:
                seat = seats[change["seat_id"]]
                seat["status"] = change["curr_status"]
                seat["reason"] = change["reason"]
                seat["status_since"] = change["status_since"]
                seat["last_observed_at"] = change["last_observed_at"]
            for key in ("available_seats", "unknown_seats", "congestion_level"):
                room[key] = event[key]
        room["version"] = event["version"]
    return room


def screen(room: dict) -> dict:
    """학생 화면에 보이는 것만 남긴다. 상태가 그대로인 좌석의 마지막 확인 시각은 웹이 30초마다 다시 조회해 맞추므로 뺀다."""
    return {
        "version": room["version"],
        "edge_online": room["edge_online"],
        "summary": (room["total_seats"], room["available_seats"], room["unknown_seats"], room["congestion_level"]),
        "seats": {s["seat_id"]: (s["status"], s["reason"], s["status_since"]) for s in room["seats"]},
    }


# ── 단계별 대조 ──────────────────────────────────────────────────


@dataclass
class StepResult:
    at: float
    title: str
    events: list[dict]
    room: dict
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check(expect: Expect, events: list[dict], room: dict, web: dict) -> list[str]:
    problems = []
    names = tuple(event["event"] for event in events)
    if names != expect.events:
        problems.append(f"이벤트 {names or '없음'} ≠ 기대 {expect.events or '없음'}")
    if any(event["version"] != expect.version for event in events):
        problems.append(f"이벤트 version {[e['version'] for e in events]} ≠ 기대 {expect.version}")
    actual = (room["total_seats"], room["available_seats"], room["unknown_seats"], room["congestion_level"],
              room["edge_online"], room["version"])
    wanted = (expect.total, expect.available, expect.unknown, expect.congestion, expect.edge_online, expect.version)
    if actual != wanted:
        problems.append(f"조회 결과 {actual} ≠ 기대 {wanted}")
    if screen(web) != screen(room):
        problems.append("이벤트로 다시 만든 화면이 조회 결과와 다름")
    return problems


def run_scenario(driver: Driver, steps: tuple[Step, ...] = STEPS, on_step=None) -> list[StepResult]:
    """WebSocket 연결 → 조회 → 단계 실행 순서로 진행한다. 웹의 시작 순서와 같다."""
    results = []

    # 0단계: 서버를 막 켠 방. 웹은 이 조회 응답의 version을 기준으로 기억한다.
    web = driver.fetch()
    fetched_version = web["version"]
    first = StepResult(at=0, title="서버 시작 직후 조회", events=[], room=web,
                       problems=check(INITIAL, [], web, web))
    results.append(first)
    if on_step:
        on_step(first)
    if not first.ok:
        # 시나리오는 막 켠 서버를 가정한다. 이전 상태가 남아 있으면 이후 단계의 기대값이 모두 어긋나므로 멈춘다.
        return results

    for step in steps:
        driver.wait_until(step.at)
        if step.seats is not None:
            driver.send(build_report(step, driver.start))

        # 기대한 이벤트를 받는다. 오지 않아야 하는 단계라면 잠시 기다려 본다(가능한 Driver만).
        events = driver.receive(len(step.expect.events)) if step.expect.events else []
        if not step.expect.events and (extra := driver.unexpected_event()) is not None:
            events.append(extra)

        web = apply_events(web, events, fetched_version=fetched_version)
        room = driver.fetch()
        result = StepResult(at=step.at, title=step.title, events=events, room=room,
                            problems=check(step.expect, events, room, web))
        results.append(result)
        if on_step:
            on_step(result)
    return results


__all__ = ["ROOM_ID", "Driver", "StepResult", "apply_events", "run_scenario"]
