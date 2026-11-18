from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_STATS_DB_PATH = Path("var/stats.sqlite3")
"""혼잡도 기록을 쌓는 SQLite 파일의 기본 위치. 실행한 폴더 기준이며 저장소에는 올리지 않는다."""


class Settings(BaseSettings):
    """환경 변수나 `.env` 파일에서 읽는 서버 설정."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    edge_api_key: SecretStr = Field(min_length=1, description="장치가 X-Edge-Api-Key 헤더로 보내는 인증 키")
    stats_db_path: Path = Field(default=DEFAULT_STATS_DB_PATH, description="혼잡도 기록을 쌓는 SQLite 파일 경로")
