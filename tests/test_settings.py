import pytest
from pydantic import ValidationError

from app.main import create_app
from app.settings import CorsSettings, Settings


def test_edge_api_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("EDGE_API_KEY", "key-from-env")

    assert Settings(_env_file=None).edge_api_key.get_secret_value() == "key-from-env"


@pytest.mark.parametrize("value", [None, ""])
def test_server_refuses_to_start_without_a_key(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("EDGE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("EDGE_API_KEY", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_stats_db_path_is_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGE_API_KEY", "key-from-env")
    monkeypatch.setenv("STATS_DB_PATH", str(tmp_path / "render-disk" / "stats.sqlite3"))

    assert Settings(_env_file=None).stats_db_path == tmp_path / "render-disk" / "stats.sqlite3"


def test_stats_db_path_defaults_to_var(monkeypatch):
    monkeypatch.setenv("EDGE_API_KEY", "key-from-env")
    monkeypatch.delenv("STATS_DB_PATH", raising=False)

    assert str(Settings(_env_file=None).stats_db_path) == "var/stats.sqlite3"


# ── 웹 출처(CORS) ────────────────────────────────────────────────


def test_cors_origins_are_read_as_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://web.example, https://preview.example")

    assert CorsSettings(_env_file=None).cors_allow_origins == ["https://web.example", "https://preview.example"]


@pytest.mark.parametrize("value", [None, "", " , "])
def test_cors_origins_are_empty_without_a_value(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)

    assert CorsSettings(_env_file=None).cors_allow_origins == []


def test_cors_origin_trailing_slash_is_removed(monkeypatch):
    """브라우저의 Origin 헤더에는 끝 '/'가 없다. 주소창에서 복사한 값도 그대로 맞게 한다."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://web.example/")

    assert CorsSettings(_env_file=None).cors_allow_origins == ["https://web.example"]


def test_cors_settings_do_not_need_the_device_key(monkeypatch):
    """create_app()은 import 때 CORS 설정을 읽는다. 장치 키가 없어도 실패하지 않아야 한다."""
    monkeypatch.delenv("EDGE_API_KEY", raising=False)

    assert CorsSettings(_env_file=None).cors_allow_origins == []


def test_app_can_be_created_without_the_device_key(monkeypatch):
    monkeypatch.delenv("EDGE_API_KEY", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    create_app(cors_settings_loader=lambda: CorsSettings(_env_file=None))
