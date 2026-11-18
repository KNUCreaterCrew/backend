from collections.abc import Callable
from datetime import datetime, timezone

Clock = Callable[[], datetime]
"""서버의 현재 시각을 돌려준다. 테스트에서는 고정된 시각을 주입한다."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
