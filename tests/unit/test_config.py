import pytest
from pydantic import ValidationError

from src.config import Settings


def test_example_configuration_loads_without_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    config = Settings(_env_file=".env.example")
    assert config.github_app_id is None
    assert config.max_webhook_bytes == 2_000_000


@pytest.mark.parametrize("field", ["max_diff_lines", "max_webhook_bytes"])
def test_resource_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
