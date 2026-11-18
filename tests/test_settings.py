import pytest
from pydantic import ValidationError

from app.settings import Settings


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
