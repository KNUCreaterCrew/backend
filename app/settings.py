from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 변수나 `.env` 파일에서 읽는 서버 설정."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    edge_api_key: SecretStr = Field(min_length=1, description="장치가 X-Edge-Api-Key 헤더로 보내는 인증 키")
