from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

Clock = Callable[[], datetime]
"""서버의 현재 시각을 돌려준다. 테스트에서는 고정된 시각을 주입한다."""


def utc_now() -> datetime:
    return datetime.now(UTC)


SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
"""통계를 묶는 기준 시간대. 한국은 서머타임이 없어 +09:00 고정으로 충분하고, Windows에서도 tzdata 패키지가 필요 없다."""
