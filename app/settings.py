from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_STATS_DB_PATH = Path("var/stats.sqlite3")
"""혼잡도 기록을 쌓는 SQLite 파일의 기본 위치. 실행한 폴더 기준이며 저장소에는 올리지 않는다."""


class Settings(BaseSettings):
    """환경 변수나 `.env` 파일에서 읽는 서버 설정. 서버가 시작할 때(lifespan) 읽는다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    edge_api_key: SecretStr = Field(min_length=1, description="장치가 X-Edge-Api-Key 헤더로 보내는 인증 키")
    stats_db_path: Path = Field(default=DEFAULT_STATS_DB_PATH, description="혼잡도 기록을 쌓는 SQLite 파일 경로")


class CorsSettings(BaseSettings):
    """다른 주소에 배포한 웹이 REST를 부를 수 있게 하는 설정.

    미들웨어는 앱이 시작하기 전에 달아야 하므로 create_app()이 앱을 만들 때 읽는다.
    `app = create_app()`은 import 때 실행되므로, 장치 키처럼 필수인 값이 없어도 읽히도록 Settings와 나눴다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="REST 응답을 읽을 수 있는 웹 출처. 쉼표로 구분한다. 비어 있으면 다른 출처를 허용하지 않는다.",
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_by_comma(cls, value: object) -> object:
        # 환경 변수는 "https://a.example, https://b.example" 처럼 쉼표로 받는다(JSON 배열이 아니다).
        # 브라우저의 Origin 헤더에는 끝 '/'가 없으므로, 주소창에서 복사한 값의 '/'는 떼어 낸다.
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            return [origin.strip().rstrip("/") for origin in value if origin.strip()]
        return value
